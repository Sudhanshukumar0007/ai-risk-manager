# Day 04 — Model Training & Calibration

## Status

- Phase status: `COMPLETE`
- Checkpoint impact: `none` (Checkpoint 1 = end of Day 5)
- Date/session: 2026-08-25
- Agent/session identifier: Antigravity

## 1. Plan Tasks

| Plan Step | Requirement | Status |
|---|---|---|
| 1 | Train base XGBoost (`xgboost_rto_v1.bin`) | DONE |
| 2 | Hyperparameter tuning w/ grid search | DONE |
| 3 | Apply isotonic regression for calibration | DONE |
| 4 | Dump `eval/calibration_report.md` | DONE |
| 5 | Prepare SHAP explainer stub (`app/ml/shap_engine.py`) | DONE |
| 6 | Build tests for deterministic results | DONE |

## 2. Repository State Before Work

### Relevant files
- `scripts/train_model.py`
- `app/ml/shap_engine.py`
- `tests/test_model_performance.py`

### Existing implementation
- Training script improperly loaded and tuned on `heldout.csv`.
- Drift reporting artificially reduced drift values instead of using an orthogonal probe.
- Output artifacts were missing the `xgboost_rto_v1.base.bin` required for SHAP.
- Model manifest generation was not implemented.

### Existing tests
- Tests in `test_model_performance.py` created leftover files and did not check for leakage automatically.

### Known failures
- Audit findings A-D4-001 to A-D4-004 highlighted significant test leakage and architectural gaps.

## 3. Pre-Implementation Assessment

### What was already correct
- XGBoost configuration was generally correct.
- Isotonic regression was properly used for calibration.

### What was missing
- Protection against `heldout.csv` leakage.
- Synthetic orthogonal probe for drift evaluation.
- Serialization of the base model `.base.bin`.
- Model manifest `.manifest.json`.
- AST-based leakage detection in tests.

### Risks identified
- **R1:** Tuning on `heldout.csv` would violate the primary integrity rule of the project.
- **R2:** Missing the base model would crash SHAP in production since `CalibratedClassifierCV` isn't compatible with `shap.TreeExplainer`.
- **R3:** Hardcoded file paths in tests could lead to race conditions or leftover state.

### Recommended implementation order
1. Fix `train_model.py` to remove `heldout.csv` references.
2. Add synthetic drift probe to `train_model.py`.
3. Save `.base.bin` and `.manifest.json`.
4. Fix `app/ml/shap_engine.py` to load `.base.bin`.
5. Add AST leakage check to `test_model_performance.py`.

## 4. Implementation Performed

### Changes
- Updated `scripts/train_model.py`:
  - Removed `heldout.csv` loading.
  - Implemented synthetic data generation using Numpy for evaluating `is_novel_pincode` vs. base rate.
  - Saved `xgboost_rto_v1.base.bin` (base XGBoost model).
  - Saved `xgboost_rto_v1.manifest.json`.
  - Added CLI arguments for data and model directories.
- Updated `app/ml/shap_engine.py` to load `.base.bin`.
- Updated `tests/test_model_performance.py` to:
  - Read `train_model.py` via AST to assert `heldout.csv` is not present.
  - Use `pytest` temporary directories (`tmp_path`) for deterministic training reproducibility.

### Files created
- None

### Files modified
- `scripts/train_model.py`
- `app/ml/shap_engine.py`
- `tests/test_model_performance.py`

### Files deleted
- None

### Configuration/service changes
- None

## 5. Validation

### Commands run
```text
docker compose exec api python scripts/train_model.py
docker compose exec api pytest tests/test_model_performance.py -v
```

### Test results
- 8/8 PASSED across model performance tests.

### Metrics/results
- Validation Brier Score: 0.0216
- Validation ECE: 0.0145
- No leakage detected by AST check.
- SHAP engine works with `.base.bin`.

## 6. Plan Compliance Review

### Fully aligned
- Model evaluation and tuning strictly avoid `heldout.csv`.
- Drift reporting is purely diagnostic.
- Training artifacts match expected paths and formats.

### Deviations
- None

### Why deviations were necessary
- N/A

### Impact on later phases
- Day 5 will evaluate the frozen model properly on `heldout.csv`.

## 7. Problems Encountered
- **Problem:** `test_no_heldout_leakage_in_train_model` was initially tricky to implement robustly.
- **Root cause:** String matching is fragile.
- **Fix:** Used Python's `ast` module to scan for the literal string `"heldout.csv"`, which is much more reliable.

## 8. Decisions
- **Decision:** Synthetic drift probe generates a DataFrame orthogonal to real data.
- **Reason:** Ensuring drift reporting doesn't accidentally affect real test predictions.

## 9. Suggestions for Next Session
- Move to Day 5, the model evaluation on the held-out set. Ensure you do not change thresholds on the held-out set.

## 10. Next Required Action

The next agent should:
1. Review Day 5 worklog and implementation plan.
2. Proceed to Day 5 (End of Checkpoint 1).

## 11. Completion Gate

- Acceptance test: PASS
- Deliverables present: YES
- Blocking issues: NONE
- Phase complete: YES
