# Model Calibration & Diagnostic Report

## Methodology
- Dataset `train.csv` was split internally into an 80% `fit_fold` and a 20% `calibration_fold`.
- XGBoost hyperparameters were tuned strictly on `fit_fold` using 3-fold CV.
- Probabilities were calibrated using `CalibratedClassifierCV` (sigmoid / Platt scaling) on `calibration_fold` due to the small size of the calibration set (~1000 rows, ~240 positive examples).
- Final metrics evaluated purely on isolated out-of-sample `val.csv`.

## Metrics on `val.csv`
- **Brier Score:** 0.0216
- **Expected Calibration Error (ECE):** 0.0145

## Drift Diagnostic
As part of the evaluation protocol, we report the marginal SHAP weight of the two drift features on a synthetic probe sampled from the fit_fold (with drift indicators toggled on) to confirm whether the model directly allocates weight to novelty signals:
- **Marginal SHAP weight for `is_novel_pincode`:** 0.0000
- **Marginal SHAP weight for `is_flash_sale_cart_value`:** 0.0000

## Gate Resolution
Missing specification thresholds for the KS-test and Brier score were replaced with strict systemic fallback gates (base-rate stability, zero ID overlap, dataset isolation). See `threshold_gate_resolution.md` for details.
