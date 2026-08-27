# Day 09 Audit — End-to-End System Integration, Resiliency & Audit Trail

Date/session: 2026-08-27  
Auditor: Codex (GPT-5)  
Scope: End-to-end system audit across all 8 architectural domains (Infrastructure, Data Engine, Model/Feature Pipeline, Cost/Threshold Search, Scoring API & Idempotency, Decision Router, Celery Background Worker, and Razorpay Webhooks) as recorded in audit rollout session `rollout-2026-08-27T19-59-16-01a043a0-088f-7033-a5f9-23bdfbf93421.jsonl`.

---

## Audit Verdict

**Verdict: PARTIAL PASS / NOT CLEAN FOR CHECKPOINT 2**

The system successfully demonstrates robust core API design, model inference, total-outage fail-closed behavior (`503 Service Unavailable`), exact score routing, and concurrent Redis idempotency deduplication. However, Checkpoint 2 cannot be cleanly cleared due to two critical operational blockers:

1. **Celery Worker Task Unregistration**: Background Celery workers reject `app.services.payment_tasks` and `app.services.llm_explain` as unregistered tasks, preventing mid-risk Razorpay payment link generation and async LLM explanations from executing.
2. **Postgres Fallback Scoring Failure**: When Redis is down, the API successfully inserts placeholder rows into `audit_log` and returns `202 Accepted`, but background tasks fail to complete scoring and persist results back to Postgres, leaving orders in a `score: null` state indefinitely.

---

## Governing Workflow Check

| Workflow Requirement | Status | Evidence |
|---|---|---|
| Read governing instructions | PASS | Governing instructions and rollout specifications verified. |
| Read implementation plan | PASS | Reviewed Checkpoint 2 requirements and Day 06-09 specs. |
| Verify Docker topology | PASS | 5 core containers (`risk_api`, `risk_postgres`, `risk_redis`, `risk_rabbitmq`, `risk_dashboard`) healthy; `risk_celery` active but with task registration errors. |
| Held-out Isolation Check | PASS | Clean-state data generation validated; held-out dataset preserved for final evaluation. |
| Outage & Failover Validation | PARTIAL | Total outage (Redis + Postgres down) correctly returns `503`. Single-node Redis outage fails background completion to Postgres. |
| Idempotency & Deduplication | PASS (REDIS UP) | Redis-up duplicate requests, replay attacks, and cold-store race checks created exactly 1 `audit_log` row. |

---

## Component Audit Matrix

| Section / Component | Status | Key Findings & Evidence |
|---|---|---|
| **Section 1: Infrastructure & Topology** | PASS WITH CAVEAT | All 5 Docker services start and become healthy. `risk_celery` runs but fails task execution. |
| **Section 2: Synthetic Data Engine** | PASS | Generated datasets pass schema, ID non-overlap, and 10% held-out covariate shift checks. |
| **Section 3: Feature Pipeline & Latency** | PASS | Feature extraction p99 latency is under 10 ms (2.84 ms recorded). Zero post-inference score mutation detected. |
| **Section 4: Model, Cost & Thresholds** | PASS WITH CAVEAT | Model PR-AUC / calibration bounds pass. `t_low=0.50`, `t_high=0.75`. Cost engine `cost_tp_h_abandoned()` returns 0 instead of friction cost (45). |
| **Section 5: Idempotency & Resiliency** | PARTIAL | Redis-up deduplication succeeds. Redis-down Postgres fallback scoring fails to persist final scores (`score: null`). Total outage properly returns `503`. |
| **Section 6: Decision Router & Tiers** | PASS | `route(score, 0.5, 0.75)` correctly assigns `ALLOW_COD`, `SOFT_GATE_COD`, and `NUDGE_PREPAY`. |
| **Section 7: Celery Background Processing** | FAIL (BLOCKER) | Celery worker emits `KeyError` / `NotRegistered` for `app.services.payment_tasks` and `app.services.llm_explain`. |
| **Section 8: Razorpay Integration & Webhooks** | PARTIAL | Webhook signature validation & event deduplication logic are sound; live sandbox payment link creation blocked by placeholder credentials in `.env` and Celery task unregistration. |

---

## Validation Evidence

### 1. Service Topology & Health Check
```text
POST /v1/orders/score -> HTTP 200 / 202
GET /health -> HTTP 200 {"status": "ok", "dependencies": {"postgres": "ok", "redis": "ok", "rabbitmq": "ok"}}
```

### 2. Idempotency & Replay Protection (Redis Active)
```text
Concurrent duplicate requests with identical event_id ('audit-s5-concurrent-20260827'):
- First Request: HTTP 200 {"status": "COMPLETE", "score": 0.421, "action": "ALLOW_COD"}
- Duplicate Request: HTTP 200 (Returned cached payload from Redis)
- DB Verification: SELECT COUNT(*) FROM audit_log WHERE event_id = 'audit-s5-concurrent-20260827' -> 1 row
```

### 3. Graceful Fallback & Total Outage Behavior
```text
[Redis Down Test]
- docker stop risk_redis
- POST /v1/orders/score -> HTTP 202 {"status": "PROCESSING", "event_id": "audit-s5-redis-down-001"}
- GET /v1/orders/result/audit-s5-redis-down-001 -> score: null (FAILED: Async task did not update Postgres)

[Total Outage Test (Redis Down + Postgres Down)]
- docker stop risk_postgres risk_redis
- POST /v1/orders/score -> HTTP 503 {"detail": "Service Unavailable - Database connection failed"} (PASS)
```

### 4. Celery Worker Execution Logs
```text
[2026-08-27 14:51:19,673: ERROR/MainProcess] Received unregistered task 'app.services.llm_explain.explain_order_task'.
KeyError: 'app.services.llm_explain.explain_order_task'
[2026-08-27 14:51:25,102: ERROR/MainProcess] Received unregistered task 'app.services.payment_tasks.create_payment_link_task'.
KeyError: 'app.services.payment_tasks.create_payment_link_task'
```

---

## Audit Findings

### A-DAY09-001: Celery Worker Task Registration Failure (Blocking)

- **Severity**: Blocking
- **Evidence**:
  - `docker logs risk_celery` reveals `KeyError` when attempting to dispatch `create_payment_link_task` and `explain_order_task`.
  - `app/core/celery_app.py` includes imports, but the worker process does not load the task modules under their registered task signatures on startup.
- **Impact**:
  - `NUDGE_PREPAY` tier orders fail to generate Razorpay payment links in the background.
  - Asynchronous LLM explanations are never generated or saved to `llm_explanations`.
- **Remediation**:
  - Explicitly import `app.services.payment_tasks` and `app.services.llm_explain` inside `app/core/celery_app.py` and set `autodiscover_tasks(['app.services'])` or add them to Celery `imports` config.

---

### A-DAY09-002: Postgres Fallback Scoring Fails to Complete During Redis Outage (High)

- **Severity**: High
- **Evidence**:
  - When Redis is stopped (`docker stop risk_redis`), the API returns HTTP 202 and creates a placeholder row in `audit_log`.
  - However, background scoring fails to write back the computed `score`, `risk_tier`, and `action` to Postgres.
  - Queries to `GET /v1/orders/result/{event_id}` return `score: null` permanently.
- **Impact**:
  - Breaches the Day 6 requirement for fallback scoring when Redis is offline.
- **Remediation**:
  - Update `app/services/scoring.py` / `app/api/routes.py` so that when Redis is unavailable, synchronous inline execution or a direct database background task finishes the scoring pipeline and commits the result directly to `audit_log`.

---

### A-DAY09-003: Cost Engine Abandoned High-Risk Path Formula Discrepancy (Medium)

- **Severity**: Medium
- **Evidence**:
  - `app/ml/costs.py:cost_tp_h_abandoned()` returns `0`.
  - Audit specification requires friction/verification cost ($3 \times 15 = 45$) without freight/RTO cost.
- **Impact**:
  - Causes slight misalignment in 2D threshold optimization cost surface calculations.
- **Remediation**:
  - Adjust `cost_tp_h_abandoned()` in `app/ml/costs.py` to evaluate `3 * 15` (or the configured friction parameters).

---

### A-DAY09-004: Training Script Reads Validation File on Initialization (Low)

- **Severity**: Low / Data Hygiene
- **Evidence**:
  - `scripts/train_model.py` reads `data/val.csv` at startup before model fitting to pre-configure metric logging structures.
- **Impact**:
  - Minor data hygiene issue; does not leak target labels into model parameters (tuning uses `train.csv` fit fold only).
- **Remediation**:
  - Defer loading `val.csv` until after model fitting and calibration are completed.

---

### A-DAY09-005: Placeholder Razorpay Credentials in Environment (Configuration)

- **Severity**: Low / Configuration
- **Evidence**:
  - `.env` contains `RAZORPAY_KEY_ID=rzp_test_CHANGEME` and `RAZORPAY_KEY_SECRET=CHANGEME`.
- **Impact**:
  - Live Razorpay Sandbox API calls fail authentication; tests must use mock/stub handlers.
- **Remediation**:
  - Provide valid Razorpay Sandbox test credentials in `.env` before final production demo.

---

## Next Steps for Remediation

1. Update `app/core/celery_app.py` to properly import and register `app.services.payment_tasks` and `app.services.llm_explain`.
2. Fix the Postgres fallback path in `app/api/routes.py` so that scoring requests complete and persist when Redis is down.
3. Update `app/ml/costs.py` to correctly calculate friction costs for abandoned high-risk orders.
