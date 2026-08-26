"""Soft gate handler for Tier 3 (SOFT_GATE_COD) orders.

Applies verification flags (Shopify tag stub) and logs IVR payload triggers.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def apply_soft_gate(order_id: str) -> None:
    """Apply the soft gate for high-risk COD orders.
    
    This function runs synchronously and inline within the Celery worker.
    It stubs the Shopify tag assignment and IVR trigger.
    """
    logger.info("Applying SOFT_GATE_COD for order %s", order_id)
    
    # 1. Stub: Shopify tag assignment
    tag_name = "Flagged_RTO_High"
    logger.info("Stub: Assigned Shopify tag '%s' to order %s", tag_name, order_id)
    
    # 2. Stub: IVR verification payload trigger
    ivr_payload = {
        "order_id": order_id,
        "action": "trigger_ivr_verification",
        "reason": "High P(RTO) score"
    }
    logger.info("Stub: Logged IVR payload trigger: %s", ivr_payload)
