import os
import pandas as pd
import numpy as np
import xgboost as xgb
import joblib
import argparse
import json
import hashlib
from sklearn.model_selection import train_test_split, GridSearchCV
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import brier_score_loss, log_loss

# Feature columns
FEATURE_COLS = [
    "pincode_historical_rto_rate",
    "customer_past_rto_count",
    "category_baseline_rto_rate",
    "cart_value_category_std_dev",
    "item_quantity_anomaly_score",
    "is_night_order",
    "phone_order_velocity_7d",
    "device_account_reuse_count",
    "account_age_days",
    "address_char_length",
    "address_tfidf_ambiguity_score",
    "hub_distance_km",
    "is_cod_selected",
    "is_novel_pincode",
    "is_flash_sale_cart_value"
]
TARGET_COL = "is_rto"

def compute_ece(y_true, y_prob, n_bins=10):
    """Computes Expected Calibration Error."""
    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    for i in range(n_bins):
        bin_lower = bin_edges[i]
        bin_upper = bin_edges[i+1]
        in_bin = (y_prob >= bin_lower) & (y_prob < bin_upper)
        if np.any(in_bin):
            prob_mean = np.mean(y_prob[in_bin])
            true_mean = np.mean(y_true[in_bin])
            ece += np.abs(prob_mean - true_mean) * np.sum(in_bin) / len(y_true)
    return ece

def get_hash(df):
    return hashlib.md5(pd.util.hash_pandas_object(df, index=True).values).hexdigest()

def main():
    parser = argparse.ArgumentParser(description="Train RTO Model")
    parser.add_argument("--model-dir", type=str, default=None, help="Output directory for models")
    parser.add_argument("--eval-dir", type=str, default=None, help="Output directory for evaluations")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(base_dir, "data")
    models_dir = args.model_dir if args.model_dir else os.path.join(base_dir, "models")
    eval_dir = args.eval_dir if args.eval_dir else os.path.join(base_dir, "eval")

    os.makedirs(models_dir, exist_ok=True)
    os.makedirs(eval_dir, exist_ok=True)

    # 1. Load Data
    train_df = pd.read_csv(os.path.join(data_dir, "train.csv"))
    val_df = pd.read_csv(os.path.join(data_dir, "val.csv"))

    # 2. Split train.csv into fit and calibration folds (80/20)
    X_train_full = train_df[FEATURE_COLS]
    y_train_full = train_df[TARGET_COL]

    X_fit, X_calib, y_fit, y_calib = train_test_split(
        X_train_full, y_train_full, test_size=0.2, random_state=42, stratify=y_train_full
    )

    # 3. Train and tune XGBoost on fit fold
    print("Training and tuning XGBoost on fit fold...")
    base_clf = xgb.XGBClassifier(
        objective="binary:logistic",
        random_state=42,
        eval_metric="logloss",
        n_jobs=1
    )

    param_grid = {
        'max_depth': [3, 4],
        'learning_rate': [0.05, 0.1],
        'n_estimators': [50, 100]
    }

    grid_search = GridSearchCV(
        estimator=base_clf,
        param_grid=param_grid,
        scoring="neg_log_loss",
        cv=3,
        n_jobs=1
    )
    grid_search.fit(X_fit, y_fit)
    
    best_clf = grid_search.best_estimator_
    print(f"Best params: {grid_search.best_params_}")

    # 4. Calibrate probabilities on calibration fold
    print("Calibrating probabilities on calibration fold...")
    calibrated_clf = CalibratedClassifierCV(
        estimator=best_clf, 
        method='sigmoid', # Sigmoid (Platt scaling) is used due to small calibration set size (~1000 rows, ~240 positives)
        cv='prefit'
    )
    calibrated_clf.fit(X_calib, y_calib)

    # 5. Save the models
    model_path = os.path.join(models_dir, "xgboost_rto_v1.bin")
    joblib.dump(calibrated_clf, model_path)
    
    base_model_path = os.path.join(models_dir, "xgboost_rto_v1.base.bin")
    joblib.dump(best_clf, base_model_path)
    print(f"Models saved to {models_dir}")
    
    # Save manifest
    manifest = {
        "train_hash": get_hash(train_df),
        "val_hash": get_hash(val_df),
        "fit_hash": get_hash(X_fit),
        "calib_hash": get_hash(X_calib),
        "random_seed": 42,
        "best_params": grid_search.best_params_
    }
    manifest_path = os.path.join(models_dir, "xgboost_rto_v1.manifest.json")
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2)

    # 6. Evaluate on val.csv
    X_val = val_df[FEATURE_COLS]
    y_val = val_df[TARGET_COL]

    y_val_prob = calibrated_clf.predict_proba(X_val)[:, 1]

    brier = brier_score_loss(y_val, y_val_prob)
    ece = compute_ece(y_val, y_val_prob)

    print(f"Validation Brier Score: {brier:.4f}")
    print(f"Validation ECE: {ece:.4f}")

    # 6.5 SHAP Diagnostic for Drift Features (Issue #2)
    # We will compute the average absolute SHAP value for the drift features on a synthetic probe
    # generated from the fit_fold (avoiding heldout data leakage).
    probe_df = X_fit.sample(min(100, len(X_fit)), random_state=42).copy()
    probe_df["is_novel_pincode"] = 1
    probe_df["is_flash_sale_cart_value"] = 1
    
    import shap
    explainer = shap.TreeExplainer(best_clf)
    shap_vals = explainer.shap_values(probe_df[FEATURE_COLS])
    
    # Feature indices
    idx_novel = FEATURE_COLS.index("is_novel_pincode")
    idx_flash = FEATURE_COLS.index("is_flash_sale_cart_value")
    
    mean_shap_novel = np.mean(np.abs(shap_vals[:, idx_novel]))
    mean_shap_flash = np.mean(np.abs(shap_vals[:, idx_flash]))

    # 7. Write calibration report
    report_path = os.path.join(eval_dir, "calibration_report.md")
    with open(report_path, "w") as f:
        f.write("# Day 04: Calibration Report\n\n")
        f.write("## Methodology\n")
        f.write("- Dataset `train.csv` was split internally into an 80% `fit_fold` and a 20% `calibration_fold`.\n")
        f.write("- XGBoost hyperparameters were tuned strictly on `fit_fold` using 3-fold CV.\n")
        f.write("- Probabilities were calibrated using `CalibratedClassifierCV` (sigmoid / Platt scaling) on `calibration_fold` due to the small size of the calibration set (~1000 rows, ~240 positive examples).\n")
        f.write("- Final metrics evaluated purely on isolated out-of-sample `val.csv`.\n\n")
        
        f.write("## Metrics on `val.csv`\n")
        f.write(f"- **Brier Score:** {brier:.4f}\n")
        f.write(f"- **Expected Calibration Error (ECE):** {ece:.4f}\n\n")

        f.write("## Drift Diagnostic (Issue #2)\n")
        f.write("As per the requirements, we report the marginal SHAP weight of the two drift features on a synthetic probe sampled from the fit_fold (with drift indicators toggled on) to confirm the model allocates weight to novelty, without leaking heldout data.\n")
        f.write(f"- **Marginal SHAP weight for `is_novel_pincode`:** {mean_shap_novel:.4f}\n")
        f.write(f"- **Marginal SHAP weight for `is_flash_sale_cart_value`:** {mean_shap_flash:.4f}\n\n")

        f.write("## Gate Resolution\n")
        f.write("Missing scalar thresholds for KS-test and Brier score (Issue #8) were replaced with strict systemic fallback gates (base-rate stability, zero ID overlap, dataset isolation). See `docs/threshold_gate_resolution.md` for details.\n")
        
    print(f"Calibration report saved to {report_path}")

if __name__ == "__main__":
    main()
