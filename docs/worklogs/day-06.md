# Day 06 — FastAPI Ingestion, Redis Dedup, Postgres Audit (Race-Fixed)

## Status

- Phase status: `COMPLETE`
- Checkpoint impact: `none` (Checkpoint 1 already passed at Day 5)
- Date/session: 2026-08-26
- Agent/session identifier: Antigravity

## 1. Plan Tasks

| Plan Step | Requirement | Status |
|---|---|---|
| 1 | `audit_log` table with DB-level `UNIQUE(event_id)` | DONE |
| 2 | `POST /v1/orders/score` | DONE |
| 3 | Redis atomic `SET NX` dedup before task enqueue | DONE |
| 4 | Insert-and-catch (not SELECT→INSERT) idempotency | DONE |
| 5 | Idempotent-replay integration test (duplicate = 1 row) | DONE |

**User-directed additions (approved before implementation):**

| Addition | Status |
|---|---|
| Celery-first architecture (POST returns 202; task does pipeline/score/SHAP/insert) | DONE |
| Duplicate lookup via Postgres `event_id` query (not Redis cached response) | DONE |
| Real concurrency test using `asyncio.gather` (not sequential) | DONE |
| Append-only trigger on `audit_log` in same migration (not Day 10 retrofit) | DONE |
| `PaymentLinkState` stub table (Day 7 schema, no migration risk later) | DONE |

## 2. Repository State Before Work

### Relevant files
- `config/thresholds.json` — frozen `t_low=0.5, t_high=0.75`
- `app/ml/costs.py`, `app/ml/shap_engine.py` — complete from Day 4/5
- `app/features/pipeline.py` — complete from Day 3
- `models/xgboost_rto_v1.base.bin` — trained, calibrated model

### Existing implementation
- `app/api/` — empty (only `__init__.py`)
- `app/db/` — empty (only `__init__.py`)
- `app/core/idempotency.py` — did not exist
- `scripts/test_idempotency.sh` — did not exist

### Existing tests
- No Day 6 tests.

### Known failures
- None from Day 5.

## 3. Pre-Implementation Assessment

### What was already correct
- All Day 5 deliverables complete; Checkpoint 1 milestones M01–M08 green.
- Docker stack running cleanly (5 services healthy).
- Frozen thresholds in `config/thresholds.json`.

### What was missing
- The entire Day 6 API + idempotency + DB layer.

### Risks identified
- **R1:** Building `POST /v1/orders/score` synchronous and retrofitting Celery in Day 7/8 would require rewriting idempotency wiring twice.
- **R2:** SELECT→INSERT race: not implemented (correctly avoided — insert-and-catch used).
- **R3:** Append-only trigger deferred to Day 10 would add migration risk at the worst time.

### Recommended implementation order
Per user direction: Celery-first from the start; append-only trigger in the same migration; real concurrency test.

## 4. Implementation Performed

### Changes

**Celery-first architecture:**
- `POST /v1/orders/score` → Redis `SET NX` → `score_order_task.delay(payload)` → `202 Accepted`
- Duplicate (Redis) → Postgres lookup by `event_id` → `200 OK` with existing row
- Redis unavailable → Postgres `INSERT` placeholder first (guard) → task dispatched
- Postgres unavailable → `503` (never process without durable dedup)

**Append-only trigger:**
- `audit_log_append_only()` Postgres function + `tg_audit_log_append_only` trigger installed at app startup via `create_all_tables()`. Idempotent DDL (DO $$ block checks `pg_proc`/`pg_trigger`).

### Files created
- `app/db/models.py` — `AuditLog` (UNIQUE event_id, JSONB fields, task_id column) + `PaymentLinkState` stub
- `app/db/session.py` — async engine, `AsyncSessionLocal`, `get_db()` dependency, `create_all_tables()` with append-only trigger DDL
- `app/core/idempotency.py` — `redis_set_nx()`, `lookup_existing_audit_log()`, `insert_audit_log()` (insert-and-catch)
- `app/services/scoring.py` — `score_order_task` Celery task (feature pipeline → XGBoost → SHAP → router → Postgres insert-and-catch)
- `app/api/routes.py` — `POST /v1/orders/score`, `GET /v1/orders/{event_id}/result`
- `tests/test_idempotency.py` — 5 pytest tests including `asyncio.gather` concurrency test
- `scripts/test_idempotency.sh` — shell integration test (7 assertions, uses python3/psycopg2 for DB queries)

### Files modified
- `app/main.py` — lifespan now calls `create_all_tables()`, initialises shared Redis pool on `app.state`, includes scoring router
- `app/core/celery_app.py` — added `app.services.scoring` to `include` list

### Files deleted
- None

### Configuration/service changes
- No new env vars required (all already in `.env`).
- No Docker changes.

## 5. Validation

### Commands run
```text
docker compose restart api celery_worker
docker compose exec api pytest tests/test_idempotency.py -v
docker compose exec api bash scripts/test_idempotency.sh
```

### Test results
```
tests/test_idempotency.py::test_sequential_duplicate_single_row          PASSED
tests/test_idempotency.py::test_concurrent_duplicate_single_row          PASSED
tests/test_idempotency.py::test_redis_unavailable_postgres_catches_duplicate PASSED
tests/test_idempotency.py::test_postgres_unavailable_returns_503         PASSED
tests/test_idempotency.py::test_invalid_payload_returns_422              PASSED
5 passed, 3 warnings in 10.77s

scripts/test_idempotency.sh:
  Results: 7 passed, 0 failed
  ACCEPTANCE TEST: PASS
```

### Metrics/results
- Sequential duplicate: 1 DB row ✓
- Concurrent duplicate (asyncio.gather): 1 DB row ✓
- Fresh event end-to-end: 202 → Celery runs → 1 DB row ✓
- Redis unavailable: Postgres UNIQUE constraint catches duplicate ✓
- Postgres unavailable: 503 returned ✓

## 6. Plan Compliance Review

### Fully aligned
- DB-level `UNIQUE(event_id)` constraint — not application-only.
- Insert-and-catch pattern — no SELECT→INSERT race.
- Redis `SET NX` fast path with 24h TTL.
- Postgres `503` when unavailable.
- Append-only trigger installed in same migration (not Day 10).

### Deviations
- **Architecture: Celery-first (user-approved decision).**
  - Original plan implied synchronous-feeling response with inline scoring.
  - Changed to: `202 Accepted` immediately; Celery task does pipeline/score/SHAP/write.
  - Reason: retrofitting Celery in Day 8 would require rewriting idempotency wiring twice; user explicitly approved this shape before implementation.
  - Impact on later phases: Day 7 router and Day 8 LLM task build on this; no rework needed.

### Why deviations were necessary
See above — user-directed before any code was written.

### Impact on later phases
- Day 7: `app/services/router.py` dispatches Razorpay call from inside (or after) `score_order_task`; `PaymentLinkState` table already exists.
- Day 8: LLM explanation task dispatched from `score_order_task` after Postgres write; `celery_app.py` include list has a commented placeholder ready.

## 7. Problems Encountered

- **Problem:** `psql` not installed in the API container; shell script used `psql` for DB queries.
- **Root cause:** `postgresql-client` package not in Dockerfile — only `psycopg2-binary` (Python).
- **Fix:** Replaced `psql` calls with `python3 -c` using psycopg2.
- **Remaining risk:** None.

- **Problem:** Shell script `((PASS++))` exits with code 1 under `set -e` when PASS==0.
- **Root cause:** Bash arithmetic expansion returns exit code equal to the arithmetic result; `0` is falsy.
- **Fix:** Switched to `PASS=$((PASS + 1))` and removed `-e` from `set`.
- **Remaining risk:** None.

## 8. Decisions

- **Decision:** Celery-first architecture from Day 6 (202 + task), not synchronous with Day 8 retrofit.
- **Reason:** Avoids rewriting idempotency wiring twice; aligns with the LLM architecture rule (HTTP response never waits on async work).
- **Alternatives rejected:** Synchronous inline scoring → would require full rewrite when Day 8 adds LLM task.

- **Decision:** Append-only trigger installed in `create_all_tables()` at startup.
- **Reason:** Checkpoint 2 requires it as a blocking criterion; deferring to Day 10 adds needless migration risk.
- **Alternatives rejected:** Application-layer soft delete → insufficient (a bug can still write an UPDATE).

- **Decision:** Duplicate response looks up Postgres row (not Redis-cached full response).
- **Reason:** Avoids Redis storing large JSON blobs; the DB is the durable source of truth; the lookup is cheap (primary key index on event_id).

## 9. Suggestions for Next Session

- Day 7: `score_order_task` should be extended or a new Celery task should dispatch the Razorpay call for `SOFT_GATE_COD` tier, using `PaymentLinkState` (already created).
- Day 7: `app/api/webhooks.py` — `POST /v1/webhooks/razorpay` with signature verification before any business logic.
- Day 7: `app/services/razorpay_client.py` — deterministic `reference_id`, reconciliation-safe retry.

## 10. Next Required Action

The next agent should:
1. Read `implementation_plan.md` Day 7.
2. Inspect `app/db/models.py` — `PaymentLinkState` is already created; no schema migration needed.
3. Implement `app/services/router.py`, `app/services/razorpay_client.py`, `app/api/webhooks.py`.
4. Wire Razorpay sandbox call into `score_order_task` (or a new chained task) for `SOFT_GATE_COD` tier.
5. Add `pytest tests/test_razorpay_integration.py` with invalid-signature rejection test.

## Do Not Repeat

- Do NOT use SELECT→INSERT for deduplication — insert-and-catch is the only safe pattern.
- Do NOT use `psql` in shell scripts inside the API container — use `python3 -c` with psycopg2.
- Do NOT make `score_order_task` block the HTTP response — the endpoint returns 202 immediately.
- Do NOT let task failure leave a live Redis dedup key — always delete it on retries exhausted.
- Do NOT return a bare 404 from the GET polling endpoint — distinguish processing/failed/unknown.

## 11. Post-Completion Fixes (session 2 — 2026-08-26T15:10 IST)

### Bug identified by user review

**Bug: Task failure permanently blackholes the event_id for 24h.**

**Failure path:**
```
Redis SET NX succeeds → task dispatched → 202 returned
→ task throws (any error) → retries exhausted → no audit row written
→ Redis dedup key still lives with 24h TTL
→ any retry of that event_id hits fast-path → "already processed"
→ order silently lost for up to 24 hours
```

This is a correctness bug independent of Day 6 moving money, because Day 7 chains Razorpay dispatch on top of this exact pattern — a transient failure there would lose a payment-link creation with no automatic retry path.

**Two smaller issues also identified:**
1. GET polling endpoint: `404` was indistinguishable between "processing" and "never seen" — a client can't tell whether to wait or give up.
2. No tests covered the GET endpoint in any state.

---

### Fixes implemented

#### Fix 1: Task retry with exponential backoff

`app/services/scoring.py` — `score_order_task` now retries up to 3 times on any exception:

| Attempt | Wait before next |
|---|---|
| 1 (initial) | fails → wait 5s |
| 2 (retry 1) | fails → wait 15s |
| 3 (retry 2) | fails → wait 45s |
| 4 (retry 3) | retries exhausted → `_handle_final_failure` |

Backoff shape matches the spec's Razorpay call failure table (§9) — same pattern, not new work.

#### Fix 2: `_handle_final_failure` — sentinel write + Redis key delete

On retries exhausted, `_handle_final_failure(event_id, order_id, task_id, error, retry_count)`:

1. **Writes a `ScoringFailure` row** — observable, not silent; includes error message and retry count.
2. **Deletes the Redis dedup key** — `redis.delete(f"dedup:{event_id}")` — so legitimate resubmission is treated fresh.

**Why a separate `scoring_failures` table instead of a FAILED sentinel in `audit_log`:**
Writing a FAILED row to `audit_log` would re-trigger the UNIQUE constraint on resubmission, incorrectly routing it as a duplicate. A separate table keeps `audit_log` semantically clean (only successfully scored orders) and eliminates the double-dedup problem.

#### Fix 3: GET endpoint — four distinguishable states

`GET /v1/orders/{event_id}/result?task_id=<celery_task_id>` now returns:

| HTTP | `status` | Source | Meaning |
|---|---|---|---|
| 200 | `complete` | `audit_log` | Scoring done, row present |
| 200 | `failed` | `scoring_failures` | Retries exhausted, Redis key deleted, safe to resubmit |
| 202 | `processing` | Celery `AsyncResult` | Task PENDING/STARTED/RETRY |
| 404 | `unknown` | Nothing found | event_id never submitted or task_id stale |

#### Fix 4: Tests extended from 5 → 9

Four new tests added to `tests/test_idempotency.py`:

| Test | Asserts |
|---|---|
| `test_get_result_complete` | 200, `status=complete`, score/tier in body |
| `test_get_result_failed_state` | 200, `status=failed`, retry_count present, "resubmit" in message |
| `test_get_result_processing` | 202 or 404 (Celery mock boundary), not the wrong 404 |
| `test_get_result_unknown` | 404, `detail.status=unknown` |

### Files changed in session 2

| File | Change |
|---|---|
| [`app/db/models.py`](file:///c:/Users/vom69/Desktop/BUILDATHON/app/db/models.py) | Added `ScoringFailure` table |
| [`app/services/scoring.py`](file:///c:/Users/vom69/Desktop/BUILDATHON/app/services/scoring.py) | Full rewrite: retries, `_handle_final_failure`, `_delete_redis_dedup_key` |
| [`app/api/routes.py`](file:///c:/Users/vom69/Desktop/BUILDATHON/app/api/routes.py) | Four-state GET endpoint, `_lookup_scoring_failure` helper |
| [`tests/test_idempotency.py`](file:///c:/Users/vom69/Desktop/BUILDATHON/tests/test_idempotency.py) | 4 new GET tests |

### Test results after fixes

```
pytest tests/test_idempotency.py -v
======================== 9 passed, 3 warnings in 11.05s ========================
```

All original 5 idempotency tests still pass. 4 new GET endpoint tests pass.

---

## 12. Completion Gate (updated)

- Acceptance test: PASS (9/9 pytest + 7/7 shell integration)
- Deliverables present: YES
  - `app/api/routes.py` ✓ (four-state GET endpoint)
  - `app/db/models.py` ✓ (`ScoringFailure` table added)
  - `app/db/session.py` ✓
  - `app/core/idempotency.py` ✓
  - `app/services/scoring.py` ✓ (retry backoff + final failure handler)
  - `scripts/test_idempotency.sh` ✓
  - `tests/test_idempotency.py` ✓ (9 tests)
- Blocking issues: NONE
- Phase complete: YES

---

## 13. Post-Completion Fixes (session 3 — 2026-08-26T15:14 IST)

### Issues identified by user review

**Blocking: POST duplicate branch not aligned with GET's three-state model.**

The original Redis-duplicate branch on `POST /v1/orders/score` only checked `audit_log`. During the "still retrying" window (up to 65s per attempt × 3 retries ≈ minutes), a resubmission that hit the Redis duplicate fast-path would find no `audit_log` row and return either a malformed response or an undifferentiated 202 with no `task_id`. Undefined behavior in a window that is easily triggered by Shopify webhook retries or merchant resubmissions.

**Worth doing: flip `_handle_final_failure` operation order.**

Previous order: sentinel write → Redis delete. If the process crashed between them, the Redis key survived with the sentinel already written — the original 24h blackhole re-introduced in the one path meant to close it. Flipping to delete-first means a crash leaves the key gone (resubmission unblocked) at the cost of a missing sentinel row (loss of observability for one incident).

**Smaller: `test_get_result_processing` accepted either 202 or 404.**

The test was asserting "doesn't crash" rather than the actual behavior. The Celery mock was not reliably wiring through the local import inside the route handler.

**Missing: end-to-end resubmission proof.**

The unit tests confirmed each state rendered in isolation; none proved that Fix 2 actually unblocks a resubmission and allows a fresh task to run.

---

### Fixes implemented

#### Fix A (blocking): POST duplicate branch — three-way state check

`app/api/routes.py` — `is_redis_duplicate` branch now mirrors GET exactly:

| Lookup | Result | POST response |
|---|---|---|
| `audit_log` row found | task completed | `200 duplicate` with score/tier/action |
| `scoring_failures` row found | retries exhausted, key still present (crash window) | `200 failed` with resubmission guidance |
| Neither found | task still running/retrying | `202 processing` with poll-GET hint |

The normal "failed + key deleted" resubmission never reaches this branch (key is gone, falls through to fresh submission) — this covers only the narrow crash window.

#### Fix B (worth doing): `_handle_final_failure` — delete-key-first

`app/services/scoring.py` — operation order flipped:

```
BEFORE: sentinel write → Redis delete
AFTER:  Redis delete → sentinel write
```

If process crashes between the two steps:
- **Before**: Redis key alive + sentinel written → resubmission blocked (bug re-introduced)
- **After**: Redis key gone + no sentinel → resubmission unblocked (loses observability, not correctness)

#### Fix C (smaller): `test_get_result_processing` — exact assertion

`tests/test_idempotency.py` — mock changed to patch `celery.result.AsyncResult` at the correct import level. Now asserts exactly `202` and `status=processing` and `task_id` in body — not `in (202, 404)`.

#### Fix D (missing test): `test_resubmission_after_exhausted_retries`

Five-phase end-to-end test proving the fix closes the blackhole:

1. Submit → 202; Redis key written.
2. Force `_handle_final_failure` with mocked sync Redis that mutates shared `redis_keys` set. Asserts key is gone after the call.
3. GET `/result` → `status=failed` (sentinel present).
4. Re-POST same `event_id` → `202` (fresh, not duplicate); task enqueued again; new Redis key written.
5. GET `/result` → `status=complete`.

### Files changed in session 3

| File | Change |
|---|---|
| [`app/api/routes.py`](file:///c:/Users/vom69/Desktop/BUILDATHON/app/api/routes.py) | POST `is_redis_duplicate` branch: three-way state check (audit_log → scoring_failures → processing) |
| [`app/services/scoring.py`](file:///c:/Users/vom69/Desktop/BUILDATHON/app/services/scoring.py) | `_handle_final_failure`: delete-key-first, sentinel-second; updated docstring |
| [`tests/test_idempotency.py`](file:///c:/Users/vom69/Desktop/BUILDATHON/tests/test_idempotency.py) | `test_get_result_processing` tightened; `test_resubmission_after_exhausted_retries` added |

### Test results after session 3 fixes

```
pytest tests/test_idempotency.py -v
======================= 10 passed, 3 warnings in 10.02s ========================
```

All 10 tests pass. `test_get_result_processing` now asserts exactly 202, not 202-or-404.

---

## 14. Post-Completion Verification (session 4 — 2026-08-26T15:20 IST)

### 1. Live Redis Key Deletion & Retry Exhaustion Test

To ensure the test suite wasn't relying purely on unit mock doubles, a live end-to-end integration script was authored and executed inside the Docker container: [`scripts/test_live_retry_and_redis_delete.sh`](file:///c:/Users/vom69/Desktop/BUILDATHON/scripts/test_live_retry_and_redis_delete.sh).

**Test Execution Steps on Real Infrastructure:**
1. **Failure Induction:** Renamed `/workspace/models/xgboost_rto_v1.base.bin` inside the container to force `FileNotFoundError` across all attempts.
2. **Submission:** `POST /v1/orders/score` returned `202 Accepted`.
3. **Immediate Redis Check:** Verified `dedup:<event_id>` key was written into real Redis (`EXISTS`).
4. **Retry Loop Wait:** Celery worker executed retry backoff (5s → 15s → 45s). At ~60s mark, retries exhausted and `_handle_final_failure` executed.
5. **Key Deletion Verified:** Verified via real Redis client that `dedup:<event_id>` was `GONE`.
6. **Sentinel Verified:** Verified 1 row recorded in PostgreSQL `scoring_failures`.
7. **Model Restored:** Model file restored to original path.
8. **Resubmission:** Submitted the same `event_id` again. API received it as fresh (returned `202 Accepted`, wrote new Redis key).
9. **Final Scored Row:** Celery completed execution; verified row inserted into PostgreSQL `audit_log`.

**Result:** 7/7 checks PASSED on live Redis / Celery / Postgres stack.

---

### 2. Architectural Note: `scoring_failures` Reconciliation for Day 9 / Day 10

- **Honest History:** When an order initially fails all retries and is subsequently resubmitted and succeeds, both a row in `scoring_failures` and a row in `audit_log` will exist for that `event_id`.
- **Dashboard / Metrics Guideline (Day 9):** Metric queries counting permanent failures must NOT simply do `SELECT COUNT(*) FROM scoring_failures`. Instead, calculate unrecovered failures via `WHERE NOT EXISTS (SELECT 1 FROM audit_log a WHERE a.event_id = scoring_failures.event_id)` or `LEFT JOIN audit_log ... WHERE audit_log.id IS NULL`.
- **Audit Trail (Day 10):** `audit_log` remains strictly append-only and contains only valid, completed scores. `scoring_failures` serves as the failure log.

---

## 15. Completion Gate (final)

- Acceptance test: PASS
  - `pytest tests/test_idempotency.py`: 10/10 PASSED
  - `scripts/test_idempotency.sh`: 7/7 PASSED
  - `scripts/test_live_retry_and_redis_delete.sh`: 7/7 PASSED (live Redis / Celery)
- Blocking issues: NONE
- Phase complete: YES — cleared for Day 7
- Do not repeat rules (cumulative):
  - Do NOT use SELECT→INSERT for deduplication
  - Do NOT use `psql` in shell scripts inside the API container (use `python3 -c` with psycopg2/asyncpg)
  - Do NOT let `score_order_task` block the HTTP response
  - Do NOT let task failure leave a live Redis key (delete-first in `_handle_final_failure`)
  - Do NOT return bare 404 from GET polling endpoint (distinguish complete / failed / processing / unknown)
  - Do NOT write sentinel before deleting Redis key in failure handler
  - Do NOT make the POST duplicate branch check only `audit_log` — check all three states
  - Do NOT count `scoring_failures` blindly in Day 9 dashboards without filtering out recovered events present in `audit_log`

---

## 16. Sanity-Check Verification (session 5 — 2026-08-26T15:25 IST)

Two concerns were raised for explicit verification before Day 7.

---

### Concern 1 — Is `test_resubmission_after_exhausted_retries` testing a mock or the real code path?

**Short answer:** The unit test uses a mock; the real code path was verified by the live integration script in session 4. Both proofs are on record. Nothing is papering over a real bug.

**Detailed analysis:**

The concern is legitimate — async clients are easy to paper over with mocks (e.g. forgetting `await` before `.delete()`). Here is what was verified:

1. **The client is NOT async.** `_delete_redis_dedup_key` (in `scoring.py` L182–198) uses `sync_redis.from_url(...)` — the synchronous `redis-py` client, not `aioredis` or `redis.asyncio`. There is no `await` to forget. The call is `client.delete(f"dedup:{event_id}")` — a blocking synchronous call that runs in the Celery worker process. The mock-vs-reality concern about `await` does not apply to this code path.

2. **The key format matches exactly.** `idempotency.py` defines `_KEY_PREFIX = "dedup:"` and sets the key as `dedup:{event_id}`. `scoring.py` deletes `f"dedup:{event_id}"`. They are the same string for any given `event_id`.

3. **The live integration script (`scripts/test_live_retry_and_redis_delete.sh`) ran in session 4** against real Redis, real Celery worker, real Postgres — not mocks. It forcibly induced failure (model file renamed), waited for all retries to exhaust (5s → 15s → 45s backoff), then verified:
   - Redis key `dedup:{event_id}` was `GONE` after `_handle_final_failure` ran (via `python3 -c "import redis; r.exists(key)"`)
   - `scoring_failures` row was present in Postgres
   - Resubmission returned 202 (treated as fresh)
   - New Redis key was set for the fresh submission
   - After resubmission task ran, `audit_log` row was present

   Result: **7/7 PASS** on live infrastructure.

**What `test_resubmission_after_exhausted_retries` proves:** That `_handle_final_failure` deletes the mock Redis keyspace before writing the sentinel, and that the API then accepts the same `event_id` as a fresh submission. It is a unit-level proof of the correctness of the logic flow.

**What the live script proves:** That the real `sync_redis.from_url(...).delete(...)` call reaches the actual Redis server and removes the key, and that a real Celery task triggers `_handle_final_failure` after real retry backoff.

**Status:** Both proofs are on record. The mocked unit test is explicitly labelled as a unit-level proof; the live integration test is the real-world verification. No gap exists.

---

### Concern 2 — `scoring_failures` rows are never cleaned up; Day 9 may double-count

**Short answer:** Already documented in §14.2; now encoded in the model docstring, enforced by a test, and converted into the path of least resistance via a new queries module.

**What was done:**

1. **`ScoringFailure` model docstring updated** (`app/db/models.py`) — added an `IMPORTANT — DASHBOARD QUERY PATTERN` block with both the wrong query and the correct NOT EXISTS form.

2. **[NEW] `app/db/queries.py`** — exports two helpers:
   - `get_unrecovered_failures(session, *, limit, offset)` → returns rows from `scoring_failures` with no matching `audit_log` entry.
   - `count_unrecovered_failures(session)` → COUNT variant for dashboard widgets.
   
   The correct NOT EXISTS join is encapsulated here. Day 9 dashboard code calls `await get_unrecovered_failures(session)` or `await count_unrecovered_failures(session)` — no raw SQL, no chance of writing the wrong query.

3. **`test_scoring_failures_reconciliation_query_logic` updated** — now also asserts `app.db.queries` is importable and exports both helpers (catches a Day 9 refactor that accidentally removes them).

4. **Test result:** 11/11 PASS.

**What Day 9 must do:**
- Import from `app.db.queries` — not write raw `SELECT COUNT(*) FROM scoring_failures`.
- The `scoring_failures` table rows are never deleted (honest history). That is intentional.

---

## 17. Completion Gate (final, session 5)

- Acceptance test: PASS
  - `pytest tests/test_idempotency.py`: **11/11 PASSED**
  - `scripts/test_idempotency.sh`: 7/7 PASSED
  - `scripts/test_live_retry_and_redis_delete.sh`: 7/7 PASSED (live Redis / Celery)
- Blocking issues: NONE
- Phase complete: YES — cleared for Day 7
- Files added this session: `app/db/queries.py`
- Both session-5 sanity checks fully resolved and documented.
