"""SQLAlchemy ORM models for AI Risk Manager.

Tables created here:
  audit_log          — immutable append-only scoring record (UNIQUE event_id at DB level)
  payment_link_state — Day 7 Razorpay idempotency table (stub created now to avoid retrofit)

The append-only constraint on audit_log is enforced by a Postgres trigger
(see app/db/session.py:create_all_tables) so that application-layer bugs
cannot mutate historical records.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AuditLog(Base):
    """Immutable per-event scoring record.

    event_id carries a DB-level UNIQUE constraint — not an application-level
    check.  The correct duplicate-handling path is insert-and-catch the
    UniqueViolation, not SELECT-then-INSERT (which is race-prone under
    concurrent requests with identical event_ids).

    An append-only Postgres trigger prevents UPDATE/DELETE at the DB layer,
    ensuring the audit trail cannot be mutated by application bugs.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # DB-level uniqueness — plan §Day 6 Step 1, issue #5 fix
    event_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    order_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # Raw feature vector stored for auditability / dashboard replay
    features_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Top-3 SHAP attributions as [{feature, impact}, ...]
    shap_values_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # ALLOW_COD | NUDGE_PREPAY | SOFT_GATE_COD
    tier: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Human-readable action surfaced to merchant layer
    action: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Celery task ID — lets the caller poll for completion
    task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        # DB-level UNIQUE — the critical constraint for insert-and-catch idempotency
        UniqueConstraint("event_id", name="uq_audit_log_event_id"),
        # Composite index for dashboard queries by order
        Index("ix_audit_log_order_id_created_at", "order_id", "created_at"),
    )


class PaymentLinkState(Base):
    """Day 7 Razorpay idempotency table.

    Created now so Day 7 has no schema migration risk.

    States: PENDING_CREATE → PENDING_PREPAY → PAID | FAILED
    The deterministic reference_id is derived from order_id, so ambiguous
    network failures can be reconciled before retrying link creation.
    """

    __tablename__ = "payment_link_state"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)

    # Deterministic reference — sha256(order_id)[:32] recommended in Day 7
    reference_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)

    # Current state machine value
    state: Mapped[str] = mapped_column(String(50), nullable=False, default="PENDING_CREATE")

    # Populated after successful Razorpay response
    razorpay_link_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    razorpay_link_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ScoringFailure(Base):
    """Records event_ids where score_order_task exhausted all retries.

    Kept separate from audit_log so audit_log stays clean (append-only, only
    successfully scored orders).  On writing here the task also deletes the
    Redis dedup key, so a legitimate resubmission is treated as fresh.

    The GET /v1/orders/{event_id}/result endpoint checks this table when
    audit_log has no row, allowing clients to distinguish:
      - "processing"  (Celery task still running)
      - "failed"      (row here, Redis key deleted, can resubmit)
      - "unknown"     (404 — event_id was never seen)

    IMPORTANT — DASHBOARD QUERY PATTERN (Day 9 / Day 10):
    ─────────────────────────────────────────────────────
    When a failed event_id is subsequently resubmitted and succeeds, BOTH a
    scoring_failures row AND an audit_log row will exist for that event_id.
    The scoring_failures row is *honest history*, not an error — it records
    the first attempt's failure.

    DO NOT count permanent failures as:
        SELECT COUNT(*) FROM scoring_failures

    That double-counts event_ids that were recovered by a successful retry.

    CORRECT query for unrecovered failures (events that failed and never
    successfully completed on any subsequent attempt):

        SELECT sf.*
        FROM scoring_failures sf
        WHERE NOT EXISTS (
            SELECT 1 FROM audit_log al WHERE al.event_id = sf.event_id
        )

    Or equivalently with a LEFT JOIN:

        SELECT sf.*
        FROM scoring_failures sf
        LEFT JOIN audit_log al ON al.event_id = sf.event_id
        WHERE al.id IS NULL

    See also: day-06.md §14.2 Architectural Note.
    """

    __tablename__ = "scoring_failures"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # Same event_id as what was sent to audit_log; UNIQUE — one failure record per event
    event_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    order_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # Last error message after retries exhausted
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Celery task id that ultimately failed
    task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # How many retry attempts were made before giving up
    retry_count: Mapped[int] = mapped_column(nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
