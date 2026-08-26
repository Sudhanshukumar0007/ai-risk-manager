"""app/db/queries.py — Reusable query helpers for AI Risk Manager.

Contains the vetted query patterns that dashboard and reporting code (Day 9,
Day 10) MUST use.  These helpers exist to make the correct behaviour the path
of least resistance — callers import the function and get the right semantics
without having to remember schema caveats or join conditions.

Authoring guideline: add a helper here whenever a query has a non-obvious
correctness constraint (e.g. a join that must be included to avoid
double-counting) that a naive SELECT would miss.
"""

from __future__ import annotations

from typing import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# ── Scoring failure reconciliation ────────────────────────────────────────────


async def get_unrecovered_failures(
    session: AsyncSession,
    *,
    limit: int = 1000,
    offset: int = 0,
) -> Sequence[dict]:
    """Return scoring_failures rows that were NEVER subsequently recovered.

    An event_id is "recovered" when a later successful resubmission writes a
    row to audit_log.  When that happens, scoring_failures retains the original
    failure record (honest history — it is NOT deleted), so a naive::

        SELECT COUNT(*) FROM scoring_failures

    double-counts event_ids that actually succeeded on retry.

    This function applies the correct reconciliation filter::

        SELECT sf.*
        FROM scoring_failures sf
        WHERE NOT EXISTS (
            SELECT 1 FROM audit_log al WHERE al.event_id = sf.event_id
        )

    Use this function everywhere "permanently failed orders" are counted,
    displayed, or exported:
      - Day 9 dashboard failure metrics
      - Day 10 final audit report
      - Any monitoring alert threshold on failure counts

    Args:
        session: async SQLAlchemy session.
        limit:   maximum rows to return (default 1000, for dashboard paging).
        offset:  row offset for paging.

    Returns:
        List of dicts with all scoring_failures columns for unrecovered rows.

    Example::

        from app.db.queries import get_unrecovered_failures
        rows = await get_unrecovered_failures(session)
        permanent_failure_count = len(rows)
    """
    result = await session.execute(
        text(
            """
            SELECT sf.*
            FROM scoring_failures sf
            WHERE NOT EXISTS (
                SELECT 1 FROM audit_log al WHERE al.event_id = sf.event_id
            )
            ORDER BY sf.created_at DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        {"limit": limit, "offset": offset},
    )
    return [dict(row) for row in result.mappings()]


async def count_unrecovered_failures(session: AsyncSession) -> int:
    """Return the count of scoring_failures rows with no corresponding audit_log row.

    Equivalent to ``len(await get_unrecovered_failures(session))`` but issued
    as a single COUNT query — cheaper for dashboard widgets that only need the
    number.

    See get_unrecovered_failures() for the full rationale.
    """
    result = await session.execute(
        text(
            """
            SELECT COUNT(*) AS n
            FROM scoring_failures sf
            WHERE NOT EXISTS (
                SELECT 1 FROM audit_log al WHERE al.event_id = sf.event_id
            )
            """
        )
    )
    row = result.mappings().first()
    return int(row["n"]) if row else 0
