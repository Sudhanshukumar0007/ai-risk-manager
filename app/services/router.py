"""Deterministic routing layer for AI Risk Manager.

Translates the calibrated P(RTO) score from the ML engine into a deterministic
business action using the frozen 2D threshold grid (t_low, t_high).

This isolates ML intelligence from financial execution rules.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def route(score: float, t_low: float, t_high: float) -> tuple[str, str]:
    """Route an order based on its P(RTO) score and boundary thresholds.
    
    Args:
        score: Calibrated P(RTO) output from XGBoost model.
        t_low: Lower bound cutoff separating ALLOW_COD from NUDGE_PREPAY.
        t_high: Upper bound cutoff separating NUDGE_PREPAY from SOFT_GATE_COD.
        
    Returns:
        (tier, action): 
          - tier: "ALLOW_COD", "NUDGE_PREPAY", or "SOFT_GATE_COD"
          - action: A short string describing the action taken.
    """
    if score < t_low:
        tier = "ALLOW_COD"
        action = "Standard COD fulfillment"
    elif score < t_high:
        tier = "NUDGE_PREPAY"
        action = "Razorpay prepaid link with ₹50 discount context"
    else:
        tier = "SOFT_GATE_COD"
        action = "Shopify tag Flagged_RTO_High & IVR logging"

    logger.info(
        "Router evaluation: score=%.4f (t_low=%.4f, t_high=%.4f) -> tier=%s",
        score,
        t_low,
        t_high,
        tier,
    )
    return tier, action
