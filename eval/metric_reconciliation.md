# Metric Reconciliation & Calibration Verification

## Context
During secondary validation, an initial test run observed a divergent Net Saved figure (₹13,874) compared to the headline production evaluation (₹15,611), despite using identical frozen thresholds (`[0.50, 0.75]`). An investigation was conducted to isolate and document the mechanism.

## Point of Divergence
The discrepancy originated in `scripts/run_evaluations.py`, specifically lines 300-302 (prior to the fix):

```python
    model_path = os.path.join(base_dir, "models", "xgboost_rto_v1.base.bin")
    if not os.path.exists(model_path):
        model_path = os.path.join(base_dir, "models", "xgboost_rto_v1.bin")
    model = joblib.load(model_path)
```

**Technical Explanation:**
The production evaluation (`evaluate_heldout.py`) strictly loaded the calibrated production model (`xgboost_rto_v1.bin`). 

In the secondary test script, fallback logic was included to load `xgboost_rto_v1.base.bin` if present. The `.base.bin` file is the raw, uncalibrated tree ensemble required specifically by SHAP `TreeExplainer` (which cannot directly parse calibrated wrapper objects). By loading the base model globally in `main()`, the test script evaluated the metrics using uncalibrated margins rather than the calibrated probabilities from the production model.

This difference in raw output probabilities caused fewer orders to cross the intervention threshold, lowering recall and reducing the calculated net saved.

## Resolution
The calibrated model was reaffirmed as the sole production artifact:
1. `scripts/run_evaluations.py` was corrected to unconditionally load the calibrated production model (`xgboost_rto_v1.bin`) for all routing, economic, and confusion matrix calculations.
2. The SHAP tree-attribution step was isolated to load `xgboost_rto_v1.base.bin` locally solely for tree traversal.

## Verified Numbers
Re-evaluating with the calibrated production model confirms the exact headline figures:

- **Net Saved (full heldout)**: ₹15,611
- **Precision**: 87.1% (TP=148, FP=22)
- **Recall**: 80.4% (TP=148, FN=36)
- **Net Saved (shifted subset only)**: ₹2,507

All evaluation reports (`confusion_matrix.md`, `baseline_comparison.md`, `drift_attribution.md`, `bootstrap_ci.md`, `sensitivity_analysis.md`) reflect these verified production metrics.
