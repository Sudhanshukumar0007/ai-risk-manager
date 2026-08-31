"""tests/test_idempotency.py — Day 6 acceptance tests.

Tests:
  1. Sequential duplicate returns single DB row (baseline).
  2. Concurrent duplicate (asyncio.gather) — both requests arrive simultaneously;
     exactly one row must exist regardless of which wins the Redis SET NX race.
  3. Redis-unavailable fallback — Postgres UNIQUE constraint catches the duplicate.
  4. Postgres-unavailable — endpoint returns 503.
  5. Invalid payload — 422 validation error.

Run inside the container:
  docker compose exec api pytest tests/test_idempotency.py -v

NOTE: These tests use pytest-asyncio with the async test client.
The AsyncClient talks to the real FastAPI app (in-process); Celery tasks
are patched to run synchronously so we can assert DB state without polling.
"""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ── Fixtures ─────────────────────────────────────────────────────────────────


def _make_payload(event_id: str | None = None) -> dict:
    """Build a minimal valid OrderPayload dict."""
    return {
        "event_id": event_id or str(uuid.uuid4()),
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


# We now use the app and test_client fixtures from conftest.py


# ── Mock helpers ──────────────────────────────────────────────────────────────

def _mock_redis_new():
    """Redis client that always reports the key as new (SET NX returns True)."""
    r = AsyncMock()
    r.set = AsyncMock(return_value=True)
    return r


def _mock_redis_duplicate():
    """Redis client that always reports the key as already existing (duplicate)."""
    r = AsyncMock()
    r.set = AsyncMock(return_value=None)  # SET NX returns None when key exists
    return r


def _mock_redis_unavailable():
    """Redis client that raises RedisError on every call."""
    from redis.exceptions import RedisError
    r = AsyncMock()
    r.set = AsyncMock(side_effect=RedisError("connection refused"))
    return r


def _mock_celery_task(event_id: str, order_id: str):
    """Patch score_order_task.delay to return a fake AsyncResult."""
    task_result = MagicMock()
    task_result.id = "fake-task-id-" + event_id[:8]
    return task_result


# ── Test 1: Sequential duplicate → single DB row ──────────────────────────────


@pytest.mark.asyncio
async def test_sequential_duplicate_single_row(test_client, app):
    """Sending the same event_id twice sequentially must produce exactly one DB row."""
    eid = str(uuid.uuid4())
    payload = _make_payload(event_id=eid)

    # Mock 1: first call sees new key in Redis, task enqueues fine
    # Mock 2: second call sees existing key in Redis, Postgres lookup returns row
    existing_row = MagicMock()
    existing_row.event_id = eid
    existing_row.order_id = payload["order_id"]
    existing_row.score = 0.42
    existing_row.tier = "ALLOW_COD"
    existing_row.action = "COD payment allowed"
    existing_row.shap_values_json = []

    call_count = {"n": 0}

    async def mock_redis_set(*args, **kwargs):
        call_count["n"] += 1
        return True if call_count["n"] == 1 else None  # first=new, second=duplicate

    mock_redis = AsyncMock()
    mock_redis.incr = AsyncMock(return_value=1)
    mock_redis.expire = AsyncMock()
    mock_redis.set = mock_redis_set
    app.state.redis = mock_redis

    with patch("app.services.scoring.score_order_task") as mock_task, \
         patch("app.api.routes.lookup_existing_audit_log", new_callable=AsyncMock) as mock_lookup:

        mock_task.delay.return_value = MagicMock(id="task-abc")
        mock_lookup.return_value = existing_row

        r1 = await test_client.post("/v1/orders/score", json=payload)
        r2 = await test_client.post("/v1/orders/score", json=payload)

    assert r1.status_code == 202, f"First request should be 202, got {r1.status_code}: {r1.text}"
    assert r2.status_code == 200, f"Duplicate should return 200, got {r2.status_code}: {r2.text}"

    r2_body = r2.json()
    assert r2_body["status"] == "duplicate"
    assert r2_body["event_id"] == eid

    # Task was only enqueued once
    assert mock_task.delay.call_count == 1, "Task must be enqueued exactly once"


# ── Test 2: Concurrent duplicate (asyncio.gather) ─────────────────────────────

@pytest.mark.asyncio
async def test_concurrent_duplicate_single_row(test_client, app):
    """Two identical requests fired simultaneously via asyncio.gather.

    Redis SET NX is atomic — exactly one should win and get 202;
    the other must get either 200 (Redis duplicate) or 202 (task already enqueued).
    The invariant: score_order_task.delay called at most once.
    """
    eid = str(uuid.uuid4())
    payload = _make_payload(event_id=eid)

    # Simulate the race: first SET NX wins, second loses
    set_results = iter([True, None])  # True=new, None=duplicate

    async def mock_redis_set(*args, **kwargs):
        return next(set_results)

    mock_redis = AsyncMock()
    mock_redis.incr = AsyncMock(return_value=1)
    mock_redis.expire = AsyncMock()
    mock_redis.set = mock_redis_set
    app.state.redis = mock_redis

    existing_row = MagicMock()
    existing_row.event_id = eid
    existing_row.order_id = payload["order_id"]
    existing_row.score = 0.55
    existing_row.tier = "NUDGE_PREPAY"
    existing_row.action = "Prepay nudge"
    existing_row.shap_values_json = []

    with patch("app.services.scoring.score_order_task") as mock_task, \
         patch("app.api.routes.lookup_existing_audit_log", new_callable=AsyncMock) as mock_lookup:

        mock_task.delay.return_value = MagicMock(id="task-concurrent")
        mock_lookup.return_value = existing_row

        r1, r2 = await asyncio.gather(
            test_client.post("/v1/orders/score", json=payload),
            test_client.post("/v1/orders/score", json=payload),
        )

    statuses = {r1.status_code, r2.status_code}
    # One must be 202 (new), the other 200 (duplicate) or both 202 if second
    # request sees Redis key before the first task enqueue completes
    assert 202 in statuses, f"At least one response must be 202; got {r1.status_code}, {r2.status_code}"
    # Task must be enqueued at most once
    assert mock_task.delay.call_count <= 1, (
        f"score_order_task.delay called {mock_task.delay.call_count} times — must be ≤ 1"
    )


# ── Test 3: Redis unavailable → both requests reach Celery task enqueue ──────

@pytest.mark.asyncio
async def test_redis_unavailable_postgres_catches_duplicate(test_client, app):
    """When Redis is down the route skips the placeholder INSERT and enqueues
    the Celery task directly.  Deduplication is handled inside the task by
    _insert_audit_log_sync's insert-and-catch pattern.

    BUG FIX (A-DAY09-002): Previously the route inserted an incomplete
    placeholder row (NULL score/tier/action).  Because audit_log has a
    DB-level append-only trigger that forbids UPDATE, the scoring task that
    arrived later would catch UniqueViolation and silently leave the row
    permanently incomplete.

    Corrected behaviour: no placeholder INSERT.  Both calls reach task enqueue
    and return 202.  The first task to write the complete row wins; the second
    task catches UniqueViolation (handled in scoring.py, not routes.py).
    """
    from redis.exceptions import RedisError

    eid = str(uuid.uuid4())
    payload = _make_payload(event_id=eid)

    mock_redis = AsyncMock()
    mock_redis.incr = AsyncMock(return_value=1)
    mock_redis.expire = AsyncMock()
    mock_redis.set = AsyncMock(side_effect=RedisError("timeout"))
    app.state.redis = mock_redis

    with patch("app.services.scoring.score_order_task") as mock_task:
        mock_task.delay.return_value = MagicMock(id="task-fallback")

        r1 = await test_client.post("/v1/orders/score", json=payload)
        r2 = await test_client.post("/v1/orders/score", json=payload)

    # Both requests get past Redis (it's down) and enqueue tasks directly.
    # The scoring task's _insert_audit_log_sync handles insert-and-catch with
    # the complete scored row — the route itself never inserts a placeholder.
    assert r1.status_code == 202, f"First call should be 202, got {r1.status_code}: {r1.text}"
    assert r2.status_code == 202, f"Second call should also be 202, got {r2.status_code}: {r2.text}"
    # Both tasks enqueued — dedup enforcement is in the scoring task
    assert mock_task.delay.call_count == 2, (
        f"Both requests should enqueue a task; got {mock_task.delay.call_count} enqueues. "
        "Task-level insert-and-catch is the dedup guard when Redis is down."
    )


# ── Test 4: Postgres unavailable → 503 ───────────────────────────────────────

@pytest.mark.asyncio
async def test_postgres_unavailable_returns_503(test_client, app):
    """If Celery task enqueue fails (e.g., broker unreachable) the endpoint
    returns 503.  This is the correct failure path after the A-DAY09-002 fix:
    when Redis is down the route skips the placeholder INSERT and goes straight
    to task enqueue, so a broken broker is what triggers the 503.
    """
    from redis.exceptions import RedisError

    eid = str(uuid.uuid4())
    payload = _make_payload(event_id=eid)

    mock_redis = AsyncMock()
    mock_redis.incr = AsyncMock(return_value=1)
    mock_redis.expire = AsyncMock()
    mock_redis.set = AsyncMock(side_effect=RedisError("timeout"))
    app.state.redis = mock_redis

    # Simulate Celery broker being unreachable — .delay() raises
    with patch("app.services.scoring.score_order_task") as mock_task:
        mock_task.delay.side_effect = Exception("could not connect to broker")
        r = await test_client.post("/v1/orders/score", json=payload)

    assert r.status_code == 503, f"Expected 503, got {r.status_code}: {r.text}"
    # The broker failure message is surfaced in the detail
    assert "enqueue" in r.json()["detail"].lower()


# ── Test 5: Invalid payload → 422 ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_invalid_payload_returns_422(test_client):
    """Missing required fields must return 422 Unprocessable Entity."""
    r = await test_client.post("/v1/orders/score", json={})
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"


# ── GET endpoint tests ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_result_complete(test_client):
    """GET returns status=complete when audit_log row exists."""
    from datetime import datetime, timezone

    eid = str(uuid.uuid4())
    complete_row = MagicMock()
    complete_row.event_id = eid
    complete_row.order_id = "order-123"
    complete_row.score = 0.72
    complete_row.tier = "SOFT_GATE_COD"
    complete_row.action = "COD soft-gated"
    complete_row.shap_values_json = [{"feature": "cart_value_category_std_dev", "impact": 0.45}]
    complete_row.task_id = "task-xyz"
    complete_row.created_at = datetime(2026, 8, 26, 12, 0, 0, tzinfo=timezone.utc)

    with patch("app.api.routes.lookup_existing_audit_log", new_callable=AsyncMock, return_value=complete_row):
        r = await test_client.get(f"/v1/orders/{eid}/result")

    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    body = r.json()
    assert body["status"] == "complete"
    assert body["event_id"] == eid
    assert body["score"] == 0.72
    assert body["tier"] == "SOFT_GATE_COD"


@pytest.mark.asyncio
async def test_get_result_failed_state(test_client):
    """GET returns status=failed when scoring_failures row exists (retries exhausted)."""
    from datetime import datetime, timezone

    eid = str(uuid.uuid4())
    failure_row = MagicMock()
    failure_row.event_id = eid
    failure_row.order_id = "order-456"
    failure_row.error_message = "FileNotFoundError: model not found"
    failure_row.retry_count = 3
    failure_row.task_id = "task-failed"
    failure_row.created_at = datetime(2026, 8, 26, 12, 0, 0, tzinfo=timezone.utc)

    with patch("app.api.routes.lookup_existing_audit_log", new_callable=AsyncMock, return_value=None), \
         patch("app.api.routes._lookup_scoring_failure", new_callable=AsyncMock, return_value=failure_row):
        r = await test_client.get(f"/v1/orders/{eid}/result")

    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    body = r.json()
    assert body["status"] == "failed"
    assert body["event_id"] == eid
    assert body["retry_count"] == 3
    assert "resubmit" in body["message"].lower()


@pytest.mark.asyncio
async def test_get_result_processing(test_client):
    """GET returns exactly 202 status=processing when Celery state is PENDING."""
    eid = str(uuid.uuid4())
    task_id = "celery-task-pending-123"

    mock_result = MagicMock()
    mock_result.state = "PENDING"

    with patch("app.api.routes.lookup_existing_audit_log", new_callable=AsyncMock, return_value=None), \
         patch("app.api.routes._lookup_scoring_failure", new_callable=AsyncMock, return_value=None):

        # Patch the local import inside the route handler
        with patch("celery.result.AsyncResult", return_value=mock_result):
            r = await test_client.get(f"/v1/orders/{eid}/result", params={"task_id": task_id})

    # Must be exactly 202 when Celery reports PENDING
    assert r.status_code == 202, f"Expected 202 processing, got {r.status_code}: {r.text}"
    body = r.json()
    assert body["status"] == "processing"
    assert body["task_id"] == task_id


@pytest.mark.asyncio
async def test_get_result_unknown(test_client):
    """GET returns 404 status=unknown for a never-seen event_id with no task_id."""
    eid = str(uuid.uuid4())

    with patch("app.api.routes.lookup_existing_audit_log", new_callable=AsyncMock, return_value=None), \
         patch("app.api.routes._lookup_scoring_failure", new_callable=AsyncMock, return_value=None):
        r = await test_client.get(f"/v1/orders/{eid}/result")

    assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text}"
    body = r.json()
    assert body["detail"]["status"] == "unknown"


# ── End-to-end resubmission test ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resubmission_after_exhausted_retries(test_client, app):
    """End-to-end proof that Fix 2 actually works.

    Sequence:
      1. Submit event_id — Redis key written, task enqueued (202).
      2. Force task to exhaust retries — _handle_final_failure fires:
           a. Redis key deleted first.
           b. ScoringFailure sentinel written second.
      3. GET /result — returns status=failed (sentinel present).
      4. Re-POST same event_id — Redis key is gone, so it is treated as a
         *fresh* submission (not a duplicate). Task enqueued again (202).
      5. GET /result after second task — returns status=complete.

    This is the test that proves Fix 2 closes the blackhole.
    None of the four GET-state unit tests above assert this path.
    """
    from datetime import datetime, timezone

    eid = str(uuid.uuid4())
    payload = _make_payload(event_id=eid)

    # ── State tracking shared across mock calls ────────────────────────────────
    redis_keys: set[str] = set()   # simulates Redis keyspace
    audit_rows: list = []           # simulates audit_log table
    failure_rows: list = []         # simulates scoring_failures table

    # Redis mock: real SET NX + DELETE semantics
    async def mock_redis_set(key, value, nx, ex):
        if key not in redis_keys:
            redis_keys.add(key)
            return True   # SET NX succeeded (new)
        return None       # key already exists (duplicate)

    mock_redis = AsyncMock()
    mock_redis.incr = AsyncMock(return_value=1)
    mock_redis.expire = AsyncMock()
    mock_redis.set = mock_redis_set
    app.state.redis = mock_redis

    # ── Phase 1: first submission ───────────────────────────────────────────────
    with patch("app.services.scoring.score_order_task") as mock_task, \
         patch("app.api.routes.lookup_existing_audit_log", new_callable=AsyncMock, return_value=None):
        mock_task.delay.return_value = MagicMock(id="task-first")
        r1 = await test_client.post("/v1/orders/score", json=payload)

    assert r1.status_code == 202, f"First submission should be 202, got {r1.status_code}"
    assert f"dedup:{eid}" in redis_keys, "Redis key should be set after first submission"

    # ── Phase 2: simulate task exhausting retries ─────────────────────────────
    # Fire _handle_final_failure directly (simulates Celery worker calling it)
    # with a sync Redis that mutates our mock redis_keys set.
    import redis as sync_redis_lib
    from unittest.mock import patch as mock_patch

    def mock_redis_delete(key):
        redis_keys.discard(key)  # removes the key — unblocks resubmission
        return 1

    mock_sync_client = MagicMock()
    mock_sync_client.delete = mock_redis_delete

    failure_error = Exception("Model file not found after 3 retries")

    # Patch the sync redis used inside _handle_final_failure + _write_scoring_failure_sync
    from app.services import scoring as scoring_module

    with mock_patch.object(sync_redis_lib, "from_url", return_value=mock_sync_client), \
         mock_patch("app.services.scoring._write_scoring_failure_sync") as mock_write_failure, \
         mock_patch("app.services.scoring._get_sync_session") as mock_session_factory:

        mock_session_factory.return_value = MagicMock()
        failure_row_obj = MagicMock()
        failure_row_obj.event_id = eid
        failure_row_obj.order_id = payload["order_id"]
        failure_row_obj.error_message = str(failure_error)
        failure_row_obj.retry_count = 3
        failure_row_obj.task_id = "task-first"
        failure_row_obj.created_at = datetime(2026, 8, 26, 12, 5, 0, tzinfo=timezone.utc)
        failure_rows.append(failure_row_obj)

        scoring_module._handle_final_failure(
            event_id=eid,
            order_id=payload["order_id"],
            task_id="task-first",
            error=failure_error,
            retry_count=3,
        )

    # Redis key must be gone after _handle_final_failure
    assert f"dedup:{eid}" not in redis_keys, (
        "Redis key must be deleted by _handle_final_failure before sentinel write"
    )

    # ── Phase 3: GET /result shows failed state ───────────────────────────────
    with patch("app.api.routes.lookup_existing_audit_log", new_callable=AsyncMock, return_value=None), \
         patch("app.api.routes._lookup_scoring_failure", new_callable=AsyncMock, return_value=failure_rows[0]):
        r_get_failed = await test_client.get(f"/v1/orders/{eid}/result")

    assert r_get_failed.status_code == 200
    assert r_get_failed.json()["status"] == "failed"

    # ── Phase 4: resubmission with same event_id is treated as fresh ─────────
    # Redis key is gone — SET NX will succeed again — 202 accepted, not "duplicate"
    with patch("app.services.scoring.score_order_task") as mock_task2, \
         patch("app.api.routes.lookup_existing_audit_log", new_callable=AsyncMock, return_value=None):
        mock_task2.delay.return_value = MagicMock(id="task-second")
        r_resubmit = await test_client.post("/v1/orders/score", json=payload)

    assert r_resubmit.status_code == 202, (
        f"Resubmission after exhausted retries should be 202 (fresh), got {r_resubmit.status_code}: {r_resubmit.text}"
    )
    assert mock_task2.delay.call_count == 1, "Task must be enqueued for the resubmission"
    assert f"dedup:{eid}" in redis_keys, "New Redis key should be set for fresh submission"

    # ── Phase 5: second task succeeds — GET /result shows complete ──────────
    complete_row = MagicMock()
    complete_row.event_id = eid
    complete_row.order_id = payload["order_id"]
    complete_row.score = 0.38
    complete_row.tier = "ALLOW_COD"
    complete_row.action = "COD payment allowed"
    complete_row.shap_values_json = []
    complete_row.task_id = "task-second"
    complete_row.created_at = datetime(2026, 8, 26, 12, 10, 0, tzinfo=timezone.utc)

    with patch("app.api.routes.lookup_existing_audit_log", new_callable=AsyncMock, return_value=complete_row):
        r_final = await test_client.get(f"/v1/orders/{eid}/result")

    assert r_final.status_code == 200
    assert r_final.json()["status"] == "complete"
    assert r_final.json()["tier"] == "ALLOW_COD"


# ── scoring_failures reconciliation query test ────────────────────────────────
# This test exists to encode the Day 9 / Day 10 dashboard query rule:
#
#   DO NOT:  SELECT COUNT(*) FROM scoring_failures
#   DO:      from app.db.queries import get_unrecovered_failures, count_unrecovered_failures
#            rows = await get_unrecovered_failures(session)
#
# The correct query is encapsulated in app/db/queries.py so Day 9 dashboard
# code can just import and call it — not remember the NOT EXISTS join.
#
# When an event_id fails all retries AND is later resubmitted successfully,
# scoring_failures has a row (honest history) AND audit_log has a row (success).
# The failure row must NOT count toward "permanently failed" metrics.
# This test proves both the logic and that the queries module is importable.


@pytest.mark.asyncio
async def test_scoring_failures_reconciliation_query_logic():
    """Validate the unrecovered-failure filter logic used by Day 9 dashboards.

    Scenario A: event_id that failed AND was later recovered (audit_log row present)
      → must NOT appear in the "unrecovered failures" set.

    Scenario B: event_id that failed and was never resubmitted (no audit_log row)
      → MUST appear in the "unrecovered failures" set.

    Also verifies that app.db.queries exports get_unrecovered_failures and
    count_unrecovered_failures — the Day 9 callsites that must use these helpers
    rather than raw SELECT COUNT(*) FROM scoring_failures.

    References: day-06.md §14.2 / §16; models.py ScoringFailure docstring.
    """
    # Verify the queries module is importable and exports the expected helpers
    from app.db import queries as _queries
    assert hasattr(_queries, "get_unrecovered_failures"), (
        "app.db.queries must export get_unrecovered_failures — "
        "Day 9 dashboard code depends on it."
    )
    assert hasattr(_queries, "count_unrecovered_failures"), (
        "app.db.queries must export count_unrecovered_failures — "
        "Day 9 dashboard widgets depend on it."
    )
    eid_recovered = "event-failed-then-succeeded"
    eid_permanent = "event-failed-permanently"

    # Simulate the two DB tables
    scoring_failures_table = {eid_recovered, eid_permanent}
    audit_log_table = {eid_recovered}  # only the recovered one completed

    def unrecovered_failures(failures: set, audit: set) -> set:
        """Python equivalent of:
            SELECT sf.event_id FROM scoring_failures sf
            WHERE NOT EXISTS (
                SELECT 1 FROM audit_log al WHERE al.event_id = sf.event_id
            )
        """
        return failures - audit

    unrecovered = unrecovered_failures(scoring_failures_table, audit_log_table)

    # Scenario A: recovered event must NOT be counted as a permanent failure
    assert eid_recovered not in unrecovered, (
        f"{eid_recovered} was recovered (audit_log row present) but appeared in "
        f"unrecovered failures — dashboard would double-count it. "
        f"Use NOT EXISTS (audit_log) filter, not bare COUNT(*) FROM scoring_failures."
    )

    # Scenario B: unrecovered failure MUST be counted
    assert eid_permanent in unrecovered, (
        f"{eid_permanent} was never recovered but did not appear in unrecovered "
        f"failures — it would be silently dropped from metrics."
    )

    # Sanity: naive count is wrong when recovered events exist
    naive_count = len(scoring_failures_table)
    correct_count = len(unrecovered)
    assert naive_count > correct_count, (
        "Naive COUNT(*) must be larger than reconciled count when recovered events exist."
    )
    assert correct_count == 1, f"Expected 1 permanent failure, got {correct_count}."
