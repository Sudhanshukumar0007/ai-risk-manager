"""POST /v1/orders/score — ingestion and idempotency gateway.

Request flow (implementation_plan.md Day 6; instructions.md §9):

  1. Validate request body (Pydantic).
  2. Redis SET NX — atomic duplicate check.
     a. If Redis says DUPLICATE → look up existing Postgres row → return 200.
     b. If Redis unavailable → fall through to step 4 (Postgres is the guard).
  3. Enqueue score_order_task via Celery → return 202 Accepted immediately.
  4. Redis-unavailable fallback: attempt placeholder INSERT to establish
     the Postgres UNIQUE guard before dispatching the task.
     UniqueViolation caught here = confirmed duplicate → return 200.

The API never waits for scoring to finish.  The task ID in the 202 response
lets the caller poll GET /v1/orders/{event_id}/result (Day 7+) if needed.
"""

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.idempotency import insert_audit_log, lookup_existing_audit_log, redis_set_nx
from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["scoring"])


# ── scoring_failures lookup helper ───────────────────────────────────────────────

from sqlalchemy import text as _text


async def _lookup_scoring_failure(session: AsyncSession, event_id: str):
    """Fetch a ScoringFailure row by event_id, or None."""
    from app.db.models import ScoringFailure

    result = await session.execute(
        _text("SELECT * FROM scoring_failures WHERE event_id = :eid LIMIT 1"),
        {"eid": event_id},
    )
    row = result.mappings().first()
    if row is None:
        return None
    obj = ScoringFailure()
    for col in ScoringFailure.__table__.columns:
        setattr(obj, col.name, row.get(col.name))
    return obj


async def _lookup_llm_explanation(session: AsyncSession, event_id: str):
    """Fetch an LLMExplanation row by event_id, or None."""
    from app.db.models import LLMExplanation

    result = await session.execute(
        _text("SELECT * FROM llm_explanations WHERE event_id = :eid LIMIT 1"),
        {"eid": event_id},
    )
    row = result.mappings().first()
    if row is None:
        return None
    obj = LLMExplanation()
    for col in LLMExplanation.__table__.columns:
        setattr(obj, col.name, row.get(col.name))
    return obj



# ── Request / response models ─────────────────────────────────────────────────

class OrderPayload(BaseModel):
    """Incoming order scoring request.

    event_id must be externally generated (e.g. UUID4) and unique per event.
    order_id may be reused across retries of the same logical order.
    """

    event_id: str = Field(..., description="Idempotency key — unique per webhook delivery")
    order_id: str = Field(..., description="Logical order identifier")

    # Order attributes forwarded to feature pipeline
    pincode: str = Field(default="", description="Delivery pincode")
    customer_id: str = Field(default="", description="Customer identifier")
    category: str = Field(default="Other", description="Product category")
    cart_value: float = Field(default=0.0, ge=0)
    item_quantity: int = Field(default=1, ge=1)
    order_timestamp: str = Field(default="", description="ISO 8601 order timestamp")
    address_line_1: str = Field(default="")
    address_line_2: str = Field(default="")
    payment_method: str = Field(default="COD", description="COD or PREPAID")
    customer_past_rto_count: int = Field(default=0, ge=0)
    phone_order_velocity_7d: int = Field(default=1, ge=0)
    device_account_reuse_count: int = Field(default=1, ge=0)
    account_age_days: int = Field(default=30, ge=0)


class ScoreAcceptedResponse(BaseModel):
    status: str = "accepted"
    event_id: str
    order_id: str
    task_id: Optional[str] = None
    message: str = "Scoring task enqueued"


class ScoreDuplicateResponse(BaseModel):
    status: str = "duplicate"
    event_id: str
    order_id: str
    score: Optional[float] = None
    tier: Optional[str] = None
    action: Optional[str] = None
    shap_top3: Optional[list] = None
    explanation: Optional[str] = None
    explanation_status: str = "pending"
    message: str = "Duplicate event_id — returning existing result"


# ── Redis dependency ──────────────────────────────────────────────────────────

async def get_redis(request: Request) -> Optional[Redis]:
    """Return the shared Redis client stored on app state, or None if unavailable."""
    return getattr(request.app.state, "redis", None)


# ── Route ─────────────────────────────────────────────────────────────────────

@router.post(
    "/orders/score",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Score an order for RTO risk",
    response_description="202 Accepted (new) or 200 OK (duplicate)",
)
async def score_order(
    request: Request,
    payload: OrderPayload,
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
) -> JSONResponse:
    """Idempotent order ingestion endpoint.

    - New event: enqueues Celery task, returns 202.
    - Duplicate (Redis or Postgres): returns 200 with existing result.
    - Postgres unavailable: returns 503.
    """
    if redis is not None:
        client_ip = request.client.host if request.client else "unknown"
        rl_key = f"rate_limit:score:{client_ip}"
        try:
            current = await redis.incr(rl_key)
            if current == 1:
                await redis.expire(rl_key, 60)
            if current > 100:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many requests",
                )
        except RedisError as exc:
            logger.warning("Redis unavailable during rate limit check: %s", exc)

    event_id = payload.event_id
    order_id = payload.order_id
    raw_dict: dict[str, Any] = payload.model_dump()

    import time
    t_start = time.perf_counter()

    # ── Step 1: Redis SET NX fast path ────────────────────────────────────────
    redis_available = redis is not None
    is_redis_duplicate = False

    t_redis_start = time.perf_counter()
    if redis_available:
        try:
            is_new_in_redis = await redis_set_nx(redis, event_id)
            if not is_new_in_redis:
                is_redis_duplicate = True
        except RedisError as exc:
            logger.warning("Redis unavailable during dedup check: %s — falling through to Postgres", exc)
            redis_available = False  # treat as unavailable; Postgres is the guard
    t_redis_end = time.perf_counter()

    if is_redis_duplicate:
        # Redis key exists — the event was previously submitted.
        # Three possible states; mirror the GET endpoint's logic exactly:
        #
        #   complete   → audit_log row present (task finished successfully)
        #   failed     → scoring_failures row present (retries exhausted, key should
        #                be gone but may still exist in the edge case where delete
        #                happened before sentinel write succeeded)
        #   processing → neither row exists yet; task is still running/retrying
        #
        # NOTE: the "failed + key deleted" case never reaches this branch because
        # _handle_final_failure deletes the key first, so a resubmission after
        # exhausted retries falls through to a fresh submission correctly.
        # This branch handles "failed + key still present" (narrow crash window).
        try:
            existing = await lookup_existing_audit_log(db, event_id)
        except Exception as exc:
            logger.exception("Postgres lookup failed for duplicate event_id=%s: %s", event_id, exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database unavailable",
            )

        if existing is not None:
            # Task completed — return the scored result
            explanation_obj = await _lookup_llm_explanation(db, event_id)
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content=ScoreDuplicateResponse(
                    event_id=event_id,
                    order_id=order_id,
                    score=existing.score,
                    tier=existing.tier,
                    action=existing.action,
                    shap_top3=existing.shap_values_json,
                    explanation=explanation_obj.explanation_text if explanation_obj else None,
                    explanation_status=explanation_obj.status if explanation_obj else "pending",
                ).model_dump(),
            )

        # No audit_log row — check whether the task failed (sentinel present)
        try:
            failure = await _lookup_scoring_failure(db, event_id)
        except Exception as exc:
            logger.exception("scoring_failures lookup failed for event_id=%s: %s", event_id, exc)
            failure = None  # fall through to processing response; don't 500

        if failure is not None:
            # Task failed; key is present due to crash between delete and sentinel write
            # Return the failed state so the caller knows to wait for key TTL or contact support
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "status": "failed",
                    "event_id": failure.event_id,
                    "order_id": failure.order_id,
                    "error": failure.error_message,
                    "retry_count": failure.retry_count,
                    "task_id": failure.task_id,
                    "message": "Scoring failed after retries — Redis key TTL may delay resubmission; "
                               "safe to resubmit once the key expires or contact support",
                },
            )

        # No audit_log row, no scoring_failures row → task still running/retrying
        # Return the same processing body shape as GET /result?task_id=...
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "status": "processing",
                "event_id": event_id,
                "order_id": order_id,
                "message": "Scoring in progress — poll GET /v1/orders/{event_id}/result for result",
            },
        )


    # ── Step 2: Redis-unavailable path — enqueue task directly ───────────────
    #
    # BUG FIX (A-DAY09-002): Previously this path inserted an incomplete
    # placeholder row (NULL score/tier/action) into audit_log so that a
    # concurrent duplicate would hit a UniqueViolation.  However, audit_log has
    # a DB-level append-only trigger that forbids UPDATE — so the Celery scorer
    # that arrived later would hit UniqueViolation, detect "duplicate", silently
    # skip its own insert, and leave the placeholder permanently incomplete.
    #
    # Correct fix: do NOT insert a placeholder.  Skip straight to task enqueue.
    # The Celery task's own _insert_audit_log_sync inserts the *complete* row
    # (score, tier, action all populated).  If two tasks race (two identical
    # requests both got past Redis), the second one catches UniqueViolation and
    # returns the already-complete row — this is correct and idempotent.
    #
    # If Postgres itself is unavailable the 503 path in Step 3 covers it.

    # ── Step 3: Enqueue Celery task ───────────────────────────────────────────
    t_celery_start = time.perf_counter()
    try:
        from app.services.scoring import score_order_task  # late import avoids circular

        import asyncio
        task = await asyncio.to_thread(score_order_task.delay, raw_dict)
        task_id = task.id
        logger.info("Enqueued score_order_task id=%s for event_id=%s", task_id, event_id)
    except Exception as exc:
        logger.exception("Failed to enqueue scoring task for event_id=%s: %s", event_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not enqueue scoring task",
        )
    t_celery_end = time.perf_counter()

    t_end = time.perf_counter()
    headers = {
        "X-Trace-Redis-Ms": f"{(t_redis_end - t_redis_start) * 1000:.3f}",
        "X-Trace-Celery-Ms": f"{(t_celery_end - t_celery_start) * 1000:.3f}",
        "X-Trace-Total-Ms": f"{(t_end - t_start) * 1000:.3f}",
    }

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=ScoreAcceptedResponse(
            event_id=event_id,
            order_id=order_id,
            task_id=task_id,
        ).model_dump(),
        headers=headers,
    )


# ── Result polling endpoint ──────────────────────────────────────────────────

@router.get(
    "/orders/{event_id}/result",
    summary="Poll scoring result for a previously submitted event",
)
async def get_score_result(
    event_id: str,
    task_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return the scoring result for a submitted event_id.

    Four distinguishable states:

      HTTP 200  status=complete   — audit_log row found; scoring done.
      HTTP 200  status=failed     — scoring_failures row found; all retries
                                   exhausted; Redis key deleted; safe to resubmit.
      HTTP 202  status=processing — no DB row yet but Celery task is PENDING
                                   or STARTED (pass task_id from the 202 response).
      HTTP 404  status=unknown    — nothing found; event_id was never seen or
                                   task_id is stale/wrong.

    Args:
        event_id: the idempotency key from the original POST.
        task_id:  optional Celery task ID returned in the 202 response;
                  used to distinguish "processing" from "unknown".
    """
    # ── 1. Check audit_log (happy path) ───────────────────────────────────
    try:
        row = await lookup_existing_audit_log(db, event_id)
    except Exception as exc:
        logger.exception("DB error fetching audit_log for event_id=%s: %s", event_id, exc)
        raise HTTPException(status_code=503, detail="Database unavailable")

    if row is not None:
        explanation_obj = await _lookup_llm_explanation(db, event_id)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "complete",
                "event_id": row.event_id,
                "order_id": row.order_id,
                "score": row.score,
                "tier": row.tier,
                "action": row.action,
                "shap_top3": row.shap_values_json,
                "task_id": row.task_id,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "explanation": explanation_obj.explanation_text if explanation_obj else None,
                "explanation_status": explanation_obj.status if explanation_obj else "pending",
            },
        )

    # ── 2. Check scoring_failures (task exhausted retries) ────────────────
    try:
        failure = await _lookup_scoring_failure(db, event_id)
    except Exception as exc:
        logger.exception("DB error fetching scoring_failures for event_id=%s: %s", event_id, exc)
        raise HTTPException(status_code=503, detail="Database unavailable")

    if failure is not None:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "failed",
                "event_id": failure.event_id,
                "order_id": failure.order_id,
                "error": failure.error_message,
                "retry_count": failure.retry_count,
                "task_id": failure.task_id,
                "created_at": failure.created_at.isoformat() if failure.created_at else None,
                "message": "Scoring failed after retries — safe to resubmit with the same event_id",
            },
        )

    # ── 3. Check Celery task status (task still running) ──────────────────
    if task_id:
        try:
            from celery.result import AsyncResult
            result = AsyncResult(task_id, app=__import__("app.core.celery_app", fromlist=["celery_app"]).celery_app)
            celery_state = result.state  # PENDING / STARTED / RETRY / SUCCESS / FAILURE
            if celery_state in ("PENDING", "STARTED", "RETRY"):
                return JSONResponse(
                    status_code=status.HTTP_202_ACCEPTED,
                    content={
                        "status": "processing",
                        "event_id": event_id,
                        "task_id": task_id,
                        "celery_state": celery_state,
                        "message": "Scoring in progress — poll again shortly",
                    },
                )
        except Exception as exc:
            logger.warning("Could not check Celery state for task_id=%s: %s", task_id, exc)

    # ── 4. Truly unknown ──────────────────────────────────────────────────
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "status": "unknown",
            "event_id": event_id,
            "message": "No record found — event_id was never submitted or task_id is stale",
        },
    )
