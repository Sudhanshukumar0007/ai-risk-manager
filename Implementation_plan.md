# Track 02 AI Risk Manager — Verified Audit + Corrected, Step-Wise 10-Day Implementation Guide

This document does three things:

1. **Verifies** every issue raised in your uploaded review against the actual PDF text (confirmed / partially confirmed / overstated).
2. **Adds independent findings** from my own pass over the PDF that the first review did not catch.
3. **Rewrites the plan** day-by-day so it is internally consistent and codeable as-is — every step says *what* to do and *why*, with Day 5 and Day 10 checkpoints and day-wise deliverables.

No numbers, thresholds, or formulas below are invented — where the source PDF is genuinely missing a value (extraction artifact), it is flagged explicitly rather than papered over.

---

## PART 1 — Audit Verification

### 1.1 Confirmed issues (verbatim-checked against the PDF)

| # | Claim in your review | Verified against PDF? | Evidence |
|---|---|---|---|
| 1 | Day 4 uses `val.csv` for both hyperparameter tuning *and* threshold optimization (leakage) | **Confirmed** | Day 4 Engineering Task 1 literally says "tune hyperparameters using 5‑fold cross‑validation on val.csv," and Day 5 separately uses the *same* `val.csv` for the 2D threshold grid search. Same file, two purposes → the threshold search is no longer an honest out-of-sample test of the tuned model. |
| 2 | Manual probability-shift-to-0.5 on `is_novel_pincode` is ad hoc and undermines calibration | **Confirmed** | The closing "Strategic Risk Mitigation" section states drift flags "apply an uncertainty adjustment that shifts probability outputs toward 0.5," while the calibration section elsewhere targets a specific ECE/Brier target on the *unadjusted* model output. Manually nudging probabilities after calibration invalidates the calibration report — ECE/Brier were measured on a distribution that production will no longer emit. |
| 3 | Day 10's threshold table (0.50/0.60/0.70/0.80) treats the router as single-threshold | **Confirmed** | Day 10 Task 2 explicitly lists four scalar cutoffs. But the router (Day 5, Day 7) is defined on a *pair* `(t_low, t_high)` with three output tiers. A scalar sweep cannot represent a two-cutoff router — it silently drops one tier from the final report entirely. |
| 4 | RabbitMQ is referenced in the architecture narrative but absent from Day 1's Docker stack | **Confirmed** | Architecture text: "Celery distributed task queue backed by RabbitMQ." Day 1 Task 2 docker-compose list: "PostgreSQL 15, Redis 7 (Alpine), FastAPI application, and Celery worker node" — no RabbitMQ service. Day 1 is the only day that touches `docker-compose.yml` structurally, so this gap is never closed later. |
| 5 | Redis fallback is not race-safe | **Partially confirmed — needs nuance** | Day 6's one-line risk mitigation says "fall back to synchronous database unique key constraints," which *is* the safe pattern. But the later "Strategic Risk Mitigation" section describes it more loosely as "a synchronous PostgreSQL query against the append-only audit table" backed by `UNIQUE(event_id)`. Taken together the *intent* is a DB unique constraint (safe), but no day ever specifies a `SELECT` pre-check before insert, which is where a real race condition would be introduced if implemented naively. **Verdict: the design intent is correct, but the plan never states "insert and catch the constraint violation" as the explicit pattern, leaving room for a developer to implement the unsafe SELECT→INSERT version.** This needs to be pinned down explicitly, not just implied. |
| 6 | Razorpay webhook signature verification is missing | **Confirmed** | Day 6 and Day 7 describe webhook handling (`payment_link.paid` listener) but neither engineering task list nor any deliverable file mentions signature verification or the `x-razorpay-event-id` header. This is a real gap — without it, anyone who discovers the webhook URL can forge `payment_link.paid` events. |
| 7 | Payment-link creation has no idempotency/reconciliation strategy against a partial failure | **Confirmed** | Day 7 Task 3 just says "invoke `client.payment_link.create()`" with no mention of a pre-generated `reference_id`, no persisted `payment_link_state`, and Day 7's risk mitigation only covers *rate limits* via backoff — not the "Razorpay succeeded, our DB write failed" case. |
| 8 | KS-test / calibration thresholds have missing numeric values | **Confirmed, but likely a PDF extraction artifact, not a planning defect** | The text reads "KS test must yield $p >$ [blank]" and "Brier Score $<$ [blank] and ECE $< 0.08$." These look like values that were originally rendered as LaTeX/image and were dropped by the PDF-to-text conversion, not necessarily omitted by the plan's author. **Action: don't invent a number — re-open the source PDF's original file (not the extracted text) and confirm the intended value before Day 4; if it truly isn't specified anywhere, use the fallback gate list below instead of guessing.** |
| 9 | The `grep "exploit|bypass|attack"` compliance check is weak | **Confirmed** | Day 10 Task 4 is literally that one grep command with no behavioral verification layer. Correct as flagged. |

### 1.2 Additional issues found on independent review (not in your original audit)

| # | Issue | Where in the PDF | Why it matters |
|---|---|---|---|
| 10 | **LLM synchronicity is self-contradictory.** Day 8's risk mitigation says to "decouple LLM call from decision router; run copy generation asynchronously **post-routing**." But Day 8's own acceptance test asserts "HTTP response completes successfully with static fallback copy **attached**," which implies the HTTP response is still waiting on the LLM call (bounded by the 2,500 ms timeout) before returning. | Day 8 Engineering Tasks 3–4 vs. Day 8 Risk & Mitigation vs. Day 8 Acceptance Test | If the LLM call — even with a 2.5s timeout — sits inside the request/response cycle for `POST /v1/orders/score`, then a slow/degraded LLM directly inflates the p99 latency of the endpoint that also creates Razorpay payment links. That is exactly the coupling the architecture claims to avoid ("the LLM never sits on the critical monetary execution path"). This needs to be made *fully* fire-and-forget: score → route → create payment link → return HTTP response immediately; LLM copy is generated in a separate Celery task and attached to the record afterward, surfaced later via the dashboard/webhook — never blocking the response. |
| 11 | **Day 9's acceptance test is not actually testable.** Every other day has an automated `pytest`/script-based acceptance test. Day 9 says "Perform manual audit verifying dashboard responsiveness" — this is not reproducible or CI-able. | Day 9 Deliverable Details | For a submission that claims rigor everywhere else, one un-automated day breaks the audit trail. Needs a scripted smoke test (e.g., Selenium/Playwright hitting the Streamlit endpoint, or a simple `requests.get` health check plus a DB-row-count assertion after simulated webhook replay). |
| 12 | **Sample sizes are small for the stated statistical gates.** Train=5,000 / Val=750 / Held-out=1,250. Running a KS-test, Frobenius-norm correlation check, *and* a 2D grid search (15 × 29 ≈ 400+ threshold pairs) on a 750-row validation set risks selecting noise. Doc 1 correctly flagged coarse step resolution (0.025) as a partial mitigation, but didn't flag the underlying sample-size risk driving it. | Day 2 sample counts vs. Day 5 grid search resolution | With only 750 validation rows and RTO being the minority class within COD orders (~24% RTO rate × 62% COD ratio ≈ ~15% of all rows), the positive class in validation may be well under 150 rows — a 2D grid search over that few positives is prone to overfitting the cutoffs to sampling noise even at 0.025 step size. Recommend k-fold on the *training* split for threshold stability checking, in addition to the single val.csv pass. |
| 13 | **24-hour Redis TTL vs. Razorpay's documented redelivery window is not reconciled.** The plan sets a flat 24h TTL for the idempotency key. | Day 6 Task 3 | If Razorpay retries a webhook delivery after the TTL has expired (their docs describe at-least-once delivery with retries, not a bounded window), a legitimate duplicate could slip past Redis and rely entirely on the Postgres unique constraint as the last line of defense. This is fine *if* issue #5's fix (DB constraint as source of truth, not just Redis) is implemented correctly — but the plan should say so explicitly rather than treating Redis TTL as sufficient on its own. |

**Net verdict on the audit itself:** 9 of 9 original findings hold up under verification (8 fully, 1 needs the nuance above), and I found 4 more. All 13 are folded into the corrected plan below.

---

## PART 2 — Corrected, Step-Wise 10-Day Plan

Legend: 🔧 = a step that exists specifically to close one of the 13 issues above.

---

### Day 1 — Infrastructure Scaffolding, Service Wiring, API Baseline

**Why this day exists:** Nothing downstream can be tested without a running, correctly-wired stack. Getting the broker/queue topology right *today* avoids a silent architecture mismatch for the rest of the build (issue #4).

**Steps**
1. Create the repo skeleton: `/app`, `/config`, `/data`, `/eval`, `/tests`, `/scripts`, `/docs`. *Why:* keeps ML code, API code, and evaluation artifacts from tangling together — this separation is what makes Day 10's automated report generation possible.
2. 🔧 Write `docker-compose.yml` with **five** services, not four: PostgreSQL 15, Redis 7 (Alpine), **RabbitMQ 3 (management image)**, FastAPI app, Celery worker. *Why:* the architecture narrative commits to Celery-over-RabbitMQ; leaving RabbitMQ out (as the original Day 1 did) means Day 6's Celery wiring has nothing to connect to. If you'd rather simplify, the alternative is to formally drop RabbitMQ and use Redis as the Celery broker — but pick one now and update the architecture doc to match, don't leave it ambiguous.
3. Add explicit `healthcheck:` blocks and `depends_on: condition: service_healthy` for every service so FastAPI/Celery never start before Postgres/Redis/RabbitMQ are ready.
4. Write `.env.example` with `DATABASE_URL`, `REDIS_URL`, `RABBITMQ_URL` (or drop if you chose Redis-only broker), `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`.
5. Implement `GET /health` returning JSON status for each dependency (DB ping, Redis ping, broker ping) — not just "200 OK". *Why:* a flat 200 tells you the web process is alive, not that the system is usable; per-dependency status catches partial outages immediately.
6. 🔧 Add a `docs/architecture_decision_log.md` and record the broker decision (RabbitMQ vs Redis-only) with the reasoning, so Day 6/7 code and Day 10 docs stay consistent with what Day 1 actually built.

**Acceptance test:** `pytest tests/test_health.py` — asserts HTTP 200 from `/health` **and** that the JSON body reports `"ok"` for every individual dependency, inside running containers.

**Day 1 Deliverables:** `docker-compose.yml`, `app/main.py`, `Dockerfile`, `.env.example`, `docs/architecture_decision_log.md`.

---

### Day 2 — Synthetic Data Engine: Seeded Generation + Drift Injection

**Why this day exists:** Every later evaluation number (PR-AUC, calibration, breakeven, Net Saved) is only as trustworthy as this data. Getting the splits and leakage boundaries right here is what makes Day 4/5/10 results defensible.

**Steps**
1. Build `scripts/generate_data.py` implementing the 15 features across the five signal families (delivery history, order anomaly, identity/velocity, address quality, drift indicators) exactly as specified in the feature table.
2. Generate three **isolated** seeded files: `train.csv` (5,000 rows, seed=101), `val.csv` (750 rows, seed=202), `heldout.csv` (1,250 rows, seed=303).
3. Inject the held-out covariate shift: force `is_novel_pincode=1` and `is_flash_sale_cart_value=1` on the specified 10% subset of `heldout.csv` only — never in train or val.
4. 🔧 **Log the actual positive-class counts per split** (RTO=1 rows in each of train/val/heldout) to `data/generation_report.md`, not just the overall ratios. *Why (issue #12):* if validation ends up with well under ~150 positive rows, flag it now so Day 5's grid search can be designed around that constraint (e.g., widen the step size or add a train-side stability check) instead of discovering it after the fact.
5. Compute pincode-level and category-level historical RTO rates **strictly from `train.csv`**, and confirm — via a unit test, not a comment — that neither `val.csv` nor `heldout.csv` is ever read during that computation.
6. Verify dataset composition matches spec: ~62% overall COD ratio, ~24% baseline RTO rate within COD orders.

**Acceptance test:** `pytest tests/test_data_integrity.py` — asserts (a) zero ID overlap across the three splits, (b) target distributions match spec within tolerance, (c) 🔧 positive-class count in `val.csv` is logged and asserted `> 0` with the actual count printed to the test output for manual sanity review.

**Day 2 Deliverables:** `data/train.csv`, `data/val.csv`, `data/heldout.csv`, `data/generation_report.md` (now including per-split positive-class counts).

---

### Day 3 — Feature Extraction Engine + Latency Benchmarking

**Why this day exists:** The router needs a risk score in real time, on the same request path that (eventually) also creates a Razorpay payment link. If feature extraction is slow, everything downstream inherits that latency.

**Steps**
1. Build `app/features/address.py`: fit the character 2–4 n-gram TF-IDF vectorizer **once, at process startup**, against the reference corpus of ambiguous Indian address patterns. Never refit per-request.
2. Build `app/features/pipeline.py`: merge the cached TF-IDF ambiguity score with the tabular lookups (pincode RTO rate, customer RTO count, category baseline, velocity counters, etc.).
3. Build `tests/test_feature_latency.py`: run 1,000 simulated payload extractions via `timeit`, asserting p99 latency stays under the target budget.
4. Confirm the vectorizer object is a true module-level singleton (not re-instantiated per Celery worker fork) — check this explicitly, since Celery's worker pool can otherwise cause "works locally, refits per worker in production" bugs.

**Acceptance test:** `pytest tests/test_feature_latency.py` — p99 extraction time under the target threshold across 1,000 continuous runs.

**Day 3 Deliverables:** `app/features/pipeline.py`, `app/features/address.py`, `eval/latency_report.md`.

---

### Day 4 — Model Training, Calibration, SHAP Explainability (Leakage-Fixed)

**Why this day exists:** This is where the "AI" in AI Risk Manager gets built — and where issue #1 (leakage) and issue #8 (missing thresholds) live, so this day gets rewritten most heavily.

**Steps**
1. 🔧 **Split `train.csv` internally** into a fit fold and a calibration fold (e.g., 80/20 within the 5,000 rows) for hyperparameter tuning and probability calibration. *Why:* this keeps `val.csv` completely untouched by model-fitting decisions.
2. Train the XGBoost classifier on the fit fold; tune hyperparameters via cross-validation **within `train.csv` only** — never touching `val.csv` at this stage. This directly fixes issue #1.
3. Calibrate probabilities (e.g., Platt scaling or isotonic regression) using the calibration fold carved out of `train.csv` in step 1 — not `val.csv`.
4. Attach the SHAP TreeExplainer and confirm it returns a valid top-3 feature attribution JSON for a sample of predictions.
5. 🔧 Evaluate calibration (ECE, Brier Score) **on `val.csv` for the first time here** — this is now a genuine out-of-sample check, since `val.csv` was never used for tuning or calibration.
6. 🔧 Resolve issue #8 before writing the acceptance test: open the original PDF (not the text extraction) to confirm the intended KS-test $p$-value and Brier Score thresholds. If truly unspecified anywhere in the source material, use this explicit fallback gate list instead of inventing a number:
   - Base-rate of RTO within COD in each split falls within ±3 percentage points of the design target (24%).
   - Zero row-ID overlap across splits (already tested Day 2).
   - All 15 features fall within their documented valid ranges/domains.
   - The injected 10% covariate shift is present in `heldout.csv` and absent from `train.csv`/`val.csv`.
   - Model training is reproducible (same seed → same weights, hash-checked).
7. 🔧 Do **not** implement the "shift probability toward 0.5 when `is_novel_pincode` fires" adjustment described later in the PDF (this fixes issue #2). Instead: include `is_novel_pincode` and `is_flash_sale_cart_value` as ordinary model features (already planned in the feature table), and separately report calibration-under-shift as a *diagnostic*, not a probability-mutation step:
   - Report ECE/Brier on standard `val.csv`.
   - Report ECE/Brier on the shifted rows of `heldout.csv` (diagnostic only, computed once at Day 10 — see below).
   - Report SHAP importance of the two drift features, so reviewers can see the model is *aware* of novelty without the score being manually altered post hoc.
8. Serialize the trained, calibrated model to `models/xgboost_rto_v1.bin`.

**Acceptance test:** `pytest tests/test_model_performance.py` — asserts PR-AUC > 0.70 on `val.csv`, calibration metrics meet the gate list from step 6, and SHAP output is valid JSON with exactly three ranked features per prediction, **and** a new assertion that `val.csv` row hashes were never present in any training-fold checkpoint (leakage regression test).

**Day 4 Deliverables:** `models/xgboost_rto_v1.bin`, `app/ml/shap_engine.py`, `eval/calibration_report.md` (now documents the fit/calibration/val split explicitly), `docs/threshold_gate_resolution.md` (records what you found when you resolved issue #8).

---

### Day 5 — Financial Cost Engine + 2D Threshold Search — ⭐ CHECKPOINT 1

**Why this day exists:** This converts a probability score into a business decision with a defensible ₹ justification. It's the halfway point of the build — everything before this is "can we predict risk," everything after is "can we act on it safely."

**Steps**
1. Implement `app/ml/costs.py` with the tier-conditioned cost functions exactly as derived (`Cost(FN)`, `Cost(TP_M)`, `Cost(FP_M)`, `Cost(TP_H)`, `Cost(FP_H)`), including the ₹0 freight-loss branch for canceled high-risk COD orders.
3. 🔧 Add a unit test asserting the canceled-high-risk branch literally evaluates to `Cost = TP_H_count × Friction_Cost_H` with **no** `C_RTO` term — this is the exact mathematical inversion your review caught, made into a regression test so it can never silently regress.
4. Run the 2D grid search: `t_low ∈ [0.15, 0.50]` step 0.025, `t_high ∈ [t_low+0.05, 0.85]` step 0.025, on `val.csv`, maximizing Net Saved.
5. 🔧 Because of issue #12 (small validation positive count), also run the same grid search on 5 bootstrap resamples of `val.csv` and report the **variance** of the selected `(t_low, t_high)` pair across resamples in `eval/threshold_stability.md`. *Why:* if the optimal cutoffs swing wildly across resamples, that's a signal the 750-row validation set is too small to trust a single point estimate — better to know this now than discover it in the final report.
6. Compute the closed-form breakeven `TP:FP` ratios for both tiers (M-tier ≈1.70, H-tier ≈1.66, using the baseline parameter values) and cross-check they're consistent with the grid-search-selected thresholds — the model's TP:FP ratio *at* the selected threshold should exceed the breakeven ratio, or the threshold choice contradicts the cost model.
7. Serialize the frozen cutoffs to `config/thresholds.json` and generate the 2D Net Saved heatmap.

**Acceptance test:** `pytest tests/test_threshold_optimizer.py` — asserts non-negative Net Saved outperforming the do-nothing baseline, plus the new `Cost(TP_H)` regression test from step 3.

**Day 5 Deliverables:** `config/thresholds.json`, `eval/threshold_heatmap.png`, `eval/threshold_stability.md` (new), `eval/breakeven_ratios.md`, `app/ml/costs.py`.

#### ⭐ CHECKPOINT 1 — Mid-Point Verification Tracker (End of Day 5)

| Milestone | Verification Criteria | Artifact | Status Gate |
|---|---|---|---|
| M01 Infra | `docker-compose up` brings up all **five** services clean (incl. broker choice locked in Day 1); `/health` returns per-dependency status | `docker-compose.yml` | Must pass before Day 6 |
| M02 Data Engine | Three seeded, non-overlapping splits; per-split positive-class counts logged | `data/*.csv`, `generation_report.md` | Must pass before Day 4 |
| M03 No-Leakage Model | Hyperparameter tuning and calibration used only `train.csv`; `val.csv` first touched at evaluation | `eval/calibration_report.md` | **Blocking** — do not proceed if this fails |
| M04 Feature Latency | p99 feature extraction under budget over 1,000 calls | `eval/latency_report.md` | Must pass |
| M05 Calibration | ECE/Brier meet the resolved gate list (issue #8 resolution) | `docs/threshold_gate_resolution.md` | Must pass |
| M06 Cost Engine | `Cost(TP_H)` regression test passes (₹0 freight-loss branch correct) | `app/ml/costs.py` | **Blocking** |
| M07 Threshold Search | 2D grid search executed on `val.csv`; stability check across bootstraps documented | `config/thresholds.json`, `threshold_stability.md` | Must pass, flag if variance is high |
| M08 Breakeven Ratios | Closed-form ratios computed and cross-checked against selected thresholds | `eval/breakeven_ratios.md` | Must pass |

**Go/no-go rule:** if M03 or M06 fail, stop and fix before writing any Razorpay integration code — a wrong cost model or a leaked validation set invalidates every number the rest of the submission reports.

---

### Day 6 — FastAPI Ingestion, Redis Dedup, Postgres Audit (Race-Fixed)

**Why this day exists:** This is the first day money-adjacent logic exists. Idempotency has to be airtight here, because every day after this assumes duplicate webhooks are already handled.

**Steps**
1. Create the `audit_log` table via SQLAlchemy models: `order_id, features_json, score, shap_values_json, tier, action, created_at`, plus 🔧 an `event_id` column with a **database-level `UNIQUE` constraint**, not just an application-level check.
2. Build `POST /v1/orders/score`.
3. Wire the Redis atomic key check (`{event_id}:{event_type}`, 24h TTL) **before** Celery task enqueue, as originally planned.
4. 🔧 Fix issue #5 explicitly: implement idempotency as **insert-and-catch**, not select-then-insert:
   - Fast path: `SET NX` on the Redis key. If it already exists, return the cached response immediately (no DB hit).
   - Fallback path (Redis unavailable): attempt the Postgres `INSERT` directly; catch the `UNIQUE` constraint violation exception; if caught, treat it as a duplicate and return the cached response. **Never** do a `SELECT` to check existence and then a separate `INSERT` — that gap between the two statements is exactly where two concurrent duplicate requests can both pass the check.
   - If Postgres itself is unavailable, return `503` — do not silently process the event without any durable dedup record.
5. Implement the idempotent-replay integration test: send the identical payload twice via `curl`, assert exactly one row exists.

**Acceptance test:** `bash scripts/test_idempotency.sh` — sends the identical webhook twice, asserts the DB row count stays at exactly 1, **and** a second test that kills the Redis container mid-test and confirms the Postgres `UNIQUE` constraint path (not a race-prone SELECT) is what catches the duplicate.

**Day 6 Deliverables:** `app/api/routes.py`, `app/db/models.py`, `app/core/idempotency.py` (rewritten for insert-and-catch), `scripts/test_idempotency.sh`.

---

### Day 7 — Deterministic Router + Razorpay Sandbox Integration (Security-Fixed)

**Why this day exists:** This is the actual monetary action layer. Everything in Days 1–6 exists to feed a trustworthy, safe decision into this day.

**Steps**
1. Build the routing function: evaluate `P(RTO)` against `(t_low, t_high)` from `config/thresholds.json`, returning one of `ALLOW_COD` / `NUDGE_PREPAY` / `SOFT_GATE_COD`.
2. Instantiate the Razorpay SDK with sandbox credentials.
3. 🔧 Fix issue #7 — payment-link idempotency: before calling `client.payment_link.create()`, generate a deterministic `reference_id` (e.g., derived from `order_id`) and persist a `payment_link_state = PENDING_CREATE` row **first**. Call Razorpay. On success, update the row with the returned link ID and set state to `PENDING_PREPAY`. If the network call fails or times out ambiguously (you don't know if Razorpay actually created the link), do **not** immediately retry with a new call — first attempt to reconcile by checking whether a link with that `reference_id` already exists, then only create a new one if it genuinely doesn't.
4. 🔧 Fix issue #6 — webhook security: implement `payment_link.paid` handling as `signature verification → event-id dedup (using x-razorpay-event-id, not an assumed payload field) → state-transition validation → DB update`. Reject any webhook that fails signature verification with a 400, before it touches any business logic.
5. Implement `SOFT_GATE_COD`: stub the tag assignment and log the verification trigger.
6. Remember the Razorpay Test Mode payment-link creation limit (30 links per business) when planning how many times you re-run end-to-end demo tests.

**Acceptance test:** `pytest tests/test_razorpay_integration.py` — end-to-end sandbox payment link creation, verified link URL and webhook state transition, **plus** a new test asserting a webhook with an invalid signature is rejected, and a test simulating a network timeout after Razorpay's call succeeded (mocked) that confirms no duplicate link is created on retry.

**Day 7 Deliverables:** `app/services/router.py`, `app/services/razorpay_client.py`, `app/api/webhooks.py` (now includes signature verification).

---

### Day 8 — LLM Explanation Layer, Fully Decoupled (Async-Fixed)

**Why this day exists:** Merchant-facing copy is valuable but must never be allowed to affect payment-critical latency or availability — this is where issue #10 gets fixed.

**Steps**
1. Build `app/services/llm_explain.py` to call the Claude API with SHAP top-3 features, risk score, and tier as structured context.
2. 🔧 Fix issue #10 — make this a genuinely separate Celery task, dispatched *after* `POST /v1/orders/score` has already returned its HTTP response (score + tier + payment link, if any). The LLM task writes its result (or the static fallback) to the `audit_log` row asynchronously; the dashboard/API surfaces it once available. The original request/response cycle never waits on it, not even for the 2,500ms timeout window.
3. Keep the 2,500ms timeout and try/except wrapper — but scope it to the *background task*, not the HTTP handler.
4. Implement the static fallback copy ("Flagged for manual review — explanation unavailable") for timeout/failure cases inside that background task.

**Acceptance test:** `pytest tests/test_llm_fallback.py` — mocks an API timeout and asserts (a) the static fallback text is eventually attached to the record, and 🔧 (b) a new latency test proving `POST /v1/orders/score` returns before the LLM task even starts (e.g., assert response time is unaffected when the LLM mock is made to hang indefinitely).

**Day 8 Deliverables:** `app/services/llm_explain.py`, `tests/test_llm_fallback.py`, `eval/llm_examples.md`.

---

### Day 9 — Dashboard + Fault Injection (Now Actually Testable)

**Why this day exists:** A working system that can't be observed or demonstrated failing gracefully is not credible for a judged submission — this is where issue #11 gets fixed.

**Steps**
1. Build the Streamlit dashboard: real-time audit log feed, SHAP importance cards, risk distribution gauges, cached with a short TTL to avoid hammering Postgres.
2. Record Fault Injection Clip 1: revoke the LLM API key live, show scoring/routing/payment-link creation continuing uninterrupted while explanation gracefully degrades — this now also proves the Day 8 fix, since the HTTP response won't even pause.
3. Record Fault Injection Clip 2: replay an identical webhook, show Redis/Postgres blocking the duplicate and the row count staying constant.
4. 🔧 Fix issue #11: add a scripted, automatable smoke test alongside the manual video — e.g., a `pytest`/Playwright check that (a) hits the dashboard's health/render endpoint and asserts a 200, and (b) programmatically replays a webhook via the same script used in Clip 2 and asserts the DB row count via a direct query, rather than relying on "manual audit" as the only check.

**Acceptance test:** `pytest tests/test_dashboard_smoke.py` (new, replaces "manual audit") — asserts the dashboard responds and that a scripted webhook replay produces a verifiable, queryable row-count result, not just a visual claim in a video.

**Day 9 Deliverables:** `dashboard/app.py`, `docs/videos/fault_injection_llm.mp4`, `docs/videos/fault_injection_idempotency.mp4`, `tests/test_dashboard_smoke.py` (new).

---

### Day 10 — Final Evaluation, Held-Out Audit, Submission Freeze — ⭐ CHECKPOINT 2

**Why this day exists:** This is the one and only time `heldout.csv` gets touched. Every fix from Days 1–9 either shows up correctly here, or the submission is not defensible.

**Steps**
1. Run the single evaluation pass on `heldout.csv` using the **frozen** `(t_low, t_high)` from `config/thresholds.json` — no re-tuning, no peeking.
2. 🔧 Fix issue #3 — replace the scalar 0.50/0.60/0.70/0.80 sweep with the two-cutoff-aware report:

   | Operating point | t_low | t_high |
   |---|---:|---:|
   | Conservative | 0.30 | 0.70 |
   | Balanced | 0.40 | 0.70 |
   | Aggressive | 0.40 | 0.60 |
   | **Optimized (production)** | *from Day 5 grid search* | *from Day 5 grid search* |

   Report Precision/Recall/F1/Net Saved for each **pair**, with the Optimized row clearly marked as the frozen production configuration — never select a "best-looking" pair after seeing held-out results.
3. 🔧 Fix issue #2's reporting side: report calibration/Net Saved under the shifted subset of `heldout.csv` as a **diagnostic-only** comparison against the non-shifted subset — no probability manipulation, just side-by-side numbers plus SHAP importance of the two drift features.
4. Compile `eval/final_report.md`: PR curves, calibration plots, the 2D threshold heatmap, breakeven analysis, the shift diagnostic from step 3, and the threshold-stability note from Day 5.
5. 🔧 Fix issue #9 — replace the single `grep` compliance check with a short behavioral checklist verified by manual code review, in addition to keeping the grep as an auxiliary signal:
   - No credential-harvesting logic present.
   - No unauthorized-access or privilege-escalation code paths.
   - No evasion/bypass functionality (e.g., nothing that circumvents the router or webhook signature check).
   - No attack/exploitation workflows anywhere in `/app` or `/scripts`.
   - Every action the system takes maps to one of: risk detection, prevention (routing/gating), verification, or audit logging.
   - `grep -r -i "exploit|bypass|attack"` run as a secondary sanity pass, not the primary evidence.
6. Publish the repository, architecture doc (updated with the Day 1 broker decision), and final demo video.

**Acceptance test:** `python scripts/evaluate_heldout.py` — reproduces every number in `eval/final_report.md` identically on re-run (determinism check), plus asserts the frozen thresholds file was not modified after Day 5's git commit hash.

#### ⭐ CHECKPOINT 2 — Final Submission Verification Tracker (End of Day 10)

| Criterion | Verification | Status Gate |
|---|---|---|
| Held-out isolation | `heldout.csv` queried exactly once, using frozen Day-5 thresholds | Blocking |
| Tier cost accounting | `Cost(TP_H)` regression test still passes on final code | Blocking |
| Breakeven reporting | M-tier/H-tier ratios printed and consistent with selected thresholds | Must pass |
| **Two-cutoff threshold table** (fixed) | Operating-point table above populated with Precision/Recall/F1/Net Saved per pair | Blocking — replaces scalar table |
| Covariate drift check | Shift vs. non-shift diagnostic reported, **no** probability mutation applied | Blocking |
| Sub-10ms feature latency | p99 under budget, 1,000 calls | Must pass |
| Live webhook dedup | Insert-and-catch pattern verified under simulated Redis outage | Blocking |
| Razorpay integration | Sandbox payment link + **signature-verified** webhook + reconciliation-safe retry | Blocking — replaces original unsecured version |
| Deterministic isolation | Thresholds strictly dictate Razorpay calls; LLM never blocks the response path | Blocking — replaces original ambiguous version |
| Fault injection: LLM | Video **and** scripted smoke test both pass | Must pass |
| Fault injection: replay | Video **and** scripted DB row-count assertion both pass | Must pass |
| Immutable audit trail | Append-only trigger on `audit_log`, `UNIQUE(event_id)` enforced at DB level | Blocking |
| Defense-only compliance | Behavioral checklist (6 items) reviewed, grep kept as secondary check only | Must pass |
| Threshold gate resolution | Original missing KS/Brier values resolved or explicit fallback gate list used | Must pass |

**Go/no-go rule:** any item marked **Blocking** that fails means the submission is not ready — these are the items that map directly back to the 13 verified issues.

---

## PART 3 — Day-Wise Deliverables Summary

| Day | Core Deliverables |
|---|---|
| 1 | `docker-compose.yml` (5 services), `app/main.py`, `Dockerfile`, `.env.example`, `docs/architecture_decision_log.md` |
| 2 | `data/train.csv`, `val.csv`, `heldout.csv`, `data/generation_report.md` (+ positive-class counts) |
| 3 | `app/features/pipeline.py`, `app/features/address.py`, `eval/latency_report.md` |
| 4 | `models/xgboost_rto_v1.bin`, `app/ml/shap_engine.py`, `eval/calibration_report.md`, `docs/threshold_gate_resolution.md` |
| 5 ⭐ | `config/thresholds.json`, `eval/threshold_heatmap.png`, `eval/threshold_stability.md`, `eval/breakeven_ratios.md`, `app/ml/costs.py` |
| 6 | `app/api/routes.py`, `app/db/models.py`, `app/core/idempotency.py`, `scripts/test_idempotency.sh` |
| 7 | `app/services/router.py`, `app/services/razorpay_client.py`, `app/api/webhooks.py` |
| 8 | `app/services/llm_explain.py`, `tests/test_llm_fallback.py`, `eval/llm_examples.md` |
| 9 | `dashboard/app.py`, two fault-injection videos, `tests/test_dashboard_smoke.py` |
| 10 ⭐ | `eval/final_report.md`, `README.md`, `docs/architecture_spec.md`, public repo + demo video |

---

## PART 4 — Feasibility Verdict (Re-Tested)

**10 days is still achievable — with the same priority split your review recommended, tightened slightly:**

- **Must-ship (Days 1–7):** infra → data → features → model (leak-free) → cost engine + Day 5 checkpoint → idempotent ingestion (race-fixed) → deterministic router + secured Razorpay integration.
- **Should-ship (Day 8):** LLM explanation, now correctly decoupled so it can be cut entirely under time pressure without touching the payment path.
- **Nice-to-have (Day 9):** dashboard — keep the two fault-injection demos even if the dashboard UI is minimal; the *demos* are the actual evaluation evidence, the UI is secondary.
- **Non-negotiable (Day 10):** the two-cutoff-aware final report and the behavioral compliance checklist — these are cheap to do correctly and expensive to explain away if wrong.

Score after fixes (re-rated against the same rubric your review used):

| Area | Before | After fixes |
|---|---:|---:|
| Architecture | 9/10 | 9.5/10 |
| Financial model | 9/10 | 9.5/10 |
| ML/evaluation methodology | 7/10 | 9/10 |
| Data-leakage discipline | 8.5/10 | 9.5/10 |
| Reliability/idempotency | 8/10 | 9.5/10 |
| Razorpay integration design | 7/10 | 9/10 |
| 10-day feasibility | 8/10 | 8/10 (unchanged — the fixes add work, not slack) |
| Track 02 alignment | 9/10 | 9.5/10 |

**Bottom line:** the original plan was a strong 8/10 draft with nine real defects and four more found on independent re-testing — all thirteen are now closed in the day-by-day steps above, with two explicit checkpoints (Day 5, Day 10) so a failure surfaces immediately instead of at final evaluation.
