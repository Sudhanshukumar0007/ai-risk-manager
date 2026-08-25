# Day 04 Suggestions

## Priority Fixes

1. Remove all `heldout.csv` access from `scripts/train_model.py` and regenerate `eval/calibration_report.md`. Heldout must remain untouched until Day 10.

2. Replace the Day 04 drift diagnostic with a non-heldout alternative:
   - use a synthetic in-memory probe row with drift flags toggled;
   - use train-side rows only and label the result as a sensitivity probe;
   - or defer the diagnostic entirely to Day 10.

3. Rewrite `docs/worklogs/day-04.md` into the mandatory template from `instructions .md`. Include commands run, Docker/manual validation evidence, files created, deviations, blocking issues, and next required action.

4. Add a training manifest. Record exact input files, split hashes, fit/calibration row IDs or hashes, random seeds, best parameters, package versions, model hash, and report hash.

5. Strengthen leakage tests. They should fail if `val.csv` is read before the evaluation step or if `heldout.csv` is read anywhere in Day 04.

## Suggested Test Additions

```text
pytest tests/test_model_performance.py -v
```

Improve the tests so they verify:

- `GridSearchCV.fit()` receives only train-side fit rows;
- `CalibratedClassifierCV.fit()` receives only train-side calibration rows;
- `val.csv` is used only after model fitting/calibration are complete;
- `heldout.csv` is never read by `scripts/train_model.py`;
- deterministic retraining writes outputs to a temporary directory, not the shared `models/` and `eval/` deliverables.

## Suggested Artifact Structure

Create a small model bundle instead of a lone pickle:

```text
models/
  xgboost_rto_v1.bin
  xgboost_rto_v1.base.bin
  xgboost_rto_v1.manifest.json
```

The manifest should include `FEATURE_COLS`, training data hashes, selected hyperparameters, calibration method, metrics, and dependency versions.

## Proceeding Guidance

Do not start Day 5 threshold optimization from the current Day 04 state until the heldout contamination is removed and the calibration report is regenerated from `train.csv` plus `val.csv` only.
