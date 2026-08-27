# Fault Injection Recording Guide

This document provides the exact step-by-step instructions and terminal commands required to record the fault injection video clips for the final submission. These clips serve as empirical evidence that the system gracefully handles downstream failures and enforces idempotency.

---

## Preparation

Before recording, ensure you have a clean slate so the dashboard is easy to read.

1. **Ensure containers are running:**
   ```bash
   docker compose up -d
   ```
2. **Truncate the database:** (This clears out past test data)
   ```bash
   docker compose exec db psql -U postgres -d buildathon -c "TRUNCATE TABLE audit_log, payment_link_state;"
   ```
3. **Open the Dashboard:**
   Navigate to `http://localhost:8501` in your browser.

---

## 🎥 Clip 1: LLM Key Revocation (Graceful Degradation)

**Goal:** Prove that if the LLM explanation service goes down (e.g., revoked key, rate limit), the critical monetary/scoring path is not blocked.

### Recording Steps:
1. **Start Screen Recording.** Make sure your terminal and the browser (Dashboard) are both visible.
2. **Break the LLM Key (Optional):** If you previously configured a *real* OpenRouter API key in your `.env` file, open the file and change it to an invalid value (e.g., `sk-or-broken`). Then restart the Celery worker in your terminal:
   ```bash
   docker compose restart celery_worker
   ```
   *(Note: If your `.env` file still has `OPENROUTER_API_KEY=sk-or-v1-CHANGEME`, you can skip this step! The system will already trigger the fallback automatically.)*
3. **Trigger a High-Risk Order:** Send the following `curl` command to score an order. This payload is deliberately crafted with high-risk signals (e.g., 5 past RTOs, new account) to trigger a `SOFT_GATE_COD` or `NUDGE_PREPAY` tier.
   **For PowerShell:**
   ```powershell
   Invoke-RestMethod -Uri http://localhost:8000/v1/orders/score -Method Post -Headers @{"Content-Type"="application/json"} -Body '{"event_id": "evt_demo_llm_001", "order_id": "ord_demo_999", "pincode": "110001", "category": "Electronics", "cart_value": 15000.0, "item_quantity": 3, "order_timestamp": "2026-08-28T10:00:00Z", "address_line_1": "123 Main Street", "address_line_2": "", "payment_method": "COD", "customer_past_rto_count": 5, "phone_order_velocity_7d": 10, "device_account_reuse_count": 3, "account_age_days": 1}'
   ```
   **For Bash / Mac / Linux:**
   ```bash
   curl -X POST http://localhost:8000/v1/orders/score \
   -H "Content-Type: application/json" \
   -d '{"event_id": "evt_demo_llm_001", "order_id": "ord_demo_999", "pincode": "110001", "category": "Electronics", "cart_value": 15000.0, "item_quantity": 3, "order_timestamp": "2026-08-28T10:00:00Z", "address_line_1": "123 Main Street", "address_line_2": "", "payment_method": "COD", "customer_past_rto_count": 5, "phone_order_velocity_7d": 10, "device_account_reuse_count": 3, "account_age_days": 1}'
   ```
4. **Show the Dashboard:** Point out the new row on the dashboard. Emphasize that:
   - The order was successfully processed and routed.
   - The Razorpay payment link state (if applicable) was initiated.
   - The Explanation cell says: *"Flagged for manual review — explanation unavailable"*, proving that the system degraded gracefully rather than crashing.
5. **Stop Screen Recording.** Save this file as `docs/videos/fault_injection_llm.mp4`.

---

## 🎥 Clip 2: Webhook Idempotency (Duplicate Replay)

**Goal:** Prove that if Razorpay sends the exact same webhook multiple times, the system safely ignores the duplicate using Redis and the Postgres `UNIQUE` constraint, without creating duplicate records or throwing unhandled errors.

### Recording Steps:
1. **Start Screen Recording.**
2. **Send the Initial Webhook:** Because the webhook endpoint requires a valid HMAC SHA256 signature generated from your secret key, use this Python one-liner. It automatically signs and sends the webhook. (Copy and paste this entire block as one single line):

   **For PowerShell / Windows:**
   ```powershell
   docker compose exec api python -c "import os, json, hmac, hashlib, httpx; secret = os.getenv('RAZORPAY_WEBHOOK_SECRET', 'whsec_CHANGEME').encode(); payload = json.dumps({'entity': 'event', 'event': 'payment_link.paid', 'payload': {'payment_link': {'entity': {'id': 'plink_test123', 'reference_id': 'ord_demo_999', 'status': 'paid'}}}}, separators=(',', ':')); sig = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest(); headers = {'x-razorpay-signature': sig, 'x-razorpay-event-id': 'evt_webhook_demo_001', 'Content-Type': 'application/json'}; r = httpx.post('http://localhost:8000/v1/webhooks/razorpay', content=payload, headers=headers); print(f'Status: {r.status_code}, Response: {r.text}')"
   ```
3. **Show the Dashboard/Terminal:** Point out that the terminal outputs `Status: 200` and the webhook event appears on the dashboard (or the backend logs show processing).
4. **Send the Duplicate Webhook:** Press `Up` in your terminal to recall the exact same Python one-liner and press `Enter` to run it a second time.
5. **Show the Dashboard/Terminal:** 
   - Point out that the terminal *still* outputs `Status: 200` (meaning it handled the duplicate safely without crashing).
   - Point out that the database row count on the dashboard *did not increase*.
6. **Stop Screen Recording.** Save this file as `docs/videos/fault_injection_idempotency.mp4`.
