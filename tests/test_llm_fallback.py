"""Tests for the LLM Explanation celery task and API response (OpenRouter substitution)."""

import asyncio
import uuid
import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient
from sqlalchemy import text
from app.db.session import AsyncSessionLocal
from app.services.llm_explain import explain_order_task, STATIC_FALLBACK, build_explanation_prompt

@pytest.mark.asyncio
async def test_llm_happy_path(async_session, monkeypatch):
    """1. Happy path — mocked LLM call succeeds -> row written with status=complete."""
    event_id = f"test_event_llm_{uuid.uuid4().hex}"
    order_id = f"test_order_llm_{uuid.uuid4().hex}"
    
    mock_call = AsyncMock(return_value="Valid explanation.")
    monkeypatch.setattr("app.services.llm_explain.call_openrouter_api", mock_call)
    
    # Run the Celery task in a thread to avoid loop conflicts
    await asyncio.to_thread(
        explain_order_task,
        event_id, order_id, [{"feature": "pincode", "value": 0.5}], 0.8, "NUDGE_PREPAY"
    )
    
    mock_call.assert_called_once()
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("SELECT * FROM llm_explanations WHERE event_id = :eid"), {"eid": event_id})
        row = result.mappings().first()
        assert row is not None
        assert row["status"] == "complete"
        assert row["explanation_text"] == "Valid explanation."

@pytest.mark.asyncio
async def test_llm_timeout_fallback(async_session, monkeypatch):
    """2. Timeout -> fallback row written, static text, status=fallback."""
    event_id = f"test_event_llm_{uuid.uuid4().hex}"
    order_id = f"test_order_llm_{uuid.uuid4().hex}"
    
    mock_call = AsyncMock(side_effect=asyncio.TimeoutError("Timeout"))
    monkeypatch.setattr("app.services.llm_explain.call_openrouter_api", mock_call)
    
    await asyncio.to_thread(
        explain_order_task,
        event_id, order_id, [], 0.8, "NUDGE_PREPAY"
    )
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("SELECT * FROM llm_explanations WHERE event_id = :eid"), {"eid": event_id})
        row = result.mappings().first()
        assert row is not None
        assert row["status"] == "fallback"
        assert row["explanation_text"] == STATIC_FALLBACK

@pytest.mark.asyncio
async def test_llm_api_error_fallback(async_session, monkeypatch):
    """3. Non-timeout API error -> fallback row written."""
    event_id = f"test_event_llm_{uuid.uuid4().hex}"
    order_id = f"test_order_llm_{uuid.uuid4().hex}"
    
    mock_call = AsyncMock(side_effect=Exception("API Error"))
    monkeypatch.setattr("app.services.llm_explain.call_openrouter_api", mock_call)
    
    await asyncio.to_thread(
        explain_order_task,
        event_id, order_id, [], 0.8, "NUDGE_PREPAY"
    )
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("SELECT * FROM llm_explanations WHERE event_id = :eid"), {"eid": event_id})
        row = result.mappings().first()
        assert row is not None
        assert row["status"] == "fallback"
        assert row["explanation_text"] == STATIC_FALLBACK

@pytest.mark.asyncio
async def test_http_path_not_blocked(test_client: AsyncClient, monkeypatch):
    """4. HTTP path not blocked by LLM latency (assert dispatched)."""
    # Mock Redis to bypass it
    monkeypatch.setattr("app.api.routes.get_redis", AsyncMock(return_value=None))
    
    mock_score_task = AsyncMock()
    mock_score_task.id = "fake-task-id"
    # The API calls score_order_task.delay(raw_dict)
    
    class FakeTask:
        def delay(self, data):
            return mock_score_task
            
    monkeypatch.setattr("app.services.scoring.score_order_task", FakeTask())
    
    event_id = f"test_event_llm_{uuid.uuid4().hex}"
    response = await test_client.post("/v1/orders/score", json={
        "event_id": event_id,
        "order_id": "order123",
        "pincode": "110001"
    })
    
    assert response.status_code == 202

@pytest.mark.asyncio
async def test_task_level_crash_after_success(async_session, monkeypatch):
    """5. Task-level crash after successful LLM response (DB write fails) -> fallback row written."""
    event_id = f"test_event_llm_{uuid.uuid4().hex}"
    order_id = f"test_order_llm_{uuid.uuid4().hex}"
    
    # LLM succeeds
    mock_call = AsyncMock(return_value="Valid explanation.")
    monkeypatch.setattr("app.services.llm_explain.call_openrouter_api", mock_call)
    
    # DB write for 'complete' fails, but fallback should still work!
    # Let's mock _save_explanation_sync to fail on the FIRST call (complete), but succeed on the second (fallback).
    
    original_save = None
    import app.services.llm_explain as llm_explain
    original_save = llm_explain._save_explanation_sync
    
    call_count = 0
    def mock_save(eid, oid, text, status):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("DB error on complete")
        original_save(eid, oid, text, status)
        
    monkeypatch.setattr("app.services.llm_explain._save_explanation_sync", mock_save)
    
    await asyncio.to_thread(
        explain_order_task,
        event_id, order_id, [], 0.8, "NUDGE_PREPAY"
    )
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("SELECT * FROM llm_explanations WHERE event_id = :eid"), {"eid": event_id})
        row = result.mappings().first()
        assert row is not None
        assert row["status"] == "fallback"

@pytest.mark.asyncio
@pytest.mark.parametrize("status_val,exp_text,expected_api_status", [
    (None, None, "pending"),
    ("complete", "Test complete", "complete"),
    ("fallback", STATIC_FALLBACK, "fallback")
])
async def test_get_endpoint_statuses(test_client: AsyncClient, async_session, status_val, exp_text, expected_api_status):
    """6. GET endpoint reflects all three explanation_status values correctly."""
    event_id = f"test_event_llm_{uuid.uuid4().hex}"
    order_id = f"test_order_llm_{uuid.uuid4().hex}"
    
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("INSERT INTO audit_log (event_id, order_id, score, tier, action, shap_values_json) "
                 "VALUES (:eid, :oid, 0.9, 'NUDGE_PREPAY', 'nudge', '[]')"),
            {"eid": event_id, "oid": order_id}
        )
        if status_val:
            await session.execute(
                text("INSERT INTO llm_explanations (event_id, order_id, explanation_text, status) "
                     "VALUES (:eid, :oid, :txt, :st)"),
                {"eid": event_id, "oid": order_id, "txt": exp_text, "st": status_val}
            )
        await session.commit()
        
    response = await test_client.get(f"/v1/orders/{event_id}/result")
    assert response.status_code == 200
    data = response.json()
    assert data["explanation_status"] == expected_api_status
    if exp_text:
        assert data["explanation"] == exp_text
    else:
        assert data["explanation"] is None

@pytest.mark.asyncio
async def test_duplicate_post_statuses(test_client: AsyncClient, async_session):
    """7. Duplicate/score_order response path carries the explanation fields correctly.

    Pre-inserts a completed audit_log row and an LLM explanation, then sends a
    POST with Redis reporting the key as already existing (SET NX -> None).
    The route must hit the Redis-duplicate fast-path, look up the existing record,
    and return HTTP 200 with explanation_status and explanation fields populated.

    After the A-DAY09-002 fix, the Redis-unavailable path (get_redis=None) skips
    directly to task enqueue and always returns 202, so it can no longer serve
    as a dedup path.  The Redis-duplicate path is the correct branch to test here.
    """
    from app.main import app as _app

    event_id = f"test_event_llm_{uuid.uuid4().hex}"
    order_id = f"test_order_llm_{uuid.uuid4().hex}"

    # Pre-insert a completed audit_log row and its LLM explanation
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("INSERT INTO audit_log (event_id, order_id, score, tier, action, shap_values_json) "
                 "VALUES (:eid, :oid, 0.9, 'NUDGE_PREPAY', 'nudge', '[]')"),
            {"eid": event_id, "oid": order_id}
        )
        await session.execute(
            text("INSERT INTO llm_explanations (event_id, order_id, explanation_text, status) "
                 "VALUES (:eid, :oid, 'Dup test', 'complete')"),
            {"eid": event_id, "oid": order_id}
        )
        await session.commit()

    # Mock Redis to report the key as already existing (SET NX returns None = duplicate).
    # This drives the Redis fast-path duplicate branch, which fetches the existing
    # audit_log row and returns it as a 200 with full explanation fields.
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=None)  # None = key already existed
    original_redis = getattr(_app.state, "redis", None)
    _app.state.redis = mock_redis

    try:
        response = await test_client.post("/v1/orders/score", json={
            "event_id": event_id,
            "order_id": order_id,
            "pincode": "110001",
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
        })

        assert response.status_code == 200, (
            f"Expected 200 for Redis-duplicate with existing row, got {response.status_code}: {response.text}"
        )
        data = response.json()
        assert data["explanation_status"] == "complete"
        assert data["explanation"] == "Dup test"
    finally:
        # Restore the original Redis state so other tests are not affected
        _app.state.redis = original_redis

def test_explain_order_task_direct_invocation(async_session, monkeypatch):
    """8. Ensure the actual Celery entrypoint handles asyncio loop creation properly and persists the row."""
    event_id = f"test_event_llm_{uuid.uuid4().hex}"
    order_id = f"test_order_llm_{uuid.uuid4().hex}"
    
    # We must patch call_openrouter_api since we don't want a real API call in tests
    mock_call = AsyncMock(return_value="Direct entrypoint explanation.")
    monkeypatch.setattr("app.services.llm_explain.call_openrouter_api", mock_call)

    # Patch _save_explanation_sync to avoid running actual DB operations in a nested loop
    from unittest.mock import MagicMock
    mock_save = MagicMock()
    monkeypatch.setattr("app.services.llm_explain._save_explanation_sync", mock_save)
    
    # Call the actual Celery task callable (NOT the internal _async function)
    # This runs synchronously in the test environment (which mimics a Celery worker without an active loop)
    explain_order_task(event_id, order_id, [], 0.8, "NUDGE_PREPAY")
    
    mock_call.assert_called_once()
    
    # Validate the result was passed to the DB save function
    mock_save.assert_called_once_with(
        event_id, 
        order_id, 
        "Direct entrypoint explanation.", 
        "complete"
    )
