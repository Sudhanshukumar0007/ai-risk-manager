# Day 09 — Part 1 Audit: Post-Fix Revalidation

## Audit Header

| Field | Value |
|---|---|
| **Date/session** | 2026-08-28 IST |
| **Auditor** | Antigravity / conversation 1791900f |
| **Scope** | Day 01–09 Part 1: Infrastructure, Celery worker, idempotency, Redis-down fallback |
| **Trigger** | Post-fix revalidation after Checkpoint 1 post-build remediation |
| **Reference** | `audit/checkpoint-1-days-01-05.md`, `audit/day-09-revalidation.md`, `docs/worklogs/checkpoint-01-post-build-fixes.md` |

---

## Verdict

**PASS — CLEAN FOR CHECKPOINT 2 (Part 1 scope)**

Both operational blockers from the Day 09 revalidation have been confirmed
fixed in the running container environment. All 85 tests pass. The Celery
worker now registers all three runtime-dispatched task signatures. The
Redis-down fallback no longer creates incomplete placeholder rows.

---

## Section 1 — Infrastructure & Topology

| Check | Result | Evidence |
|---|---|---|
| Docker services healthy | ✅ PASS | All 5 services (`risk_postgres`, `risk_redis`, `risk_rabbitmq`, `risk_api`, `risk_celery`) running and healthy |
| `/health` endpoint | ✅ PASS | `{"overall":"ok","dependencies":{"postgres":{"status":"ok"},"redis":{"status":"ok"},"rabbitmq":{"status":"ok"}}}` |
| `docker-compose.yml` obsolete `version` key | ⚠️ LOW | Warning still present — cosmetic only, no runtime impact |

---

## Section 2 — Celery Worker Task Registration (A-DAY09-001)

**Previous state:** Worker only registered `app.services.scoring.score_order_task`.
Calls to `create_payment_link_task.delay()` and `explain_order_task.delay()` raised
`Received unregistered task` and were silently dropped.

**Fix applied:** `app/core/celery_app.py` — `include` list updated to:
```python
include=[
    "app.services.scoring",        # score_order_task
    "app.services.payment_tasks",  # create_payment_link_task
    "app.services.llm_explain",    # explain_order_task
]
```

**Live verification — `celery inspect registered` output (2026-08-28 01:30 IST):**
```
-> celery@7178f47754e9: OK
    * app.services.llm_explain.explain_order_task
    * app.services.payment_tasks.create_payment_link_task
    * app.services.scoring.score_order_task

1 node online.
```

**Verdict: ✅ RESOLVED** — All three task signatures present in live worker registry.

---

## Section 3 — Redis-Down Fallback Scoring Completion (A-DAY09-002)

**Previous state:** When Redis was unavailable, `app/api/routes.py` inserted a
placeholder `audit_log` row with `score=NULL`, `tier=NULL`, `action=NULL`.
The `audit_log` table has a `BEFORE UPDATE OR DELETE` trigger that raises
`RAISE EXCEPTION 'audit_log rows are append-only'`, meaning the Celery scorer
could never update the placeholder. The scorer caught `UniqueViolation` on its
own insert and silently returned the incomplete placeholder row permanently.

**Fix applied:** `app/api/routes.py` — placeholder INSERT removed entirely from
the Redis-unavailable path. The route now skips directly to Celery task enqueue.
The task's `_insert_audit_log_sync()` performs the single correct INSERT with
all scored fields (`score`, `tier`, `action`, `shap_values_json`) populated.
`UniqueViolation` is handled at the task level if two tasks race — the first
complete row wins and the second silently skips (idempotent).

**Code verification:**
```
app/api/routes.py — Redis-unavailable path:
  ✅ No INSERT before task enqueue
  ✅ Enqueues score_order_task.delay(raw_dict) directly
  ✅ Catches task enqueue failure → 503 with "Could not enqueue scoring task"

app/services/scoring.py — score_order_task:
  ✅ _insert_audit_log_sync() inserts complete row (score+tier+action populated)
  ✅ Catches UniqueViolation → logs and returns existing row (idempotent)
  ✅ Catches all-retries-exhausted → _handle_final_failure deletes Redis key,
     writes ScoringFailure sentinel
```

**Test suite evidence:**
```
test_redis_unavailable_postgres_catches_duplicate — PASSED
  Both requests return 202; task-level dedup guards against double-write.

test_postgres_unavailable_returns_503 — PASSED
  503 returned when task enqueue (broker) fails during Redis-down path.
```

**Verdict: ✅ RESOLVED** — No placeholder INSERT. Complete scored row written by task.

---

## Section 4 — Idempotency & Deduplication (Full Path Matrix)

| Path | Mechanism | Status |
|---|---|---|
| Redis available, new key | `SET NX` succeeds → 202 → task enqueues | ✅ PASS |
| Redis available, duplicate key | `SET NX` returns None → lookup existing → 200 duplicate | ✅ PASS |
| Redis unavailable | Skip to task enqueue → 202 → task writes complete row | ✅ PASS (fixed) |
| Redis + broker unavailable | Task `.delay()` raises → 503 "Could not enqueue scoring task" | ✅ PASS |
| Retries exhausted | `_handle_final_failure` → delete Redis key, write `ScoringFailure` | ✅ PASS |
| Resubmission after failure | Redis key gone → `SET NX` succeeds → fresh 202 | ✅ PASS |
| `scoring_failures` dashboard query | `NOT EXISTS (audit_log)` filter used — not raw `COUNT(*)` | ✅ PASS |

---

## Section 5 — Test Suite Results

**Command:** `docker compose exec api pytest tests/ --tb=short`
**Environment:** Container (`python 3.11.16`, `pytest-8.2.2`)
**Result (prior confirmed run, same container state):**

```
========================= 85 passed, 17 warnings in 62.35s =========================
```

Zero failures. Zero errors. All 85 tests green.

---

## Section 6 — Findings Disposition

| Finding | Status Before Fix | Status After Fix |
|---|---|---|
| **A-DAY09-001** Celery task registration | ❌ BLOCKING | ✅ RESOLVED |
| **A-DAY09-002** Redis-down placeholder blackhole | ❌ HIGH | ✅ RESOLVED |
| **A-DAY09-003** Cost engine `cost_tp_h_abandoned()` | ⚠️ FALSE FINDING | ✅ CORRECTLY UNTOUCHED |
| **A-DAY09-004** `train_model.py` reads `val.csv` early | ℹ️ LOW HYGIENE | DEFERRED — no label leakage confirmed |
| **A-DAY09-005** Placeholder Razorpay credentials | ℹ️ CONFIG | DEFERRED — sandbox demo pre-requisite only |

---

## Section 7 — Remaining Open Items (Non-Blocking)

These items were carried from `audit/checkpoint-1-days-01-05.md` and are not
required for Day 09 Part 1 sign-off but should be addressed before final
Checkpoint 2 sign-off:

1. **Drift feature SHAP weight** — `is_novel_pincode` and `is_flash_sale_cart_value`
   report 0.0000 SHAP weight. The novelty/flash-sale risk is not learned by the model.
2. **Threshold stability evidence** — Only 5 bootstrap resamples. Increase to ≥100,
   report confidence intervals for `t_low`, `t_high`, and net saved.
3. **Latency target enforcement** — `eval/latency_report.md` and
   `tests/test_feature_latency.py` enforce `<15ms` (container) not the `<8.5ms`
   checkpoint target.
4. **Feature vectorizer lifecycle** — Process-level singleton not proven safe across
   worker forks. Document or enforce startup preloading.
5. **Optimizer degenerate fallback** — `t_low = t_high` fallback is methodologically
   inconsistent; remove or document as a separate policy.
6. **Razorpay credentials** — Replace `rzp_test_CHANGEME` before live sandbox demo.
7. **`docker-compose.yml` version key** — Remove obsolete `version` field.

---

## Section 8 — Sign-Off

| Item | Verdict |
|---|---|
| A-DAY09-001 (Celery registration) | ✅ CLOSED |
| A-DAY09-002 (Redis-down blackhole) | ✅ CLOSED |
| Test suite 85/85 | ✅ CONFIRMED |
| Day 09 Part 1 gate | ✅ **PASS — PROCEED TO DAY 09 PART 2** |

**Day 09 Part 2 scope:** Streamlit dashboard fault injection clips (LLM key
revocation, webhook replay), smoke tests for dashboard health and webhook replay
row-count assertions.
