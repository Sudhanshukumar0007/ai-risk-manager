import pytest
import os
import pandas as pd
import json

from app.features.pipeline import extract_features, compute_hub_distance
from app.features.address import compute_address_ambiguity

# Load a sample of validation data to test with
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
VAL_CSV_PATH = os.path.join(DATA_DIR, 'val.csv')

def test_feature_pipeline_schema_and_types():
    # Basic dummy payload
    payload = {
        "pincode": "PIN_001",
        "customer_id": "CUST_123",
        "category": "Apparel",
        "cart_value": 1500.0,
        "item_quantity": 2,
        "order_timestamp": "2026-08-25T02:30:00Z",
        "address_line_1": "near main road",
        "address_line_2": "",
        "payment_method": "COD"
    }
    
    features = extract_features(payload)
    
    expected_features = {
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
    }
    
    # 1. Exact 15 features present
    assert set(features.keys()) == expected_features
    
    # 2. Check no None/NaNs and check types
    for key, value in features.items():
        assert value is not None, f"Feature {key} is None"
        if isinstance(value, float):
            import math
            assert not math.isnan(value), f"Feature {key} is NaN"
        assert isinstance(value, (int, float)), f"Feature {key} has invalid type {type(value)}"


def test_feature_pipeline_hand_computed_values():
    payload = {
        "pincode": "UNKNOWN_PIN", # Novel pincode
        "customer_id": "CUST_123",
        "category": "Beauty",
        "cart_value": 3500.0,
        "item_quantity": 2,
        "order_timestamp": "2026-08-25T03:30:00Z",
        "address_line_1": "asdfghjkl",
        "address_line_2": "test address",
        "payment_method": "COD",
        "customer_past_rto_count": 3,
        "phone_order_velocity_7d": 5,
        "device_account_reuse_count": 2,
        "account_age_days": 15
    }
    
    features = extract_features(payload)
    
    # Delivery History Signal Family
    # UNKNOWN_PIN should fall back to global rate (0.239857...)
    assert round(features["pincode_historical_rto_rate"], 3) == 0.240
    assert features["customer_past_rto_count"] == 3
    # Category rate for 'Beauty' is 0.02 (from historical_rates.json)
    assert features["category_baseline_rto_rate"] == 0.02
    
    # Order Anomaly Signal Family
    # cart_value_category_std_dev: (3500 - 600) / 300 = 9.666...
    assert abs(features["cart_value_category_std_dev"] - 9.666666666666666) < 1e-6
    # item_quantity_anomaly_score: 2 / 6.0 = 0.3333333333333333
    assert abs(features["item_quantity_anomaly_score"] - 0.3333333333333333) < 1e-6
    # is_night_order: 03:30Z is 09:00 IST -> not night -> 0
    assert features["is_night_order"] == 0
    
    # Identity & Velocity Signal Family
    assert features["phone_order_velocity_7d"] == 5
    assert features["device_account_reuse_count"] == 2
    assert features["account_age_days"] == 15
    
    # Address Quality Signal Family
    addr = "asdfghjkl test address"
    assert features["address_char_length"] == len(addr)
    # Ambiguity score should be > 0.0 since it's in the corpus
    assert features["address_tfidf_ambiguity_score"] > 0.0
    # Hub distance for UNKNOWN_PIN should be fallback 1000.0
    assert features["hub_distance_km"] == 1000.0
    
    # Payment Context Signal Family
    assert features["is_cod_selected"] == 1
    
    # Drift Indicators Signal Family
    # UNKNOWN_PIN is not in NOVEL_PINCODES, so it's 0
    assert features["is_novel_pincode"] == 0
    # flash sale is direct copy of is_novel_pincode
    assert features["is_flash_sale_cart_value"] == 0


def test_val_csv_thin_positive_class_samples():
    """
    Test extraction using real validation rows, particularly focusing on the
    thin positive class constraint flagged in Day 2 (Issue #12).
    """
    if not os.path.exists(VAL_CSV_PATH):
        pytest.skip(f"{VAL_CSV_PATH} not found.")
        
    df_val = pd.read_csv(VAL_CSV_PATH)
    
    # Filter some positive RTO rows from val.csv
    pos_rto = df_val[df_val['is_rto'] == 1].head(5)
    neg_rto = df_val[df_val['is_rto'] == 0].head(5)
    
    sample_df = pd.concat([pos_rto, neg_rto])
    
    for _, row in sample_df.iterrows():
        # Create a mock payload based on csv data
        payload = {
            "pincode": row.get("pincode", "PIN_001"),
            "category": row.get("category", "Apparel"),
            "cart_value": row.get("cart_value", 1000.0),
            "item_quantity": row.get("item_quantity", 1),
            "customer_past_rto_count": row.get("customer_past_rto_count", 0),
            "phone_order_velocity_7d": row.get("phone_order_velocity_7d", 1),
            "device_account_reuse_count": row.get("device_account_reuse_count", 1),
            "account_age_days": row.get("account_age_days", 30),
            "payment_method": "COD" if row.get("is_cod_selected", 1) == 1 else "PREPAID"
        }
        
        # We simulate address ambiguity based on length provided in CSV
        # Just giving a dummy address to avoid empty
        payload["address_line_1"] = "test" * (int(row.get("address_char_length", 20)) // 4)
        
        features = extract_features(payload)
        
        # Verify feature output is valid and complete
        assert len(features) == 15
        for v in features.values():
            assert not pd.isna(v)
            
        # Verify drift values match what was in the CSV (no override anymore, should match)
        assert features["is_novel_pincode"] == row.get("is_novel_pincode", 0)
        assert features["is_flash_sale_cart_value"] == row.get("is_flash_sale_cart_value", 0)

def test_timezone_conversion():
    payload = {
        "pincode": "PIN_001",
        "category": "Apparel",
        "cart_value": 1500.0,
        "item_quantity": 2,
        # 19:30 UTC is 01:00 IST (night)
        "order_timestamp": "2026-08-25T19:30:00Z",
    }
    features = extract_features(payload)
    assert features["is_night_order"] == 1

def test_malformed_config(tmp_path, monkeypatch):
    import json
    from app.features import pipeline
    
    malformed_rates = {
        "pincode_rto_rates": {"PIN_001": 1.5}, # Invalid rate > 1
        "category_rto_rates": {"Apparel": -0.1}, # Invalid rate < 0
        "global_cod_rto_rate": 0.2
    }
    
    config_file = tmp_path / "historical_rates.json"
    config_file.write_text(json.dumps(malformed_rates))
    
    import builtins
    original_open = builtins.open
    def mock_open(file, *args, **kwargs):
        if "historical_rates.json" in str(file):
            return original_open(config_file, *args, **kwargs)
        return original_open(file, *args, **kwargs)
        
    monkeypatch.setattr(builtins, "open", mock_open)
    
    import importlib
    with pytest.raises(ValueError, match="Rate must be finite and in"):
        importlib.reload(pipeline)
