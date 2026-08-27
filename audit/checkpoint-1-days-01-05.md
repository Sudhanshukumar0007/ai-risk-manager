# Checkpoint 1 Audit - Track 02 AI Risk Manager

Audit date: 2026-08-28 IST  
Scope: Checkpoint 1 only, Days 1-5, Milestones M01-M10  
Auditor role: Lead Technical Product Auditor and ML Systems Architect  
Gate under review: readiness to proceed to Day 6

## Executive Summary

Readiness score: 86%

Gate verdict: CONDITIONAL GO

Checkpoint 1 is substantially implemented and passes the available automated
test evidence. The live Docker stack reports healthy services, `/health`
performs real dependency checks, the synthetic splits are deterministic and
isolated, the feature pipeline is fast, model training/calibration avoids
direct validation leakage, the high-risk cost branch is mathematically correct,
and the optimized thresholds are frozen in configuration.

The gate is not a clean GO. Four material risks remain before Checkpoint 1
sign-off: the drift features have zero SHAP weight in the trained model, the
validation set has only 110 positive RTO rows, threshold bootstrap stability is
weak, and the feature-vectorizer singleton guarantee is process-level only with
no explicit fork lifecycle control. These are not cosmetic issues; they affect
model behavior under the heldout shift and confidence in the Day 5 threshold
selection.

Verification performed:

- `docker compose ps`: all services healthy: api, celery_worker, dashboard,
  postgres, rabbitmq, redis.
- Live health probe: `GET http://localhost:8000/health` returned HTTP 200 with
  postgres, redis, and rabbitmq all `ok`.
- In-container official health test: `tests/test_health.py` passed, 5/5.
- User-provided full container run: 85/85 tests passed in 33.66s.
- Auditor direct checks: split row counts, RTO counts, zero ID overlap, drift
  placement, TF-IDF configuration, and cost-engine breakeven math.

## Deliverables Traceability Matrix

| Milestone / Day | Planned Deliverable | Status | Verification Evidence / File Path | Gap Details |
|---|---|---:|---|---|
| M01 / Day 1 | Docker Compose service definitions for Postgres, Redis, RabbitMQ, API, Celery with healthchecks and environment wiring | COMPLIANT | `docker-compose.yml`; live `docker compose ps` all healthy | Compose still includes obsolete `version: "3.9"` warning. Non-blocking cleanup. |
| M01 / Day 1 | Broker topology explicitly resolved and documented | COMPLIANT | `docs/architecture_decision_log.md`, ADR-001; `app/core/config.py`; `app/core/celery_app.py` | RabbitMQ is clearly chosen as Celery broker; Redis is result backend. |
| M01 / Day 1 | `/health` performs true dependency pings for Postgres, Redis, Broker and passes health tests | COMPLIANT | `app/main.py`; `tests/test_health.py`; live health JSON; container test 5/5 passed | Host Python env missing `pytest_asyncio`, but container verification passed. |
| M02 / Day 2 | Triple-seeded generation: train seed 101, val seed 202, heldout seed 303 | COMPLIANT | `scripts/generate_data.py`; `data/generation_report.md` | Seeds and row counts are explicit and reproduced. |
| M02 / Day 2 | Zero ID/UUID overlap across splits | COMPLIANT | `tests/test_data_integrity.py`; direct check: overlaps 0/0/0 | No UUID column exists; `order_id` is the split identity key. |
| M03 / Day 2 | Target encodings and reference statistics derived strictly from train.csv | COMPLIANT | `scripts/generate_data.py`; `config/historical_rates.json`; `tests/test_data_reproducibility.py` | Historical pincode/category rates are train-only. |
| M03 / Day 2 | Positive-class counts recorded per split | COMPLIANT | `data/generation_report.md` | Counts recorded: train 739, val 110, heldout 184. Val count is thin and correctly flagged. |
| M04 / Day 3 | Address character 2-4 n-gram TF-IDF vectorizer singleton fitted once at startup | PARTIALLY MET | `app/features/address.py`; direct check: analyzer `char`, ngram `(2,4)`, fitted vocabulary present | Singleton is module-level per process. No explicit pre-fork loading or worker lifecycle guarantee proves "never re-initialized across worker forks." |
| M04 / Day 3 | 1,000-extraction p99 latency under target <8.5ms | PARTIALLY MET | `eval/latency_report.md`; `tests/test_feature_latency.py`; current p99 reported 1.9140ms | Numeric latency passes. Report/test text still uses looser `<15ms container / <10ms bare-metal` budget, not the checkpoint target `<8.5ms`. |
| M05 / Day 4 | XGBoost model training with train-only CV and no validation leakage | COMPLIANT | `scripts/train_model.py`; `models/xgboost_rto_v1.manifest.json`; `tests/test_model_performance.py` | `val.csv` is loaded in the script but used after training/calibration for evaluation only. |
| M06 / Day 4 | Probability calibration strictly on internal train split | COMPLIANT | `scripts/train_model.py`; `eval/calibration_report.md` | Uses Platt/sigmoid via `CalibratedClassifierCV` on `calibration_fold`; acceptable under Platt/isotonic criterion. |
| M06 / Day 4 | Calibration and fallback gates documented, ECE/Brier reported | COMPLIANT | `eval/calibration_report.md`; `docs/threshold_gate_resolution.md` | ECE 0.0145 passes explicit `<0.08`; Brier 0.0216 reported. Brier threshold is intentionally not invented. |
| M06 / Day 4 | No ad-hoc probability shifting toward 0.5 for `is_novel_pincode` | COMPLIANT | Code search across `app`, `scripts`, `tests`, `eval`, `docs`, `config`; `scripts/train_model.py` | No serving or training probability-shift code found. |
| M06 / Day 4 | SHAP engine returns exactly top-3 ranked features in JSON-serializable form | PARTIALLY MET | `app/ml/shap_engine.py`; `tests/test_model_performance.py` | Returns a Python list of three dicts sorted by absolute impact. It is JSON-serializable, but not explicitly serialized JSON. |
| M06 / Day 4 | Drift-feature model sensitivity | PARTIALLY MET | `eval/calibration_report.md` | Reported SHAP weights for `is_novel_pincode` and `is_flash_sale_cart_value` are both 0.0000. The model is not learning these drift features. |
| M07 / Day 5 | Cost engine implements high-risk canceled branch with zero freight loss | COMPLIANT | `app/ml/costs.py`; `tests/test_threshold_optimizer.py` | `cost_tp_h_abandoned()` returns 0; `cost_tp_h()` applies gamma weighting correctly. |
| M08 / Day 5 | Closed-form breakeven ratios match benchmarks | COMPLIANT | `eval/breakeven_ratios.md`; direct calculation | Medium ratio 1.700; High ratio 1.661. |
| M09 / Day 5 | 2D grid sweep over `(t_low, t_high)` on `val.csv` | COMPLIANT | `scripts/optimize_thresholds.py`; `eval/breakeven_ratios.md` | Sweep ranges match plan: `t_low` 0.15-0.50, `t_high` `t_low+0.05`-0.85, step 0.025. |
| M10 / Day 5 | Bootstrap variance logged and thresholds frozen | PARTIALLY MET | `eval/threshold_stability.md`; `config/thresholds.json` | Thresholds frozen at `t_low=0.500`, `t_high=0.750`. Stability report is WARN: only 5 bootstraps and wide threshold movement. |

## Deep-Dive Technical and Methodological Findings

### Data Leakage and Statistical Discipline

Finding D1 - No direct split leakage found.  
The generator uses explicit split seeds: train=101, val=202, heldout=303.
Direct checks confirm row counts train=5000, val=750, heldout=1250 and ID
overlaps of 0 for train/val, train/heldout, and val/heldout.

Finding D2 - Target encodings are train-only.  
`compute_historical_rates(train_df)` is called after generating train and before
attaching rates to all splits. Tests guard against passing validation or
heldout data into rate construction. This satisfies the key isolation
requirement for target-encoded pincode/category features.

Finding D3 - Validation positive-class count is statistically thin.  
`data/generation_report.md` records val RTO=1 count as 110. This is above zero
and within distribution tolerance, but weak for stable threshold optimization.
The Day 5 bootstrap report correctly flags this. This is a warning, not a
leakage finding.

Finding D4 - Model training and calibration avoid validation leakage.  
`scripts/train_model.py` uses `train_test_split` on `train.csv`, tunes XGBoost
with `GridSearchCV` on the fit fold, and calibrates with `CalibratedClassifierCV`
on the internal calibration fold. `val.csv` is used afterward for out-of-sample
metrics. This is methodologically correct.

Finding D5 - Drift feature learning is not effective.  
The calibration report records marginal SHAP weights of 0.0000 for both
`is_novel_pincode` and `is_flash_sale_cart_value`. This is expected because
train and val have no positive drift rows by design, but it means the model has
no learned response to the very shift that heldout is supposed to test. The
code also correctly avoids artificial probability shifting, so there is no
serving-time compensating mechanism. This must be explicitly accepted as a
known model limitation or addressed with a train-only synthetic drift probe
strategy that does not leak heldout labels.

### Financial Math and Optimization Integrity

Finding F1 - High-risk canceled branch is correct.  
The high-risk true-positive branch is:

`gamma_h * (v + rho * c_rto) + (1 - gamma_h) * 0`

With defaults this equals `0.45 * (15 + 0.10 * 150) = 13.5`. The abandoned
branch itself is a literal zero and does not scale with `c_rto`.

Finding F2 - Breakeven ratios match theory.  
Direct calculation and `eval/breakeven_ratios.md` match the required
benchmarks: Medium=1.700, High=1.661. Empirical ratios at frozen thresholds
also pass: Medium=2.000, High=13.000.

Finding F3 - Grid search is implemented on validation probabilities.  
`scripts/optimize_thresholds.py` loads the calibrated model, scores `val.csv`,
then sweeps the 2D threshold grid. This is the correct Day 5 optimization
surface. Heldout data is not used.

Finding F4 - Threshold stability is a material risk.  
The stability report uses only 5 bootstrap resamples and records wide movement:
`t_low` ranges from 0.300 to 0.500 and `t_high` ranges from 0.400 to 0.800.
The artifact honestly marks `Status: WARN` and freezes full-val thresholds.
This is acceptable for conditional progression, not for clean checkpoint
sign-off.

Finding F5 - Fallback branch in optimizer can violate the original grid shape.  
If no threshold pair satisfies breakeven constraints, the optimizer collapses
M-tier with `t_low = t_high`. That violates the original search constraint
`t_high >= t_low + 0.05`. This branch did not determine the current frozen
thresholds, but it is a latent methodological risk and should be guarded.

### Performance, Latency and Architecture Cleanliness

Finding P1 - Health endpoint checks real dependencies.  
`/health` uses async Postgres `SELECT 1`, Redis `PING`, and an AMQP connection
to RabbitMQ. The live endpoint returned:

`{"overall":"ok","dependencies":{"postgres":{"status":"ok"},"redis":{"status":"ok"},"rabbitmq":{"status":"ok"}}}`

Finding P2 - Broker topology is resolved.  
RabbitMQ is the Celery broker and Redis is the result backend. This is
documented in ADR-001 and reflected in runtime settings.

Finding P3 - Address TF-IDF implementation is fast and correctly configured.  
The vectorizer is `TfidfVectorizer(analyzer='char', ngram_range=(2,4))`.
The latest latency report shows p99=1.9140ms over 1,000 extractions, well under
the checkpoint target.

Finding P4 - Singleton lifecycle is not fully proven across workers.  
The vectorizer is module-level and fitted at import time. That prevents
per-request refits. It does not, by itself, prove a single fit across forked
worker processes unless import/preload behavior is controlled. This is an
architecture cleanliness gap.

Finding P5 - Local host Python environment is not test-ready.  
Running `python -m pytest ...` on the host failed at collection due to missing
`pytest_asyncio`. The container environment is test-ready and passed. This is a
developer-experience warning, not a product runtime blocker.

## Prioritized Punch List

1. Blocking before clean Checkpoint 1 sign-off: resolve or formally accept the
   zero drift-feature sensitivity. The current model reports 0.0000 SHAP weight
   for `is_novel_pincode` and `is_flash_sale_cart_value`; this undermines the
   planned heldout shift test.

2. Blocking before clean Checkpoint 1 sign-off: strengthen threshold stability
   evidence. Increase bootstrap resamples from 5 to at least 100, report
   confidence intervals for `t_low`, `t_high`, and net saved, and define an
   explicit stability acceptance rule.

3. High priority: update `eval/latency_report.md` and
   `tests/test_feature_latency.py` to enforce the checkpoint target `<8.5ms`
   instead of documenting a looser `<15ms container / <10ms bare-metal` target.

4. High priority: document and enforce the feature-vectorizer process lifecycle.
   Decide whether startup preloading is required; otherwise state that the
   singleton is per worker process and ensure no request path can refit it.

5. Medium priority: remove or hard-fail the optimizer fallback that sets
   `t_low = t_high`, or document it as a separate degenerate policy outside the
   planned 2D grid. The current selected thresholds are valid, but the fallback
   is methodologically inconsistent with the plan.

6. Medium priority: make `shap_engine.explain_prediction()` return an explicitly
   JSON-compatible API contract, including exactly three entries, deterministic
   ordering, and stable numeric field names. The current list-of-dicts is
   serializable but not explicitly a JSON response object.

7. Medium priority: either populate a working local `.venv` or document that
   all verification must run inside Docker. Host collection currently fails
   because `pytest_asyncio` is missing.

8. Low priority: remove the obsolete `version` key from `docker-compose.yml` to
   eliminate Docker Compose warnings.

## Gate Verdict Detail

CONDITIONAL GO to Day 6 is justified because no direct data leakage,
mathematical cost error, broker ambiguity, or health-check failure remains in
the verified Checkpoint 1 path. The condition is that the team must not treat
the Day 5 threshold and Day 4 drift behavior as final-quality evidence. They
are sufficient to continue integration work, but not sufficient for final
risk-engine sign-off without the punch-list items above.
