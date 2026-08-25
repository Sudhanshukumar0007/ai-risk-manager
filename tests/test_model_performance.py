import os
import pytest
import pandas as pd
import numpy as np
import joblib
from sklearn.metrics import precision_recall_curve, auc

from app.ml.shap_engine import explain_prediction

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
MODEL_PATH = os.path.join(BASE_DIR, "models", "xgboost_rto_v1.bin")

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

@pytest.fixture(scope="module")
def data_splits():
    train = pd.read_csv(os.path.join(DATA_DIR, "train.csv"))
    val = pd.read_csv(os.path.join(DATA_DIR, "val.csv"))
    heldout = pd.read_csv(os.path.join(DATA_DIR, "heldout.csv"))
    return train, val, heldout

def test_model_pr_auc_performance(data_splits):
    """Asserts that PR-AUC on the out-of-sample val set is > 0.70."""
    _, val, _ = data_splits
    
    if not os.path.exists(MODEL_PATH):
        pytest.skip("Model not trained yet.")
        
    model = joblib.load(MODEL_PATH)
    
    X_val = val[FEATURE_COLS]
    y_val = val["is_rto"]
    
    y_probs = model.predict_proba(X_val)[:, 1]
    
    precision, recall, _ = precision_recall_curve(y_val, y_probs)
    pr_auc = auc(recall, precision)
    
    print(f"Validation PR-AUC: {pr_auc:.4f}")
    assert pr_auc > 0.70, f"PR-AUC {pr_auc:.4f} is not strictly > 0.70"

def test_model_ece_performance(data_splits):
    """Asserts that ECE on the out-of-sample val set is strictly < 0.08."""
    _, val, _ = data_splits
    
    if not os.path.exists(MODEL_PATH):
        pytest.skip("Model not trained yet.")
        
    model = joblib.load(MODEL_PATH)
    
    X_val = val[FEATURE_COLS]
    y_val = val["is_rto"]
    
    y_probs = model.predict_proba(X_val)[:, 1]
    
    # Simple manual ECE calculation since we don't import netcal or similar
    # Using 10 bins
    bins = np.linspace(0, 1, 11)
    ece = 0.0
    for i in range(10):
        bin_mask = (y_probs >= bins[i]) & (y_probs < bins[i+1])
        if np.sum(bin_mask) > 0:
            bin_conf = np.mean(y_probs[bin_mask])
            bin_acc = np.mean(y_val[bin_mask])
            ece += (np.sum(bin_mask) / len(y_probs)) * np.abs(bin_conf - bin_acc)
            
    print(f"Validation ECE: {ece:.4f}")
    assert ece < 0.08, f"ECE {ece:.4f} is not strictly < 0.08"

def test_shap_engine_valid_json_top_3(data_splits):
    """Asserts SHAP engine returns exactly 3 features as valid Python dicts."""
    _, val, _ = data_splits
    
    if not os.path.exists(MODEL_PATH):
        pytest.skip("Model not trained yet.")
        
    # Pick a random row
    row = val.iloc[0]
    features_dict = row[FEATURE_COLS].to_dict()
    
    result = explain_prediction(features_dict)
    
    assert isinstance(result, list)
    assert len(result) == 3
    
    for item in result:
        assert isinstance(item, dict)
        assert "feature" in item
        assert "impact" in item
        assert item["feature"] in FEATURE_COLS
        assert isinstance(item["impact"], float)

def test_leakage_regression_no_overlap(data_splits):
    """Asserts that there is absolute data isolation (zero ID overlap across splits)."""
    train, val, heldout = data_splits
    
    train_ids = set(train["order_id"])
    val_ids = set(val["order_id"])
    heldout_ids = set(heldout["order_id"])
    
    assert len(train_ids.intersection(val_ids)) == 0, "Leakage detected: train and val overlap"
    assert len(train_ids.intersection(heldout_ids)) == 0, "Leakage detected: train and heldout overlap"
    assert len(val_ids.intersection(heldout_ids)) == 0, "Leakage detected: val and heldout overlap"

def test_fallback_gate_base_rate_stability(data_splits):
    """Asserts that RTO-in-COD rate is within +/-3 percentage points of 24% for all splits."""
    train, val, heldout = data_splits
    
    for split_name, df in [("train", train), ("val", val), ("heldout", heldout)]:
        # Only measure RTO rate for COD orders (base rate target is 24%)
        cod_orders = df[df["is_cod_selected"] == 1]
        
        if len(cod_orders) == 0:
            continue
            
        rate = cod_orders["is_rto"].mean()
        assert abs(rate - 0.24) <= 0.03, f"Base rate {rate:.4f} in {split_name} is outside 24% +/- 3pp"

def test_fallback_gate_covariate_shift(data_splits):
    """
    Asserts that the injected 10% covariate shift is present in heldout.csv 
    and absent from train.csv/val.csv (checking `is_novel_pincode`).
    """
    train, val, heldout = data_splits
    
    # Train and Val should have ~0% novel pincodes
    train_novel_rate = train["is_novel_pincode"].mean()
    val_novel_rate = val["is_novel_pincode"].mean()
    
    assert train_novel_rate < 0.01, f"Train contains unexpected novel pincodes: {train_novel_rate:.4f}"
    assert val_novel_rate < 0.01, f"Val contains unexpected novel pincodes: {val_novel_rate:.4f}"
    
    # Heldout should have EXACTLY 10% novel pincodes as per day 2 logs (125 / 1250 = 10%)
    heldout_novel_rate = heldout["is_novel_pincode"].mean()
    assert abs(heldout_novel_rate - 0.10) < 0.01, f"Heldout is missing 10% shift: {heldout_novel_rate:.4f}"

def test_deterministic_training_reproducibility(tmp_path):
    """Asserts that model training is exactly reproducible (fallback gate #5)."""
    import subprocess
    import hashlib
    
    def get_model_hash(path):
        with open(path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()
    
    # Ensure train_model.py script path is correct
    script_path = os.path.join(BASE_DIR, "scripts", "train_model.py")
    
    temp_model_dir = tmp_path / "models"
    temp_eval_dir = tmp_path / "eval"
    
    cmd = ["python", script_path, "--model-dir", str(temp_model_dir), "--eval-dir", str(temp_eval_dir)]
    
    # Train first time
    subprocess.run(cmd, check=True, capture_output=True)
    model_bin = temp_model_dir / "xgboost_rto_v1.bin"
    hash1 = get_model_hash(model_bin)
    
    # Train second time
    subprocess.run(cmd, check=True, capture_output=True)
    hash2 = get_model_hash(model_bin)
    
    assert hash1 == hash2, "Model training is not deterministic: hashes differ between runs"

def test_no_heldout_leakage_in_train_model():
    """Ensure scripts/train_model.py does not contain 'heldout.csv' to prevent data leakage."""
    import ast
    script_path = os.path.join(BASE_DIR, "scripts", "train_model.py")
    with open(script_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())
        
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert "heldout.csv" not in node.value, "Leakage detected: train_model.py references heldout.csv"
