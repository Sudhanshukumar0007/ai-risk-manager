"""Database session factory and table initialisation.

Provides:
  async_engine          — SQLAlchemy async engine (asyncpg)
  AsyncSessionLocal     — async session factory
  get_db()              — FastAPI dependency that yields an AsyncSession
  create_all_tables()   — called once at app startup; also installs the
                          append-only trigger on audit_log

Append-only trigger rationale
──────────────────────────────
The trigger fires BEFORE UPDATE OR DELETE on audit_log and raises an
exception, making the table structurally immutable at the Postgres layer.
This satisfies Checkpoint 2's "Immutable audit trail" blocking criterion
without relying on application-layer discipline alone.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

logger = logging.getLogger(__name__)

# ── Engine ────────────────────────────────────────────────────────────────────

async_engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=False,
)

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


# ── Dependency ────────────────────────────────────────────────────────────────

async def get_db() -> AsyncSession:
    """FastAPI dependency — yields a managed async session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


# ── Append-only trigger DDL ───────────────────────────────────────────────────

_APPEND_ONLY_TRIGGER_SQL = """
DO $$
BEGIN
  -- Create the trigger function if it doesn't exist yet
  IF NOT EXISTS (
    SELECT 1 FROM pg_proc WHERE proname = 'audit_log_append_only'
  ) THEN
    EXECUTE $func$
      CREATE OR REPLACE FUNCTION audit_log_append_only()
      RETURNS TRIGGER LANGUAGE plpgsql AS $body$
      BEGIN
        RAISE EXCEPTION
          'audit_log is append-only: UPDATE/DELETE are forbidden (event_id=%)',
          OLD.event_id;
        RETURN NULL;
      END;
      $body$;
    $func$;
  END IF;

  -- Create the trigger if it doesn't exist yet
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'tg_audit_log_append_only'
  ) THEN
    EXECUTE $trig$
      CREATE TRIGGER tg_audit_log_append_only
      BEFORE UPDATE OR DELETE ON audit_log
      FOR EACH ROW EXECUTE FUNCTION audit_log_append_only();
    $trig$;
  END IF;
END;
$$;
"""


async def create_all_tables() -> None:
    """Create tables and install append-only trigger.

    Safe to call on every startup — uses CREATE IF NOT EXISTS semantics
    and the DO $$ block is idempotent.
    """
    from app.db.models import Base  # local import avoids circular refs at module load

    async with async_engine.begin() as conn:
        # Create all ORM-declared tables
        await conn.run_sync(Base.metadata.create_all)
        # Install append-only trigger on audit_log
        await conn.execute(
            __import__("sqlalchemy").text(_APPEND_ONLY_TRIGGER_SQL)
        )

    logger.info("DB tables and append-only trigger are ready")
