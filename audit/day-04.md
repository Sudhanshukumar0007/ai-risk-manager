# Day 04 Audit — Model Training, Calibration & SHAP Explainability

Date/session: 2026-08-25
Auditor: Codex GPT-5
Scope: Day 04 implementation only, reviewed against `instructions .md`, `Implementation_plan.md`, `docs/worklogs/day-04.md`, `scripts/train_model.py`, `app/ml/shap_engine.py`, `tests/test_model_performance.py`, and generated Day 04 artifacts.

## Audit Verdict

Day 04 is partially implemented but not clean. The core training flow correctly avoids using `val.csv` for tuning and calibration, and the report shows strong validation calibration metrics. However, the implementation reads `heldout.csv` during Day 04 for drift diagnostics, which violates the project's held-out isolation rule. This is a blocking evaluation-integrity issue and should be remediated before Day 5/Day 10 claims rely on the current model artifacts.

The Day 04 worklog is also not compliant with the mandatory template, and the acceptance test does not enforce the strongest no-leakage claim from the plan. The user has indicated Docker/manual tests were run; this audit accepts that evidence for package availability and focuses on plan compliance and implementation risk.

## Governing Workflow Check

| Workflow Requirement | Status | Evidence |
|---|---|---|
| Read governing instructions | PARTIAL | Worklog references corrected plan decisions but does not follow the required handoff format. |
| Read implementation plan | PASS | Training uses fit/calibration split from `train.csv`, matching the leakage-fixed Day 4 plan. |
| Resolve missing KS/Brier thresholds | PASS WITH DOC ISSUE | `docs/threshold_gate_resolution.md` records fallback gates and keeps ECE `< 0.08`. |
| Preserve held-out isolation | FAIL | `scripts/train_model.py` reads `data/heldout.csv` during Day 04. |
| Validate current phase | PASS BY USER-ACCEPTED DOCKER EVIDENCE | Local non-Docker collection cannot run because system Python lacks `shap`/`xgboost`; user stated Docker tests were manually run. |
| Worklog uses mandatory template | FAIL | `docs/worklogs/day-04.md` lacks Status, Plan Tasks, Repository State, Validation, Completion Gate, Blocking Issues, and Do Not Repeat sections. |

## Plan Alignment

| Day 04 Plan Step | Audit Status | Notes |
|---|---|---|
| Split `train.csv` into fit and calibration folds | PASS | `train_test_split(... test_size=0.2, stratify=...)` is used. |
| Tune XGBoost inside training data only | PASS | `GridSearchCV` runs on `X_fit`, not `val.csv`. |
| Calibrate on training-side calibration fold | PASS | `CalibratedClassifierCV(method='sigmoid', cv='prefit')` fits on `X_calib`. |
| Attach SHAP explainer and top-3 attribution | PASS WITH TECHNICAL RISK | `app/ml/shap_engine.py` returns top 3 impacts, but calibrated-model handling may be brittle across scikit-learn versions. |
| Evaluate calibration on `val.csv` first | PASS | Report evaluates Brier/ECE on `val.csv`. |
| Resolve missing thresholds without inventing values | PASS | ECE is enforced; missing KS/Brier scalar gates are replaced by documented fallback gates. |
| Do not mutate probabilities for drift | PASS | No post-hoc shift-to-0.5 logic found. |
| Report drift diagnostic without contaminating heldout | FAIL | Day 04 uses `heldout.csv` before final evaluation. |

## Validation Evidence

Manual/Docker evidence accepted per user instruction:

```text
Day 04 tests were run manually inside Docker.
```

Local session limitation:

```text
python -m pytest tests\test_feature_pipeline.py tests\test_feature_latency.py tests\test_model_performance.py -v
```

failed at collection under system Python because `shap` is not installed. Docker was unavailable because the daemon was not running.

Generated report evidence:

```text
Brier Score: 0.0216
ECE: 0.0145
Mean absolute SHAP value for is_novel_pincode: 0.0000
Mean absolute SHAP value for is_flash_sale_cart_value: 0.0000
```

## Findings

### A-D4-001 — Day 04 Reads `heldout.csv` Before Final Evaluation

Severity: Blocking

Evidence:

- `scripts/train_model.py:121` reads `data/heldout.csv`.
- `scripts/train_model.py:122` builds `shift_subset` from heldout rows.
- `scripts/train_model.py:126` computes SHAP values on that heldout subset.
- `eval/calibration_report.md` includes a drift diagnostic computed from heldout.

Risk:

The implementation breaks the held-out isolation contract. The plan reserves `heldout.csv` for final Day 10 evaluation with frozen thresholds. Reading it during model training/reporting can influence debugging, remediation, feature decisions, and narrative claims before the final evaluation.

Recommendation:

Remove all Day 04 access to `heldout.csv`. For Day 04, validate drift-feature behavior using a synthetic probe set generated in memory, a train-side calibration subset with manually toggled drift flags, or defer the drift diagnostic entirely to Day 10 as the plan later requires.

### A-D4-002 — Drift Diagnostic Claims Awareness But Reports Zero Signal

Severity: Medium

Evidence:

- `eval/calibration_report.md` reports `0.0000` mean absolute SHAP value for both `is_novel_pincode` and `is_flash_sale_cart_value`.
- `docs/worklogs/day-04.md` says this proves the model is "aware" of novelty.

Risk:

Zero SHAP contribution is evidence that the trained model did not use those fields on the sampled rows, not evidence of awareness. The report's conclusion is not supported by its own metric.

Recommendation:

Change the report language to diagnostic-only and explicitly state when drift features have zero measured impact. If awareness is required, investigate whether the features appear in training with nonzero variance; currently train/val have no drift rows, so the model cannot learn their effect from training data.

### A-D4-003 — Acceptance Test Does Not Prove No-Leakage Model Process

Severity: High

Evidence:

- `tests/test_model_performance.py` checks split `order_id` overlap, but does not prove `val.csv` was absent from tuning/calibration or that `heldout.csv` was absent from Day 04.
- The plan's Day 4 acceptance test asks for a leakage regression around validation row hashes never appearing in training-fold checkpoints.

Risk:

A future regression could read validation or heldout during training while still passing ID-overlap checks. Evaluation metrics would look valid while the model-selection process is contaminated.

Recommendation:

Instrument `scripts/train_model.py` to emit a training manifest containing input files, split hashes, fit/calibration row hashes, best params, and random seeds. Add a test that fails if `val.csv` or `heldout.csv` is read before the evaluation-only step, except for the permitted `val.csv` metric calculation.

### A-D4-004 — Day 04 Worklog Is Not Handoff-Compliant

Severity: Medium

Evidence:

- `docs/worklogs/day-04.md` is a short narrative with seven sections.
- It omits the required template sections including Status, Plan Tasks, Repository State Before Work, Validation commands/results, Plan Compliance Review, Completion Gate, Blocking Issues, and Do Not Repeat.

Risk:

The next agent cannot reliably determine what was tested, what failed, which files changed, or whether Day 04 is safe to build on. This undermines checkpoint auditability.

Recommendation:

Rewrite `docs/worklogs/day-04.md` into the required template and include the heldout access issue explicitly under deviations/blocking issues.

### A-D4-005 — Deterministic Training Test Is Expensive And Mutates The Shared Model Artifact

Severity: Medium

Evidence:

- `tests/test_model_performance.py:167` runs `scripts/train_model.py`.
- `tests/test_model_performance.py:171` runs it a second time.
- Both runs write to `models/xgboost_rto_v1.bin` and `eval/calibration_report.md`.

Risk:

The test is slow, repeatedly mutates tracked deliverables, and can mask whether the committed model artifact is the one actually evaluated. It also makes routine test runs perform full model training as a side effect.

Recommendation:

Run deterministic training in a temporary output directory or make `train_model.py` accept `--model-dir` and `--eval-dir`. Keep artifact-producing training separate from ordinary model-performance tests.

### A-D4-006 — SHAP Engine Depends On Brittle Access To The Calibrated Base Estimator

Severity: Low to Medium

Evidence:

- `app/ml/shap_engine.py` assumes a loaded `CalibratedClassifierCV` exposes `.estimator`; this is version-sensitive and tied to `cv='prefit'`.
- The saved object is a calibrated classifier, while SHAP is initialized against the uncalibrated base XGBoost estimator.

Risk:

Attribution may silently diverge from calibrated probabilities. Future library upgrades can break SHAP initialization or return attributions for the wrong internal estimator.

Recommendation:

Persist the base fitted XGBoost model separately from the calibrated wrapper, or persist a small model bundle with explicit `base_model`, `calibrated_model`, `feature_cols`, package versions, and training manifest.

## Non-Issues Confirmed

- Hyperparameter tuning is performed on the fit fold, not `val.csv`.
- Calibration is performed on the train-side calibration fold, not `val.csv`.
- No post-calibration drift probability mutation was found.
- `models/xgboost_rto_v1.bin`, `app/ml/shap_engine.py`, `eval/calibration_report.md`, and `docs/threshold_gate_resolution.md` exist.
- ECE reported in `eval/calibration_report.md` is under the valid `< 0.08` threshold.

## Proceed / Stop Decision

Do not treat Day 04 as cleanly complete until A-D4-001 is fixed. The project can continue only if the current heldout-derived diagnostics are removed/regenerated and the worklog records the remediation. Day 5 threshold work should not rely on any conclusion learned from heldout.

## Remediation Status

Status: OPEN / BLOCKING

Blocking item:

1. Remove Day 04 use of `heldout.csv` and regenerate `eval/calibration_report.md`.

Required follow-ups:

1. Strengthen leakage tests around file access and row hashes.
2. Rewrite Day 04 worklog into the mandatory template.
3. Adjust drift diagnostic language and defer heldout shift analysis to Day 10.
