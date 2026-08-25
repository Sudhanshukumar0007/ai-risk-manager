import os
import json
import math
from datetime import datetime
from typing import Dict, Any

from app.features.address import compute_address_ambiguity

# Load and validate historical rates JSON at startup
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'config', 'historical_rates.json')

if not os.path.exists(CONFIG_PATH):
    raise RuntimeError(f"Required configuration file not found at {CONFIG_PATH}")

with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
    _rates_data = json.load(f)

# Schema validation
REQUIRED_KEYS = {"pincode_rto_rates", "category_rto_rates", "global_cod_rto_rate"}
if not isinstance(_rates_data, dict) or not REQUIRED_KEYS.issubset(_rates_data.keys()):
    raise ValueError(f"Invalid schema in historical_rates.json. Expected keys: {REQUIRED_KEYS}")

def validate_rate(v):
    if not isinstance(v, (int, float)):
        raise ValueError(f"Rate must be numeric, got {type(v)}")
    import math
    if not math.isfinite(v) or v < 0 or v > 1:
        raise ValueError(f"Rate must be finite and in [0, 1], got {v}")
    return float(v)

if not isinstance(_rates_data["pincode_rto_rates"], dict):
    raise ValueError("pincode_rto_rates must be a dict")
_pincode_rates = {k: validate_rate(v) for k, v in _rates_data["pincode_rto_rates"].items()}

if not isinstance(_rates_data["category_rto_rates"], dict):
    raise ValueError("category_rto_rates must be a dict")
_category_rates = {k: validate_rate(v) for k, v in _rates_data["category_rto_rates"].items()}

_global_cod_rto_rate = validate_rate(_rates_data["global_cod_rto_rate"])

# Load feature constants
CONSTANTS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'config', 'feature_constants.json')
with open(CONSTANTS_PATH, 'r', encoding='utf-8') as f:
    _constants_data = json.load(f)

_CATEGORY_MEDIAN_CART = _constants_data["CATEGORY_MEDIAN_CART"]
_CATEGORY_P95_BASKET = _constants_data["CATEGORY_P95_BASKET"]
_HUB_DISTANCES_BASE = _constants_data["HUB_DISTANCES_BASE"]
_NOVEL_PINCODES = set(_constants_data["NOVEL_PINCODES"])

def compute_hub_distance(pincode: str) -> float:
    if not pincode:
        return 1000.0 # Default fallback large distance
    
    return _HUB_DISTANCES_BASE.get(pincode, 1000.0)

def extract_features(order_payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extracts exactly 15 features across 5 signal families as specified in the plan.
    """
    
    # Payload parsing (with defaults if missing)
    pincode = str(order_payload.get("pincode", ""))
    customer_id = str(order_payload.get("customer_id", ""))
    category = str(order_payload.get("category", "Other"))
    cart_value = float(order_payload.get("cart_value", 0.0))
    item_quantity = int(order_payload.get("item_quantity", 1))
    order_timestamp_str = order_payload.get("order_timestamp", "")
    address_line_1 = str(order_payload.get("address_line_1", ""))
    address_line_2 = str(order_payload.get("address_line_2", ""))
    payment_method = str(order_payload.get("payment_method", "PREPAID")).upper()
    
    # 1. pincode_historical_rto_rate
    pincode_rate = _pincode_rates.get(pincode, _global_cod_rto_rate)
    
    # 2. customer_past_rto_count
    # In a real app, this would be a Redis lookup. Here, we parse from payload or default.
    cust_rto_count = int(order_payload.get("customer_past_rto_count", 0))
    
    # 3. category_baseline_rto_rate
    cat_rate = _category_rates.get(category, _global_cod_rto_rate)
    
    # 4. cart_value_category_std_dev
    cat_median = _CATEGORY_MEDIAN_CART.get(category, 1000.0)
    cat_std = cat_median * 0.5
    if cat_std > 0:
        cart_std_dev = (cart_value - cat_median) / cat_std
    else:
        cart_std_dev = 0.0
        
    # 5. item_quantity_anomaly_score
    cat_95th_qty = _CATEGORY_P95_BASKET.get(category, 5.0)
    qty_anomaly = item_quantity / float(cat_95th_qty)
    
    # 6. is_night_order
    is_night = 0
    if order_timestamp_str:
        try:
            from datetime import timezone, timedelta
            # Assuming ISO 8601 format like "2026-08-25T02:30:00Z"
            dt = datetime.fromisoformat(order_timestamp_str.replace('Z', '+00:00'))
            # Normalize to IST (+05:30)
            ist_tz = timezone(timedelta(hours=5, minutes=30))
            dt_ist = dt.astimezone(ist_tz)
            # Night is 00:00 to 05:00 IST
            if 0 <= dt_ist.hour < 5:
                is_night = 1
        except ValueError:
            pass
            
    # 7. phone_order_velocity_7d
    velocity_7d = int(order_payload.get("phone_order_velocity_7d", 1))
    
    # 8. device_account_reuse_count
    device_reuse = int(order_payload.get("device_account_reuse_count", 1))
    
    # 9. account_age_days
    account_age = int(order_payload.get("account_age_days", 30))
    
    # 10. address_char_length
    full_address = address_line_1 + " " + address_line_2
    addr_len = len(full_address.strip())
    
    # 11. address_tfidf_ambiguity_score
    ambiguity_score = compute_address_ambiguity(full_address)
    
    # 12. hub_distance_km
    hub_dist = compute_hub_distance(pincode)
    
    # 13. is_cod_selected
    is_cod = 1 if payment_method == "COD" else 0
    
    # 14. is_novel_pincode
    # NOTE: Novelty detection is scoped to the fixed 100-pincode simulation universe
    # and is not a general "have I seen this pincode before" production rule.
    is_novel = 1 if pincode in _NOVEL_PINCODES else 0
    
    # 15. is_flash_sale_cart_value
    # Match the exact co-injection identity logic from training (same value as novel pincode)
    is_flash = is_novel
    
    return {
        "pincode_historical_rto_rate": float(pincode_rate),
        "customer_past_rto_count": int(cust_rto_count),
        "category_baseline_rto_rate": float(cat_rate),
        "cart_value_category_std_dev": float(cart_std_dev),
        "item_quantity_anomaly_score": float(qty_anomaly),
        "is_night_order": int(is_night),
        "phone_order_velocity_7d": int(velocity_7d),
        "device_account_reuse_count": int(device_reuse),
        "account_age_days": int(account_age),
        "address_char_length": int(addr_len),
        "address_tfidf_ambiguity_score": float(ambiguity_score),
        "hub_distance_km": float(hub_dist),
        "is_cod_selected": int(is_cod),
        "is_novel_pincode": int(is_novel),
        "is_flash_sale_cart_value": int(is_flash)
    }
