# Checkpoint 01 — Post-Build Fixes

## Status

- Phase status: `COMPLETE`
- Checkpoint impact: `Checkpoint 1` (pre-Checkpoint 2 remediation)
- Date/session: 2026-08-28
- Agent/session identifier: Antigravity / conversation 1791900f
- Triggered by: `audit/checkpoint-1-days-01-05.md` + `audit/day-09-revalidation.md`

---

## 1. Context

After Checkpoint 1 build completed (85/85 tests passing), a formal audit was
performed against `audit/checkpoint-1-days-01-05.md` and then revalidated
against the live Docker stack in `audit/day-09-revalidation.md`.

The revalidation surfaced **two operational bugs** (A-DAY09-001 and A-DAY09-002)
that are not caught by the existing unit/integration test suite because they
manifest only at live Celery worker runtime, not in mocked test paths.

One false finding (A-DAY09-003 — cost engine) was confirmed invalid and left
untouched per the revalidation verdict.

---

## 2. Bugs Fixed

### BUG-1 · A-DAY09-001 — Celery task registration incomplete

**File:** `app/core/celery_app.py`

**Root cause:**
`app.services.payment_tasks` was never added to the `include` list, and
`app.services.llm_explain` was commented out. The live Celery worker only
registered `score_order_task`. Any call to `create_payment_link_task.delay()`
or `explain_order_task.delay()` from inside `score_order_task` would raise
`Received unregistered task of type 'app.services.payment_tasks.create_payment_link_task'`
and the task would be silently dropped.

**Evidence from revalidation:**
> "celery inspect registered shows only app.services.scoring.score_order_task;
> recent risk_celery logs show Received unregistered task for
> app.services.llm_explain.explain_order_task"

**Fix:**
```diff
 include=[
-    "app.services.scoring",   # Day 6 — score_order_task
-    # "app.services.llm_explain",  # Day 8 — async LLM task
+    "app.services.scoring",        # Day 6 — score_order_task
+    "app.services.payment_tasks",  # Day 7 — create_payment_link_task
+    "app.services.llm_explain",    # Day 8 — explain_order_task
 ],
```

**Severity:** Blocking — payment link creation and LLM explanation tasks were
unreachable by the live worker.

---

### BUG-2 · A-DAY09-002 — Redis-down fallback leaves audit_log permanently incomplete

**File:** `app/api/routes.py`

**Root cause:**
When Redis was unavailable during a POST to `/v1/orders/score`, the route
inserted a placeholder `audit_log` row with `score=NULL`, `tier=NULL`,
`action=NULL` to establish the Postgres UNIQUE guard before dispatching the
Celery task.

However, `audit_log` has a **DB-level append-only trigger** (`tg_audit_log_append_only`)
that raises an exception on any `UPDATE` or `DELETE`. When the Celery scorer
ran with the complete scored values, it called `_insert_audit_log_sync()` which
caught the `UniqueViolation` (placeholder row existed), logged "duplicate —
skipping", and returned the placeholder unchanged.

Result: the row was permanently stuck with `NULL` score, tier, and action.
No completed result was ever written. The GET endpoint would serve a null record
indefinitely.

**Evidence from revalidation:**
> "app/api/routes.py inserts placeholder row through insert_audit_log() when
> Redis is down; app/services/scoring.py later calls _insert_audit_log_sync()
> and returns existing duplicate row without updating it"

**Fix:**
Removed the placeholder INSERT entirely from the Redis-unavailable path.
The route now skips directly to Celery task enqueue. The task's own
`_insert_audit_log_sync()` performs the single correct INSERT with all fields
populated (score, tier, action, shap_values_json). If two tasks race (two
duplicate requests both past Redis), the second catches `UniqueViolation`
and returns the already-complete row — correct and idempotent.

```diff
-    # ── Redis-unavailable path — establish Postgres guard first ────────────
-    if not redis_available:
-        try:
-            _, is_new = await insert_audit_log(db, event_id=event_id, order_id=order_id)
-        except Exception as exc:
-            raise HTTPException(status_code=503, ...)
-        if not is_new:
-            existing = await lookup_existing_audit_log(db, event_id)
-            return JSONResponse(status_code=200, ...)
+    # ── Redis-unavailable path — enqueue task directly ─────────────────────
+    #
+    # BUG FIX (A-DAY09-002): Placeholder INSERT omitted — audit_log has a
+    # DB-level append-only trigger that forbids UPDATE. The Celery scorer
+    # now owns the single correct INSERT with full scored data.
```

**Severity:** High — any Redis outage window would silently produce permanently
incomplete audit records with null risk scores, tiers, and actions.

---

## 3. Test Suite Corrections

Two tests validated the old (broken) behavior and required updating.
One additional test in `test_llm_fallback.py` required redesign to use the
correct duplicate-detection path.

| Test | File | Change |
|---|---|---|
| `test_redis_unavailable_postgres_catches_duplicate` | `test_idempotency.py` | Both calls now correctly return 202 (task enqueue); task-level insert-and-catch is the dedup guard |
| `test_postgres_unavailable_returns_503` | `test_idempotency.py` | 503 now triggered by broker failure (`.delay()` raises); assertion string corrected from `"unavailable"` → `"enqueue"` |
| `test_duplicate_post_statuses` | `test_llm_fallback.py` | Redesigned: switched from Redis-unavailable path (which now always returns 202) to Redis-duplicate fast-path (SET NX → None); pre-inserts complete row, mocks Redis as "key already exists", asserts 200 + explanation field passthrough |

---

## 4. False Finding — NOT Fixed (Correctly)

**A-DAY09-003:** The pasted Day 09 audit claimed `cost_tp_h_abandoned()` should
return `3 * 15 = 45`. Confirmed **mathematically incorrect** by the revalidation.

`docs/track02_spec_reference.md` specifies the abandoned/cancelled high-risk
branch carries zero freight-loss cost. `app/ml/costs.py` returns `0` for this
branch, which is correct per spec. No change made.

---

## 5. Final Test Result

```
========================= 85 passed, 17 warnings in 62.35s =========================
```

All 85 tests pass. Zero regressions introduced.

---

## 6. Files Changed

| File | Change Type | Description |
|---|---|---|
| `app/core/celery_app.py` | BUG FIX | Added `app.services.payment_tasks` and `app.services.llm_explain` to `include` list |
| `app/api/routes.py` | BUG FIX | Removed incomplete placeholder INSERT from Redis-unavailable fallback path |
| `tests/test_idempotency.py` | TEST UPDATE | Updated tests 3 and 4 to reflect corrected Redis-down behavior |
| `tests/test_llm_fallback.py` | TEST UPDATE | Redesigned `test_duplicate_post_statuses` to use Redis-duplicate fast-path |

---

## 7. Audit Source References

- `audit/checkpoint-1-days-01-05.md` — Checkpoint 1 audit, CONDITIONAL GO verdict
- `audit/day-09-revalidation.md` — Revalidation of Day 09 findings against live stack
- `Implementation_plan.md` — Day 6 idempotency design (insert-and-catch pattern)
- `docs/track02_spec_reference.md` — Cost formula authority (A-DAY09-003 false finding)
