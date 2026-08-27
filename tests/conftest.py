"""Test configuration and shared fixtures.

DATABASE ISOLATION
──────────────────
Tests run against risk_db_test — a completely separate Postgres database —
never against risk_db (the production database read by the dashboard).

The DATABASE_URL env var is overridden HERE, at the very top of this file,
BEFORE any app module is imported.  This is the only safe place to do it:
app/db/session.py creates the SQLAlchemy engine at module-load time by reading
settings.database_url, so any override that happens after that import is too
late and silently ignored.

NOTE ON THE LIVE APP ENGINE
────────────────────────────
The FastAPI app (main_app) is instantiated at import time with the engine
created before this override can take effect IF the module was already loaded
by the test runner's import machinery. For tests that POST to the ASGI app
via AsyncClient, the app's database session will use whatever DATABASE_URL
was configured when the engine was built. This is a known limitation — the
DB isolation applies fully to direct session calls; the ASGI path is isolated
as long as conftest is the first module loaded (guaranteed by pytest collecting
conftest.py before any test module).

TEARDOWN STRATEGY
─────────────────
• audit_log has an append-only Postgres trigger that blocks DELETE/TRUNCATE.
  In risk_db_test we drop this trigger at startup so teardown can clean freely.
• The autouse truncation fixture is async and only runs when there IS a live
  event loop — sync-only tests skip it gracefully via the loop guard.
• payment_link_state, llm_explanations, scoring_failures are also wiped.
"""

import asyncio
import os
import uuid

# ── MUST be first — before any app.* import ──────────────────────────────────
os.environ["DATABASE_URL"] = (
    "postgresql+asyncpg://risk_user:risk_pass@postgres:5432/risk_db_test"
)
os.environ["DATABASE_URL_SYNC"] = (
    "postgresql://risk_user:risk_pass@postgres:5432/risk_db_test"
)
# ─────────────────────────────────────────────────────────────────────────────

import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.config import settings
from app.api.webhooks import get_redis

from app.db.session import AsyncSessionLocal, async_engine
from app.main import app as main_app


# ── SQL helpers ───────────────────────────────────────────────────────────────

_TRUNCATE_ALL_SQL = """
TRUNCATE TABLE
    llm_explanations,
    scoring_failures,
    payment_link_state,
    audit_log
RESTART IDENTITY CASCADE;
"""

_DROP_APPEND_ONLY_TRIGGER_SQL = """
DROP TRIGGER IF EXISTS tg_audit_log_append_only ON audit_log;
DROP FUNCTION IF EXISTS audit_log_append_only();
"""


# ── Event loop ────────────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def event_loop():
    """Single event loop for the entire test session."""
    loop = asyncio.new_event_loop()
    yield loop
    # Drain any remaining callbacks before closing
    loop.run_until_complete(loop.shutdown_asyncgens())
    loop.close()

@pytest.fixture(autouse=True)
def set_current_loop(event_loop):
    """Ensure the session event loop is always the current loop for all tests."""
    asyncio.set_event_loop(event_loop)

# ── One-time test DB setup ────────────────────────────────────────────────────
@pytest.fixture(scope="session", autouse=True)
def setup_test_database(event_loop):
    """Create tables in risk_db_test and drop the append-only trigger."""
    from app.db.models import Base

    async def _setup():
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # Drop the append-only trigger so teardown can TRUNCATE audit_log freely.
            # Must be executed as separate statements for asyncpg.
            await conn.execute(text("DROP TRIGGER IF EXISTS tg_audit_log_append_only ON audit_log"))
            await conn.execute(text("DROP FUNCTION IF EXISTS audit_log_append_only()"))

    async def _teardown():
        # Session teardown: final wipe
        async with AsyncSessionLocal() as cleanup:
            await cleanup.execute(text(_TRUNCATE_ALL_SQL))
            await cleanup.commit()
        await async_engine.dispose()

    event_loop.run_until_complete(_setup())
    yield
    event_loop.run_until_complete(_teardown())


# ── Per-test teardown ─────────────────────────────────────────────────────────
@pytest_asyncio.fixture(autouse=True)
async def truncate_after_each_test():
    """Wipe all four tables after every async test."""
    yield
    try:
        async with AsyncSessionLocal() as cleanup:
            await cleanup.execute(text(_TRUNCATE_ALL_SQL))
            await cleanup.commit()
    except Exception:
        # If the loop is in a bad state (e.g. for sync-only tests that don't
        # use the DB), silently skip — the session-level teardown will clean up.
        pass


# ── App / client fixtures ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app():
    """Import the FastAPI app."""
    return main_app


@pytest_asyncio.fixture
async def redis_client():
    """Real async Redis client pointing at the test environment Redis."""
    client = aioredis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    # Flush DB to ensure clean state
    await client.flushdb()
    yield client
    await client.aclose()

@pytest_asyncio.fixture
async def test_client(app, redis_client):
    """Async test client backed by ASGI transport with dependencies overridden."""
    app.state.redis = redis_client
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    if hasattr(app.state, 'redis'):
        del app.state.redis


# ── async_session fixture ─────────────────────────────────────────────────────
# Uses a plain session (SQLAlchemy 2.0 autobegin). Teardown is handled by the
# autouse `truncate_after_each_test` fixture, not here, so this stays simple.

@pytest_asyncio.fixture
async def async_session():
    """Real async DB session pointing at risk_db_test."""
    async with AsyncSessionLocal() as session:
        yield session


# ── Common payloads ───────────────────────────────────────────────────────────

@pytest.fixture
def valid_order_payload():
    """Build a minimal valid OrderPayload dict."""
    return {
        "event_id": str(uuid.uuid4()),
        "order_id": "order-" + str(uuid.uuid4()),
        "pincode": "110001",
        "customer_id": "cust-001",
        "category": "Electronics",
        "cart_value": 1500.0,
        "item_quantity": 2,
        "order_timestamp": "2026-08-25T02:30:00Z",
        "address_line_1": "12 Main St",
        "address_line_2": "",
        "payment_method": "COD",
        "customer_past_rto_count": 0,
        "phone_order_velocity_7d": 1,
        "device_account_reuse_count": 1,
        "account_age_days": 180,
    }
