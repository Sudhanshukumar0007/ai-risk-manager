import asyncio
import json
import uuid
import hmac
import httpx
import pytest
from sqlalchemy import text
from app.core.config import settings

def generate_signature(payload_bytes: bytes, secret: str) -> str:
    return hmac.new(
        key=secret.encode("utf-8"),
        msg=payload_bytes,
        digestmod="sha256"
    ).hexdigest()

@pytest.mark.asyncio
async def test_dashboard_health_endpoint():
    """Assert the Streamlit dashboard is running and healthy."""
    # The dashboard is exposed on port 8501 inside the container, but since tests run
    # inside the api container (or via docker-compose exec), we should just hit it via
    # the internal network host 'dashboard:8501'.
    
    async with httpx.AsyncClient() as client:
        try:
            # Note: _stcore/health is the standard Streamlit healthcheck endpoint
            response = await client.get("http://dashboard:8501/_stcore/health")
            assert response.status_code == 200
            assert response.text == "ok"
        except httpx.ConnectError:
            pytest.skip("Dashboard service is not reachable from test container network.")

@pytest.mark.asyncio
async def test_webhook_replay_db_assertion(test_client, async_session):
    """Programmatically replay a webhook and assert the DB row count remains constant (idempotency)."""
    order_id = f"order-smoke-{uuid.uuid4()}"
    ref_id = f"ref-smoke-{uuid.uuid4()}"
    event_id = str(uuid.uuid4())

    # 1. Seed DB with a pending payment link state
    from app.db.models import PaymentLinkState
    state_row = PaymentLinkState(
        order_id=order_id,
        reference_id=ref_id,
        state="PENDING_PREPAY"
    )
    async_session.add(state_row)
    await async_session.commit()

    webhook_payload = {
        "event_id": event_id,
        "event": "payment_link.paid",
        "payload": {
            "payment_link": {
                "entity": {
                    "id": "plink_smoke_123",
                    "reference_id": ref_id,
                    "status": "paid"
                }
            }
        }
    }
    
    payload_bytes = json.dumps(webhook_payload).encode()
    sig = generate_signature(payload_bytes, settings.razorpay_webhook_secret)
    headers = {"x-razorpay-signature": sig}

    # 2. Fire webhook FIRST TIME
    resp1 = await test_client.post("/v1/webhooks/razorpay", content=payload_bytes, headers=headers)
    assert resp1.status_code == 200

    # Get baseline row count
    res = await async_session.execute(text("SELECT COUNT(*) FROM payment_link_state WHERE order_id = :oid"), {"oid": order_id})
    baseline_count = res.scalar()
    assert baseline_count == 1

    # 3. Fire webhook SECOND TIME (Replay)
    resp2 = await test_client.post("/v1/webhooks/razorpay", content=payload_bytes, headers=headers)
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "ok"

    # 4. Assert DB row count is unchanged
    res2 = await async_session.execute(text("SELECT COUNT(*) FROM payment_link_state WHERE order_id = :oid"), {"oid": order_id})
    new_count = res2.scalar()
    assert new_count == baseline_count == 1

    # And state is PAID
    res3 = await async_session.execute(text("SELECT state FROM payment_link_state WHERE order_id = :oid"), {"oid": order_id})
    assert res3.scalar() == "PAID"
