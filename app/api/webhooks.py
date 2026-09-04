"""Razorpay Webhook Handler.

Validates signatures, ensures idempotency, and transitions PaymentLinkState.
"""

from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/webhooks", tags=["Webhooks"])

WEBHOOK_TTL = 86_400  # 24 hours

def get_redis(request: Request) -> Redis:
    return request.app.state.redis


async def verify_signature(request: Request) -> bytes:
    """Verify Razorpay webhook signature and return raw body."""
    signature = request.headers.get("x-razorpay-signature")
    if not signature:
        raise HTTPException(status_code=400, detail="Missing Razorpay signature")

    body = await request.body()
    
    expected_sig = hmac.new(
        key=settings.razorpay_webhook_secret.encode("utf-8"),
        msg=body,
        digestmod="sha256"
    ).hexdigest()
    
    if not hmac.compare_digest(expected_sig, signature):
        logger.warning("Invalid webhook signature")
        raise HTTPException(status_code=400, detail="Invalid signature")
        
    return body


@router.post("/razorpay")
async def handle_razorpay_webhook(
    request: Request,
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis)
):
    """Handle Razorpay webhook events."""
    await verify_signature(request)
    
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
        
    event_id = request.headers.get("x-razorpay-event-id") or payload.get("event_id")
    if not event_id:
        # Invalid payload
        raise HTTPException(status_code=422, detail="Missing event_id")
        
    event_type = payload.get("event")
    if event_type != "payment_link.paid":
        # Ignore other events
        return {"status": "ignored"}
        
    try:
        reference_id = payload["payload"]["payment_link"]["entity"]["reference_id"]
    except KeyError:
        raise HTTPException(status_code=422, detail="Missing reference_id in payload")
        


    # ── 1. Idempotency / Deduplication (Postgres Insert-and-Catch) ─────────
    # Note: As per ADR-002 and adversarial fixes (Gap 1), webhook idempotency completely
    # bypasses Redis to avoid race conditions. It relies entirely on the PostgreSQL UNIQUE 
    # constraint on event_id.

    # ── 2. Idempotency / Deduplication via Database insert-and-catch ──────
    # State-transition validation
    try:
        from app.db.models import WebhookEvent
        # Insert event_id first, catch UniqueViolation if duplicate
        webhook_event = WebhookEvent(event_id=event_id)
        session.add(webhook_event)
        await session.flush()
        
        result = await session.execute(
            text("SELECT id, state FROM payment_link_state WHERE reference_id = :ref FOR UPDATE"),
            {"ref": reference_id}
        )
        row = result.first()
        
        if not row:
            logger.warning("Webhook received for unknown reference_id %s", reference_id)
            await session.rollback()
            raise HTTPException(status_code=404, detail="Reference ID not found")
            
        current_state = row[1]
        
        if current_state == "PAID":
            # Genuine conflict or redundant update
            logger.warning("Webhook conflict: state is already PAID for reference_id %s", reference_id)
            await session.rollback()
            raise HTTPException(status_code=409, detail="State is already PAID")
            
        # Transition to PAID
        await session.execute(
            text("UPDATE payment_link_state SET state = 'PAID', updated_at = NOW() WHERE reference_id = :ref"),
            {"ref": reference_id}
        )
        await session.commit()
        
        logger.info("Successfully processed payment_link.paid for reference_id %s", reference_id)
        return {"status": "ok"}
    except IntegrityError as e:
        await session.rollback()
        # Duplicate event_id caught
        logger.info("Webhook %s already processed (redelivery). Ignoring.", event_id)
        return {"status": "ok"}
