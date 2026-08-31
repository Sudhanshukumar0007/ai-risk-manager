# Metric Reconciliation (Day 10 vs Day 11)

## Issue
Day 11's evaluation script reported a lower Net Saved (₹13,874) and different Precision/Recall metrics compared to the original Day 10 `final_report.md` (Net Saved: ₹15,611), despite using the same frozen thresholds (`[0.50, 0.75]`).

## Point of Divergence
The discrepancy originates in `scripts/run_day11_evaluations.py`, specifically lines 300-302 (prior to the fix):

```python
    model_path = os.path.join(base_dir, "models", "xgboost_rto_v1.base.bin")
    if not os.path.exists(model_path):
        model_path = os.path.join(base_dir, "models", "xgboost_rto_v1.bin")
    model = joblib.load(model_path)
```

**Explanation of the Bug:**
The Day 10 script (`evaluate_heldout.py`) correctly loaded the calibrated production model (`xgboost_rto_v1.bin`). 

In Day 11, the `run_day11_evaluations.py` script was written to fall back to `xgboost_rto_v1.base.bin` if it existed. The `.base.bin` file is the raw, uncalibrated `XGBClassifier` that was saved to disk earlier in the project. The Day 11 author likely included this logic because the SHAP `TreeExplainer` (used in Task 4) crashes when fed a `CalibratedClassifierCV` wrapper and requires the base tree model. However, by changing the model path globally in `main()`, the Day 11 script accidentally evaluated the entire test suite (Confusion Matrix, Baselines, CI, Sensitivity) using the uncalibrated probabilities from the base model, rather than the calibrated probabilities from the production model.

This shift in predicted probabilities completely explains why fewer cases crossed the threshold (lowering Recall) and changed the Net Saved calculation.

## Resolution
The bug was in the Day 11 script, not the Day 10 original evaluation. 
1. `scripts/run_day11_evaluations.py` was corrected to unconditionally load the calibrated production model (`xgboost_rto_v1.bin`) for all metrics and routing decisions.
2. The SHAP analysis step (Task 4) was updated to locally load `xgboost_rto_v1.base.bin` exclusively for the `TreeExplainer`, leaving the actual routing and Net Saved calculations running on the correct calibrated model.

## Corrected Numbers
Re-running the fixed Day 11 script produces the following metrics, which **perfectly match** the original Day 10 `final_report.md`:

- **Net Saved (full heldout)**: ₹15,611
- **Precision**: 87.1% (TP=148, FP=22)
- **Recall**: 80.4% (TP=148, FN=36)
- **Net Saved (shifted subset only)**: ₹2,507

Because Day 10 was correct, **no changes are needed to the project's headline ₹15,611 figure.** All Day 11 evaluation reports (`confusion_matrix.md`, `baseline_comparison.md`, `drift_attribution.md`, `bootstrap_ci.md`, `sensitivity_analysis.md`) have been re-generated to reflect the correct, consistent numbers.
