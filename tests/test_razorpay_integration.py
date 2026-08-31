import asyncio
import hmac
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from asyncpg.exceptions import UniqueViolationError

from app.core.config import settings
from app.db.models import PaymentLinkState
from app.main import app

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_razorpay():
    """Mock the razorpay Python SDK client."""
    with patch("app.services.razorpay_client.rzp_client") as mock_client:
        yield mock_client


@pytest.fixture
def valid_webhook_payload():
    return {
        "event_id": "evt_12345",
        "event": "payment_link.paid",
        "payload": {
            "payment_link": {
                "entity": {
                    "id": "plink_test123",
                    "reference_id": "test_ref_id",
                    "status": "paid"
                }
            }
        }
    }


def generate_signature(payload_bytes: bytes, secret: str) -> str:
    return hmac.new(
        key=secret.encode("utf-8"),
        msg=payload_bytes,
        digestmod="sha256"
    ).hexdigest()

# ── Tests: Webhooks ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_malformed_webhook_rejected(test_client, async_session):
    """Payload missing event_id or reference_id returns 422 before signature logic runs (if JSON is valid) 
    or 400 if signature missing/invalid."""
    
    # Missing signature -> 400
    response = await test_client.post("/v1/webhooks/razorpay", json={"event": "payment_link.paid"})
    assert response.status_code == 400
    
    # Missing event_id -> 422
    payload_bytes = b'{"event": "payment_link.paid"}'
    sig = generate_signature(payload_bytes, settings.razorpay_webhook_secret)
    response = await test_client.post(
        "/v1/webhooks/razorpay", 
        content=payload_bytes,
        headers={"x-razorpay-signature": sig}
    )
    assert response.status_code == 422
    assert "event_id" in response.json()["detail"]


@pytest.mark.asyncio
async def test_invalid_webhook_signature_rejected(test_client, valid_webhook_payload):
    """400 returned; PaymentLinkState unchanged."""
    import json
    payload_bytes = json.dumps(valid_webhook_payload).encode()
    
    # Use wrong secret
    sig = generate_signature(payload_bytes, "wrong_secret")
    
    response = await test_client.post(
        "/v1/webhooks/razorpay", 
        content=payload_bytes,
        headers={"x-razorpay-signature": sig}
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid signature"


@pytest.mark.asyncio
async def test_valid_webhook_transitions_state(test_client, async_session, valid_webhook_payload):
    """PENDING_PREPAY -> PAID on valid payment_link.paid event."""
    import json
    import uuid

    order_id = f"order-valid-{uuid.uuid4()}"
    ref_id = f"ref-valid-{uuid.uuid4()}"

    # Seed DB
    state_row = PaymentLinkState(
        order_id=order_id,
        reference_id=ref_id,
        state="PENDING_PREPAY"
    )
    async_session.add(state_row)
    await async_session.commit()

    # Point the webhook payload at our ref_id
    valid_webhook_payload["payload"]["payment_link"]["entity"]["reference_id"] = ref_id
    payload_bytes = json.dumps(valid_webhook_payload).encode()
    sig = generate_signature(payload_bytes, settings.razorpay_webhook_secret)

    response = await test_client.post(
        "/v1/webhooks/razorpay",
        content=payload_bytes,
        headers={"x-razorpay-signature": sig}
    )
    assert response.status_code == 200

    # Verify DB — open a fresh read so we see the webhook handler's commit
    from sqlalchemy import text
    res = await async_session.execute(
        text("SELECT state FROM payment_link_state WHERE order_id = :oid"),
        {"oid": order_id},
    )
    assert res.scalar() == "PAID"


@pytest.mark.asyncio
async def test_duplicate_webhook_ignored(test_client, async_session, valid_webhook_payload):
    """Second webhook with same event_id returns 200 (idempotent); no double-processing."""
    import json
    import uuid

    order_id = f"order-dup-{uuid.uuid4()}"
    ref_id = f"ref-dup-{uuid.uuid4()}"
    event_id = str(uuid.uuid4())

    state_row = PaymentLinkState(
        order_id=order_id,
        reference_id=ref_id,
        state="PENDING_PREPAY"
    )
    async_session.add(state_row)
    await async_session.commit()

    valid_webhook_payload["event_id"] = event_id
    valid_webhook_payload["payload"]["payment_link"]["entity"]["reference_id"] = ref_id
    payload_bytes = json.dumps(valid_webhook_payload).encode()
    sig = generate_signature(payload_bytes, settings.razorpay_webhook_secret)
    headers = {"x-razorpay-signature": sig}

    resp1 = await test_client.post("/v1/webhooks/razorpay", content=payload_bytes, headers=headers)
    assert resp1.status_code == 200

    # Second call — same event_id, must be idempotent
    resp2 = await test_client.post("/v1/webhooks/razorpay", content=payload_bytes, headers=headers)
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "ok"

    # Verify state via fresh query
    from sqlalchemy import text
    res = await async_session.execute(
        text("SELECT state FROM payment_link_state WHERE order_id = :oid"),
        {"oid": order_id},
    )
    assert res.scalar() == "PAID"

@pytest.mark.asyncio
async def test_concurrent_webhook_ignored(test_client, async_session, valid_webhook_payload):
    """Multiple identical webhooks sent truly concurrently process only once."""
    import json
    import uuid
    import asyncio

    order_id = f"order-conc-{uuid.uuid4()}"
    ref_id = f"ref-conc-{uuid.uuid4()}"
    event_id = str(uuid.uuid4())

    state_row = PaymentLinkState(
        order_id=order_id,
        reference_id=ref_id,
        state="PENDING_PREPAY"
    )
    async_session.add(state_row)
    await async_session.commit()

    valid_webhook_payload["event_id"] = event_id
    valid_webhook_payload["payload"]["payment_link"]["entity"]["reference_id"] = ref_id
    payload_bytes = json.dumps(valid_webhook_payload).encode()
    sig = generate_signature(payload_bytes, settings.razorpay_webhook_secret)
    headers = {"x-razorpay-signature": sig}

    # Fire 5 concurrent requests
    async def make_req():
        # Each gets its own async client to ensure true concurrency without connection pooling bottlenecks in httpx
        from httpx import AsyncClient
        async with AsyncClient(app=test_client._transport.app, base_url="http://test") as c:
            return await c.post("/v1/webhooks/razorpay", content=payload_bytes, headers=headers)

    results = await asyncio.gather(*(make_req() for _ in range(5)))
    
    # All should return 200 (idempotent), but only one should do the actual update
    for resp in results:
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    from sqlalchemy import text
    res = await async_session.execute(
        text("SELECT state FROM payment_link_state WHERE order_id = :oid"),
        {"oid": order_id},
    )
    assert res.scalar() == "PAID"
    
    # Verify exactly one WebhookEvent row was created
    res2 = await async_session.execute(
        text("SELECT count(*) FROM webhook_events WHERE event_id = :eid"),
        {"eid": event_id},
    )
    assert res2.scalar() == 1



@pytest.mark.asyncio
async def test_conflicting_webhook_returns_409(test_client, async_session, valid_webhook_payload):
    """Webhook with new event_id for already PAID order returns 409."""
    import json
    import uuid

    order_id = f"order-conflict-{uuid.uuid4()}"
    ref_id = f"ref-conflict-{uuid.uuid4()}"

    # Seed DB with PAID state
    state_row = PaymentLinkState(
        order_id=order_id,
        reference_id=ref_id,
        state="PAID"
    )
    async_session.add(state_row)
    await async_session.commit()

    # Different event_id to bypass dedup; point at our ref_id
    valid_webhook_payload["event_id"] = str(uuid.uuid4())
    valid_webhook_payload["payload"]["payment_link"]["entity"]["reference_id"] = ref_id
    payload_bytes = json.dumps(valid_webhook_payload).encode()
    sig = generate_signature(payload_bytes, settings.razorpay_webhook_secret)

    response = await test_client.post(
        "/v1/webhooks/razorpay",
        content=payload_bytes,
        headers={"x-razorpay-signature": sig}
    )
    assert response.status_code == 409
    assert "already PAID" in response.json()["detail"]


@pytest.mark.asyncio
async def test_webhook_unknown_reference_id_handled(test_client, valid_webhook_payload):
    """Webhook for an unrecognized reference_id returns 404."""
    import json
    # Use reference_id that doesn't exist
    valid_webhook_payload["payload"]["payment_link"]["entity"]["reference_id"] = "unknown_ref"
    valid_webhook_payload["event_id"] = "evt_unknown"
    
    payload_bytes = json.dumps(valid_webhook_payload).encode()
    sig = generate_signature(payload_bytes, settings.razorpay_webhook_secret)
    
    response = await test_client.post(
        "/v1/webhooks/razorpay", 
        content=payload_bytes,
        headers={"x-razorpay-signature": sig}
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Reference ID not found"


@pytest.mark.asyncio
async def test_webhook_paid_overrides_creating_state(test_client, async_session, valid_webhook_payload):
    """If webhook arrives while state is CREATING (or LINK_CREATION_FAILED), transitions to PAID correctly."""
    import json
    import uuid

    order_id = f"order-creating-{uuid.uuid4()}"
    ref_id = f"ref-creating-{uuid.uuid4()}"

    # Seed DB with CREATING state
    state_row = PaymentLinkState(
        order_id=order_id,
        reference_id=ref_id,
        state="CREATING"
    )
    async_session.add(state_row)
    await async_session.commit()

    valid_webhook_payload["payload"]["payment_link"]["entity"]["reference_id"] = ref_id
    valid_webhook_payload["event_id"] = str(uuid.uuid4())

    payload_bytes = json.dumps(valid_webhook_payload).encode()
    sig = generate_signature(payload_bytes, settings.razorpay_webhook_secret)

    response = await test_client.post(
        "/v1/webhooks/razorpay",
        content=payload_bytes,
        headers={"x-razorpay-signature": sig}
    )
    assert response.status_code == 200

    # Verify DB via fresh query
    from sqlalchemy import text
    res = await async_session.execute(
        text("SELECT state FROM payment_link_state WHERE order_id = :oid"),
        {"oid": order_id},
    )
    assert res.scalar() == "PAID"


# ── Tests: Tasks and Router ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_payment_link_created_for_nudge_prepay(mock_razorpay, valid_order_payload):
    """NUDGE_PREPAY tier dispatches chained task, we test just the delay call."""
    from app.services.scoring import score_order_task
    from unittest.mock import patch
    
    # We mock the delay call to ensure it's dispatched
    with patch("app.services.payment_tasks.create_payment_link_task.delay") as mock_delay:
        import uuid
        payload = valid_order_payload
        payload["event_id"] = f"evt_nudge_{uuid.uuid4()}"
        payload["order_id"] = f"order_nudge_{uuid.uuid4()}"
        
        # We need to mock thresholds and predict_proba to land in NUDGE_PREPAY
        with patch("app.services.scoring._load_thresholds", return_value={"t_low": 0.2, "t_high": 0.8}):
            # A mock score of 0.5 falls between 0.2 and 0.8 (NUDGE_PREPAY)
            with patch("app.services.scoring._load_model") as mock_load_model:
                mock_model = MagicMock()
                import numpy as np
                mock_model.predict_proba.return_value = np.array([[0.5, 0.5]])
                # Use real feature names returned by extract_features
                mock_model.feature_names_in_ = [
                    "pincode_historical_rto_rate", 
                    "customer_past_rto_count", 
                    "category_baseline_rto_rate", 
                    "cart_value_category_std_dev", 
                    "item_quantity_anomaly_score", 
                    "is_night_order", 
                    "phone_order_velocity_7d", 
                    "device_account_reuse_count", 
                    "account_age_days", 
                    "address_char_length", 
                    "address_tfidf_ambiguity_score", 
                    "hub_distance_km", 
                    "is_cod_selected", 
                    "is_novel_pincode", 
                    "is_flash_sale_cart_value"
                ]
                mock_load_model.return_value = mock_model
                
                # Mock shap
                with patch("app.services.scoring.explain_prediction", return_value=[]):
                    result = score_order_task(payload)
                    
                    assert result["tier"] == "NUDGE_PREPAY"
                    mock_delay.assert_called_once_with(payload["order_id"], 1500.0)

@pytest.mark.asyncio
async def test_soft_gate_triggers_stub_no_razorpay(mock_razorpay):
    """SOFT_GATE_COD tier triggers Shopify/IVR stub, DOES NOT call Razorpay."""
    from app.services.soft_gate import apply_soft_gate
    
    # Doesn't raise, doesn't call razorpay
    apply_soft_gate("order_softgate")
    mock_razorpay.payment_link.create.assert_not_called()


@pytest.mark.asyncio
async def test_reconcile_or_create_success(async_session, mock_razorpay):
    """Test standard flow where payment link is created successfully."""
    import uuid
    from app.services.razorpay_client import reconcile_or_create

    order_id = f"order-create-{uuid.uuid4()}"
    mock_razorpay.payment_link.create.return_value = {"id": "plink_123", "short_url": "https://rzp.io/l/123"}

    link_id, url = await reconcile_or_create(async_session, order_id, 1000.0)
    assert link_id == "plink_123"

    # Verify DB
    res = await async_session.execute(
        text("SELECT state FROM payment_link_state WHERE order_id = :oid"),
        {"oid": order_id},
    )
    assert res.scalar() == "PENDING_PREPAY"


@pytest.mark.asyncio
async def test_network_timeout_no_duplicate_link(async_session, mock_razorpay):
    """Razorpay SDK call mocked to raise Timeout; retry calls reconcile_or_create which fetches existing via insert-and-catch, no new link created."""
    import uuid
    from app.services.razorpay_client import reconcile_or_create

    order_id = f"order-timeout-{uuid.uuid4()}"

    # First attempt: write CREATING row but Razorpay call fails
    mock_razorpay.payment_link.create.side_effect = Exception("Timeout")

    with pytest.raises(Exception):
        await reconcile_or_create(async_session, order_id, 1000.0)

    res = await async_session.execute(
        text("SELECT state FROM payment_link_state WHERE order_id = :oid"),
        {"oid": order_id},
    )
    assert res.scalar() == "LINK_CREATION_FAILED"  # timeout updates state before re-raising

    # Second attempt (reconciliation): Razorpay reports the link was actually created
    mock_razorpay.payment_link.create.side_effect = None
    mock_razorpay.payment_link.all.return_value = {
        "items": [{"id": "plink_found", "short_url": "https://rzp.io/l/found"}]
    }

    link_id, url = await reconcile_or_create(async_session, order_id, 1000.0)
    assert link_id == "plink_found"

    res = await async_session.execute(
        text("SELECT state FROM payment_link_state WHERE order_id = :oid"),
        {"oid": order_id},
    )
    assert res.scalar() == "PENDING_PREPAY"
