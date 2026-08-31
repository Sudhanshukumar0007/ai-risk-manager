"""Celery scoring task — runs on the worker, NOT on the API request thread.

Flow (per instructions.md §9 and implementation_plan.md Day 6):

  POST /v1/orders/score (API)
    → Redis SET NX dedup check
    → enqueue score_order_task.delay(payload)   ← returns immediately
    → HTTP 202 Accepted

  score_order_task (Celery worker)
    → extract_features(payload)
    → XGBoost predict_proba
    → SHAP top-3
    → apply (t_low, t_high) router
    → Postgres insert-and-catch (UniqueViolation = duplicate, safe to ignore)
    → result stored in Celery backend (Redis DB 1)

Failure handling
────────────────
  Transient errors (DB hiccup, model load race, etc.):
    Retry up to MAX_RETRIES times with exponential backoff:
      attempt 1 → wait 5s → attempt 2 → wait 15s → attempt 3 → wait 45s → exhausted

  Retries exhausted (_handle_final_failure):
    1. Write a ScoringFailure row so the failure is observable (not silent).
    2. Delete the Redis dedup key so a legitimate resubmission is treated fresh
       (prevents the 24h blackhole where Redis says "already processed" but
       no audit row was ever written).

The LLM explanation task (Day 8) will be dispatched from inside this task
AFTER the Postgres write, so it never touches the API request/response cycle.
"""

import json
import logging
import os
from typing import Any

import joblib
import pandas as pd
import redis as sync_redis
from celery import Task
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.core.config import settings
from app.features.pipeline import extract_features
from app.ml.shap_engine import explain_prediction

logger = logging.getLogger(__name__)

# ── Retry policy (matches spec's Razorpay backoff table shape) ────────────────
MAX_RETRIES = 3
_RETRY_COUNTDOWNS = [5, 15, 45]  # seconds between attempts 1→2, 2→3, 3→exhausted

# ── Model + threshold loading (once per worker process) ───────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODEL_PATH = os.path.join(BASE_DIR, "models", "xgboost_rto_v1.base.bin")
THRESHOLDS_PATH = os.path.join(BASE_DIR, "config", "thresholds.json")

_model = None
_thresholds: dict[str, float] = {}


def _load_model():
    global _model
    if _model is None:
        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError(f"Model not found: {MODEL_PATH}")
        _model = joblib.load(MODEL_PATH)
        logger.info("XGBoost model loaded from %s", MODEL_PATH)
    return _model


def _load_thresholds() -> dict[str, float]:
    global _thresholds
    if not _thresholds:
        with open(THRESHOLDS_PATH, "r") as f:
            _thresholds = json.load(f)
        logger.info("Thresholds loaded: %s", _thresholds)
    return _thresholds


# ── Routing logic (Delegated to router.py) ───────────────────────────────────

from app.services.router import route

# ── Sync DB (Celery workers use sync SQLAlchemy) ──────────────────────────────
_sync_engine = None

def _get_sync_session() -> Session:
    global _sync_engine
    if _sync_engine is None:
        _sync_engine = create_engine(
            settings.database_url_sync, 
            pool_pre_ping=True, 
            pool_size=2, 
            max_overflow=3
        )
    return Session(_sync_engine)


def _insert_audit_log_sync(
    session: Session,
    *,
    event_id: str,
    order_id: str,
    task_id: str,
    features_json: dict,
    score: float,
    shap_values_json: list,
    tier: str,
    action: str,
) -> tuple[Any, bool]:
    """Sync insert-and-catch. Returns (row, is_new)."""
    from psycopg2.errors import UniqueViolation

    from app.db.models import AuditLog

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
        session.commit()
        session.refresh(row)
        return row, True
    except Exception as exc:
        session.rollback()
        cause = exc.__cause__ if exc.__cause__ else exc
        if isinstance(cause, UniqueViolation) or "unique" in str(exc).lower():
            logger.info("Celery: audit_log duplicate for event_id=%s — skipping", event_id)
            existing = (
                session.query(AuditLog)
                .filter(AuditLog.event_id == event_id)
                .first()
            )
            return existing, False
        raise


def _write_scoring_failure_sync(
    session: Session,
    *,
    event_id: str,
    order_id: str,
    task_id: str,
    error_message: str,
    retry_count: int,
) -> None:
    """Persist a ScoringFailure sentinel. INSERT OR IGNORE on duplicate event_id."""
    from app.db.models import ScoringFailure

    row = ScoringFailure(
        event_id=event_id,
        order_id=order_id,
        task_id=task_id,
        error_message=error_message[:1000] if error_message else None,
        retry_count=retry_count,
    )
    try:
        session.add(row)
        session.commit()
    except Exception:
        session.rollback()
        # Already have a failure record for this event — fine, ignore.
        logger.warning("ScoringFailure row already exists for event_id=%s", event_id)


def _delete_redis_dedup_key(event_id: str) -> None:
    """Delete the Redis dedup key so resubmission is treated as fresh.

    This is called only after retries are exhausted — it unblocks legitimate
    resubmissions that would otherwise be silently swallowed for 24h.
    """
    try:
        client = sync_redis.from_url(settings.redis_url, decode_responses=True)
        client.delete(f"dedup:{event_id}")
        client.close()
        logger.info("Deleted Redis dedup key for event_id=%s (task failed)", event_id)
    except Exception as exc:
        # Best-effort — don't raise; the ScoringFailure row is still written.
        logger.warning(
            "Could not delete Redis key for event_id=%s: %s — resubmission may be blocked for TTL duration",
            event_id, exc,
        )


def _handle_final_failure(
    event_id: str,
    order_id: str,
    task_id: str,
    error: Exception,
    retry_count: int,
) -> None:
    """Called when all retries are exhausted.

    Order is intentional:
      1. Delete Redis dedup key first — unblocks resubmission.
      2. Write ScoringFailure sentinel second — records the failure.

    Rationale for this order: if the process crashes between the two steps,
    we lose observability for one incident (no sentinel row) but never
    re-block a legitimate resubmission.  The inverse order (sentinel first,
    key second) re-introduces the 24h blackhole in the exact failure path
    this function exists to prevent.
    """
    logger.error(
        "score_order_task FINAL FAILURE event_id=%s after %d retries: %s",
        event_id, retry_count, error,
    )
    # Step 1: delete Redis key (unblocks resubmission — must come first)
    _delete_redis_dedup_key(event_id)

    # Step 2: write sentinel (observability — best-effort, never raises)
    session = _get_sync_session()
    try:
        _write_scoring_failure_sync(
            session,
            event_id=event_id,
            order_id=order_id,
            task_id=task_id,
            error_message=str(error),
            retry_count=retry_count,
        )
    finally:
        session.close()


# ── Celery task ───────────────────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    name="app.services.scoring.score_order_task",
    max_retries=MAX_RETRIES,
    acks_late=True,
    reject_on_worker_lost=True,
)
def score_order_task(self: Task, payload: dict[str, Any]) -> dict[str, Any]:
    """Score an order and persist to audit_log.

    Called by POST /v1/orders/score after the Redis dedup check.
    The API already returned 202; this task writes the durable result.

    On transient failure: retried up to MAX_RETRIES times with exponential
    backoff (5s → 15s → 45s).

    On final failure: ScoringFailure sentinel written; Redis key deleted.

    Args:
        payload: raw order dict from the API request body.

    Returns:
        Result dict stored in Celery backend (Redis DB 1).
    """
    event_id: str = payload["event_id"]
    order_id: str = payload["order_id"]

    try:
        # 1. Extract features
        features = extract_features(payload)

        # 2. Score
        model = _load_model()
        df = pd.DataFrame([features])
        if hasattr(model, "feature_names_in_"):
            df = df[list(model.feature_names_in_)]
        score_val: float = float(model.predict_proba(df)[0, 1])

        # 3. SHAP top-3
        shap_top3 = explain_prediction(features)

        # 4. Route (using new router)
        thresholds = _load_thresholds()
        tier, action = route(score_val, thresholds["t_low"], thresholds["t_high"])

        # 5. Persist (insert-and-catch)
        session = _get_sync_session()
        try:
            row, is_new = _insert_audit_log_sync(
                session,
                event_id=event_id,
                order_id=order_id,
                task_id=self.request.id,
                features_json=features,
                score=score_val,
                shap_values_json=shap_top3,
                tier=tier,
                action=action,
            )
        finally:
            session.close()

        # 6. Dispatch Business Actions
        if is_new:
            if tier == "NUDGE_PREPAY":
                from app.services.payment_tasks import create_payment_link_task
                cart_value = payload.get("cart_value", 0.0)
                create_payment_link_task.delay(order_id, cart_value)
            elif tier == "SOFT_GATE_COD":
                from app.services.soft_gate import apply_soft_gate
                apply_soft_gate(order_id)
                
            # 7. Dispatch LLM Explanation
            from app.services.llm_explain import explain_order_task
            explain_order_task.delay(event_id, order_id, shap_top3, score_val, tier)

        result = {
            "event_id": event_id,
            "order_id": order_id,
            "score": score_val,
            "tier": tier,
            "action": action,
            "shap_top3": shap_top3,
            "is_new_record": is_new,
        }
        logger.info(
            "score_order_task done event_id=%s score=%.4f tier=%s is_new=%s",
            event_id, score_val, tier, is_new,
        )
        return result

    except Exception as exc:
        current_retry = self.request.retries  # 0-indexed count of retries so far
        retries_remaining = MAX_RETRIES - current_retry

        if retries_remaining > 0:
            countdown = _RETRY_COUNTDOWNS[min(current_retry, len(_RETRY_COUNTDOWNS) - 1)]
            logger.warning(
                "score_order_task transient failure event_id=%s (attempt %d/%d), "
                "retrying in %ds: %s",
                event_id, current_retry + 1, MAX_RETRIES + 1, countdown, exc,
            )
            raise self.retry(exc=exc, countdown=countdown)
        else:
            # All retries exhausted — write sentinel + unblock Redis key
            _handle_final_failure(
                event_id=event_id,
                order_id=order_id,
                task_id=self.request.id or "unknown",
                error=exc,
                retry_count=current_retry,
            )
            # Re-raise so Celery marks the task as FAILURE (not SUCCESS)
            raise
