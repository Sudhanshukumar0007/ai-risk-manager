"""Payment-related Celery tasks.

Handles Razorpay link creation via the safe reconcile_or_create pathway,
with dedicated retry backoff (5s, 15s, 45s, 135s).
"""

from __future__ import annotations

import logging
import asyncio

from celery import shared_task
from sqlalchemy import text
from app.db.session import AsyncSessionLocal
from app.services.razorpay_client import reconcile_or_create

logger = logging.getLogger(__name__)


def _handle_final_link_failure(order_id: str) -> None:
    """Transition PaymentLinkState to LINK_CREATION_FAILED after retries exhaust.
    
    This ensures the record isn't permanently stuck in PENDING_CREATE,
    preventing legitimate future resubmissions from succeeding.
    """
    logger.error("All Razorpay retries exhausted for order %s. Setting LINK_CREATION_FAILED.", order_id)
    
    async def update_state():
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("UPDATE payment_link_state SET state = 'LINK_CREATION_FAILED' WHERE order_id = :oid"),
                {"oid": order_id}
            )
            await session.commit()
            
    try:
        # Run the async DB update in the synchronous Celery worker thread
        loop = asyncio.get_event_loop()
        loop.run_until_complete(update_state())
    except Exception as e:
        logger.error("Critical: Failed to set LINK_CREATION_FAILED for order %s: %s", order_id, e)


@shared_task(bind=True, max_retries=4)
def create_payment_link_task(self, order_id: str, cart_value: float) -> None:
    """Celery task to safely create a Razorpay link."""
    logger.info("Executing create_payment_link_task for order %s", order_id)
    
    async def execute():
        async with AsyncSessionLocal() as session:
            await reconcile_or_create(session, order_id, cart_value)
            
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(execute())
    except Exception as exc:
        logger.warning("Razorpay call failed for order %s: %s", order_id, exc)
        try:
            # Backoff: 5s, 15s, 45s, 135s
            countdown = 5 * (3 ** self.request.retries)
            self.retry(exc=exc, countdown=countdown)
        except self.MaxRetriesExceededError:
            _handle_final_link_failure(order_id)
            raise
