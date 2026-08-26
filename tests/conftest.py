import asyncio
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db.session import AsyncSessionLocal
from app.main import app as main_app


# ── Bug 1 fix: single event loop for the whole session ───────────────────────
# Without this, each test function may get its own event loop under
# pytest-asyncio's default mode.  The module-scoped `app` fixture creates the
# asyncpg connection pool against whichever loop is current at import time;
# any later test that runs under a *different* loop tries to tear down those
# connections and asyncpg raises "Event loop is closed".  Pinning one session-
# scoped loop makes every fixture's lifetime consistent.
@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def app():
    """Import the FastAPI app."""
    return main_app


@pytest_asyncio.fixture
async def test_client(app):
    """Async test client backed by ASGI transport."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# ── async_session fixture ─────────────────────────────────────────────────────
# Design constraints that rule out "wrap in transaction + rollback":
#   • Application code (reconcile_or_create) legitimately calls session.commit()
#     twice (once for CREATING, once after the Razorpay call succeeds).
#   • The webhook tests POST to the FastAPI ASGI app, which opens its OWN
#     session.  For the app to see seeded rows, those rows must be committed to
#     the real DB — a savepoint or unflushed write in the test session is
#     invisible to a separate connection.
#
# Strategy: plain session (SQLAlchemy 2.0 autobegin restarts a transaction
# after each commit), plus a fresh cleanup session at teardown that
# DELETE-commits all rows written during the test.  Tests use uuid-suffixed
# order_ids so collisions between concurrent or back-to-back runs are
# structurally impossible even if a previous teardown was skipped.

@pytest_asyncio.fixture
async def async_session():
    """Real async DB session; cleans up payment_link_state rows at teardown."""
    from sqlalchemy import text

    async with AsyncSessionLocal() as session:
        yield session
        # ── teardown ──────────────────────────────────────────────────────────
        # Do NOT reuse `session` here: it may be in a committed/closed state
        # after the test ran.  Open a fresh connection for the delete.

    async with AsyncSessionLocal() as cleanup:
        await cleanup.execute(text("DELETE FROM payment_link_state"))
        await cleanup.commit()


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
