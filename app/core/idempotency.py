"""Idempotency helpers for POST /v1/orders/score.

Design: insert-and-catch, NOT select-then-insert
─────────────────────────────────────────────────
The SELECT→INSERT pattern has a race window: two concurrent requests with
the same event_id can both pass the SELECT check and both attempt INSERT,
producing a duplicate row or an unhandled error.

The correct pattern here is:

  1. Fast path  — Redis SET NX (atomic, O(1)).
                  If the key already exists → duplicate; look up the
                  existing Postgres row by event_id and return it.

  2. Slow path  — Redis is unavailable (connection error).
                  Fall through to Postgres: attempt INSERT directly;
                  catch UniqueViolation; treat constraint violation as
                  a confirmed duplicate.

  3. Postgres unavailable — return 503.  Never process without a
                  durable deduplication record.

References: implementation_plan.md Day 6 Steps 3–4; instructions.md §7.
"""

import logging
from typing import Optional

from asyncpg import UniqueViolationError
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog

logger = logging.getLogger(__name__)

# Redis TTL for idempotency keys — 24 hours
_REDIS_TTL_SECONDS = 86_400
_KEY_PREFIX = "dedup:"


def _redis_key(event_id: str) -> str:
    return f"{_KEY_PREFIX}{event_id}"


async def redis_set_nx(redis: Redis, event_id: str) -> bool:
    """Atomically set the dedup key if not exists.

    Returns True  → key was NEW (this is the first request for this event_id).
    Returns False → key already existed (duplicate).
    Raises RedisError on connection failure — caller must fall through to Postgres.
    """
    was_set = await redis.set(_redis_key(event_id), "1", nx=True, ex=_REDIS_TTL_SECONDS)
    return bool(was_set)


async def lookup_existing_audit_log(
    session: AsyncSession, event_id: str
) -> Optional[AuditLog]:
    """Fetch an existing audit_log row by event_id (duplicate fast-path)."""
    result = await session.execute(
        text("SELECT * FROM audit_log WHERE event_id = :eid LIMIT 1"),
        {"eid": event_id},
    )
    row = result.mappings().first()
    if row is None:
        return None
    # Reconstruct a lightweight AuditLog-like object from the mapping
    obj = AuditLog()
    for col in AuditLog.__table__.columns:
        setattr(obj, col.name, row.get(col.name))
    return obj


async def insert_audit_log(
    session: AsyncSession,
    *,
    event_id: str,
    order_id: str,
    task_id: Optional[str] = None,
    features_json: Optional[dict] = None,
    score: Optional[float] = None,
    shap_values_json: Optional[list] = None,
    tier: Optional[str] = None,
    action: Optional[str] = None,
) -> tuple[AuditLog, bool]:
    """Insert a new audit_log row, catching UniqueViolation as a duplicate.

    Returns (AuditLog, is_new):
      is_new=True  → fresh INSERT succeeded.
      is_new=False → UniqueViolation caught; existing row returned.

    This is the Postgres fallback for the Redis-unavailable scenario.
    Never do SELECT before INSERT — the UNIQUE constraint is the guard.
    """
    row = AuditLog(
        event_id=event_id,
        order_id=order_id,
        task_id=task_id,
        features_json=features_json,
        score=score,
        shap_values_json=shap_values_json,
        tier=tier,
        action=action,
    )
    try:
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row, True
    except Exception as exc:
        await session.rollback()
        # asyncpg wraps constraint violations; check the cause chain
        cause = exc.__cause__ if exc.__cause__ else exc
        if isinstance(cause, UniqueViolationError) or "unique" in str(exc).lower():
            logger.info(
                "audit_log UniqueViolation for event_id=%s — returning existing row",
                event_id,
            )
            existing = await lookup_existing_audit_log(session, event_id)
            return existing, False
        # Any other error propagates — caller converts to 503
        raise
