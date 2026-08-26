"""Razorpay Sandbox integration for NUDGE_PREPAY tier.

Ensures reconciliation-safe payment link creation.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Optional

import razorpay
from asyncpg.exceptions import UniqueViolationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import PaymentLinkState

logger = logging.getLogger(__name__)

# Note: Using synchronous client as Razorpay Python SDK does not support native async
rzp_client = razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))


def make_reference_id(order_id: str) -> str:
    """Generate a deterministic reference ID for Razorpay.
    
    Using sha256 to ensure it's predictable across retries but avoids
    accidental collisions with internal DB IDs if order_ids are simple.
    """
    return hashlib.sha256(order_id.encode("utf-8")).hexdigest()[:32]


def create_payment_link(order_id: str, cart_value: float, reference_id: str) -> tuple[str, str]:
    """Call Razorpay Sandbox to create a payment link.
    
    Applies the ₹50 discount context.
    
    Returns:
        (link_id, short_url)
    """
    discount = 50.0
    amount_to_pay = max(cart_value - discount, 0)
    
    logger.info("Creating Razorpay payment link for %s (amount: %s, discount: %s)", 
                order_id, amount_to_pay, discount)
                
    # Razorpay expects amount in paise (smallest currency unit)
    amount_in_paise = int(amount_to_pay * 100)
    
    payload = {
        "amount": amount_in_paise,
        "currency": "INR",
        "accept_partial": False,
        "reference_id": reference_id,
        "description": f"Prepaid conversion for order {order_id} (includes ₹50 discount)",
        "customer": {
            "name": "Test Customer",  # Sandbox placeholder
            "contact": "+919999999999", 
            "email": "test@example.com"
        },
        "notify": {
            "sms": False,
            "email": False
        },
        "reminder_enable": False,
        "notes": {
            "order_id": order_id
        }
    }
    
    response = rzp_client.payment_link.create(payload)
    return response["id"], response["short_url"]


async def fetch_existing_payment_state(session: AsyncSession, order_id: str) -> Optional[PaymentLinkState]:
    """Fetch an existing PaymentLinkState by order_id."""
    result = await session.execute(
        text("SELECT * FROM payment_link_state WHERE order_id = :oid LIMIT 1"),
        {"oid": order_id},
    )
    row = result.mappings().first()
    if row is None:
        return None
    obj = PaymentLinkState()
    for col in PaymentLinkState.__table__.columns:
        setattr(obj, col.name, row.get(col.name))
    return obj


async def reconcile_or_create(session: AsyncSession, order_id: str, cart_value: float) -> tuple[str, str]:
    """Safe retry path to create a payment link.
    
    Uses insert-and-catch on PaymentLinkState's UNIQUE(order_id) constraint.
    If the link creation is actively in flight (CREATING), raises a Celery Retry 
    to backoff and re-check later.
    
    Returns:
        (link_id, short_url)
    """
    from celery.exceptions import Retry
    
    reference_id = make_reference_id(order_id)
    state_row = PaymentLinkState(
        order_id=order_id,
        reference_id=reference_id,
        state="CREATING"
    )
    
    try:
        session.add(state_row)
        await session.commit()
        await session.refresh(state_row)
        existing_row = state_row
        is_new = True
    except Exception as exc:
        await session.rollback()
        cause = exc.__cause__ if exc.__cause__ else exc
        if isinstance(cause, UniqueViolationError) or "unique" in str(exc).lower():
            logger.info("UniqueViolation on PaymentLinkState for order_id=%s. Checking existing state.", order_id)
            existing_row = await fetch_existing_payment_state(session, order_id)
            if existing_row is None:
                raise RuntimeError(f"UniqueViolation but row not found for order {order_id}")
            is_new = False
        else:
            raise

    # State machine evaluation
    state = existing_row.state
    
    if state in ("PENDING_PREPAY", "PAID"):
        # Terminal/successful intermediate states
        logger.info("Order %s is already in state %s. Returning existing link.", order_id, state)
        if not existing_row.razorpay_link_id:
            raise ValueError(f"State is {state} but no link ID present for order {order_id}")
        return existing_row.razorpay_link_id, existing_row.razorpay_link_url or ""
        
    if state == "CREATING" and not is_new:
        # A concurrent worker is currently calling Razorpay.
        # We don't want to lock; we want to back off and try again later.
        logger.info("Order %s is actively CREATING. Backing off.", order_id)
        # Raise Retry exception directly. It will be caught by the celery task or propagate if not bound.
        raise Retry(message="Concurrent creation in flight", exc=None)
        
    if state in ("CREATING", "LINK_CREATION_FAILED"):
        # If is_new=True, state is CREATING. We proceed.
        # If state is LINK_CREATION_FAILED, it's a retry of a failed creation.
        # We don't hold a lock during the HTTP call.
        
        # We can check Razorpay if a link was actually created but we timed out before saving it.
        if not is_new:
            try:
                query_params = {"reference_id": reference_id}
                existing_links = rzp_client.payment_link.all(query_params)
                
                if existing_links and existing_links.get("items"):
                    link = existing_links["items"][0]
                    link_id = link["id"]
                    link_url = link["short_url"]
                    logger.info("Reconciled existing Razorpay link %s for order %s", link_id, order_id)
                    
                    await session.execute(
                        text("UPDATE payment_link_state SET state = 'PENDING_PREPAY', razorpay_link_id = :lid, razorpay_link_url = :url WHERE order_id = :oid"),
                        {"lid": link_id, "url": link_url, "oid": order_id}
                    )
                    await session.commit()
                    return link_id, link_url
            except Exception as e:
                logger.warning("Error fetching from Razorpay during reconciliation for %s: %s", order_id, e)
                pass
                
        # Actually create the link (no DB transaction held open here)
        try:
            link_id, link_url = create_payment_link(order_id, cart_value, reference_id)
        except Exception:
            # Mark the row so the next retry knows the Razorpay call failed
            # (not that a concurrent worker is still in-flight).  Without this,
            # a timeout leaves the row in CREATING forever and every subsequent
            # attempt raises Retry rather than entering the reconcile path.
            await session.execute(
                text(
                    "UPDATE payment_link_state SET state = 'LINK_CREATION_FAILED'"
                    " WHERE order_id = :oid"
                ),
                {"oid": order_id},
            )
            await session.commit()
            raise
            
        # Update state on success
        await session.execute(
            text("UPDATE payment_link_state SET state = 'PENDING_PREPAY', razorpay_link_id = :lid, razorpay_link_url = :url WHERE order_id = :oid"),
            {"lid": link_id, "url": link_url, "oid": order_id}
        )
        await session.commit()
        return link_id, link_url

    raise ValueError(f"Unknown state {state} for order {order_id}")
