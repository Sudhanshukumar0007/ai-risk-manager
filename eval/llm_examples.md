# LLM Explanation API Examples (OpenRouter substitution)

This document shows the actual API response shapes from `GET /v1/orders/{event_id}/result` when the LLM explanation task succeeds or falls back.

## 1. Happy Path (OpenRouter Success)

When the Celery task successfully calls the OpenRouter API (Llama 3.1 8B Instruct), the `explanation_status` is `complete` and the `explanation` field contains the LLM output.

```json
{
  "status": "complete",
  "event_id": "test-event-llm-1",
  "order_id": "test-order-llm-1",
  "score": 0.8543,
  "tier": "NUDGE_PREPAY",
  "action": "Offer pre-paid discount via WhatsApp",
  "shap_top3": [
    {"feature": "pincode_risk_score", "impact": 0.45},
    {"feature": "account_age_days", "impact": 0.32},
    {"feature": "phone_order_velocity_7d", "impact": 0.15}
  ],
  "task_id": "1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed",
  "created_at": "2026-08-25T14:30:00.000Z",
  "explanation": "This order is flagged for high pincode risk and recent high velocity on a relatively new account.",
  "explanation_status": "complete"
}
```

## 2. Fallback Path (Timeout / API Failure)

If the OpenRouter API times out (strict 2.5s limit) or returns an error, the task writes a deterministic fallback row to ensure the state machine completes. The `explanation_status` is `fallback`.

```json
{
  "status": "complete",
  "event_id": "test-event-llm-2",
  "order_id": "test-order-llm-2",
  "score": 0.9123,
  "tier": "SOFT_GATE_COD",
  "action": "Require OTP for COD",
  "shap_top3": [
    {"feature": "customer_past_rto_count", "impact": 0.65},
    {"feature": "device_account_reuse_count", "impact": 0.40},
    {"feature": "cart_value", "impact": -0.10}
  ],
  "task_id": "2c9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bee",
  "created_at": "2026-08-25T14:31:00.000Z",
  "explanation": "Flagged for manual review — explanation unavailable",
  "explanation_status": "fallback"
}
```
