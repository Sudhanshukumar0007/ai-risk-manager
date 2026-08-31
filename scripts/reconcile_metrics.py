import os
import sys
import json
import pandas as pd
import numpy as np
import joblib

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.ml.costs import CostEngine
from sklearn.metrics import confusion_matrix

def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    df = pd.read_csv(os.path.join(base_dir, "data", "heldout.csv"))
    
    with open(os.path.join(base_dir, "config", "thresholds.json"), "r") as f:
        thresholds = json.load(f)
    t_low = thresholds["t_low"]
    t_high = thresholds["t_high"]

    feature_cols = [
        "pincode_historical_rto_rate", "customer_past_rto_count", "category_baseline_rto_rate",
        "cart_value_category_std_dev", "item_quantity_anomaly_score", "is_night_order",
        "phone_order_velocity_7d", "device_account_reuse_count", "account_age_days",
        "address_char_length", "address_tfidf_ambiguity_score", "hub_distance_km",
        "is_cod_selected", "is_novel_pincode", "is_flash_sale_cart_value"
    ]
    
    pos_idx = df[df['is_rto'] == 1].index[:5]
    neg_idx = df[df['is_rto'] == 0].index[:5]
    idx = list(pos_idx) + list(neg_idx)
    df_sub = df.loc[idx]
    
    X = df_sub[feature_cols]
    
    def simulate_router_day10(probs, tl, th):
        tiers = []
        for p in probs:
            if p >= th:
                tiers.append('SOFT_GATE_COD')
            elif p >= tl:
                tiers.append('NUDGE_PREPAY')
            else:
                tiers.append('ALLOW_COD')
        return np.array(tiers)
        
    model_path = os.path.join(base_dir, "models", "xgboost_rto_v1.bin")
    model = joblib.load(model_path)
    y_prob = model.predict_proba(X)[:, 1]
    
    tiers = simulate_router_day10(y_prob, t_low, t_high)
    
    for i, row_idx in enumerate(idx):
        yt = y_true[i]
        yp_prob = y_prob[i]
        tier = tiers[i]
        
        # Day 10 metrics logic (from evaluate_heldout.py)
        # y_pred_binary = (y_prob >= t_low).astype(int) -> so TP if yt=1 and prob >= t_low
        d10_pred = int(yp_prob >= t_low)
        if yt == 1 and d10_pred == 1: d10_label = "TP"
        elif yt == 0 and d10_pred == 1: d10_label = "FP"
        elif yt == 1 and d10_pred == 0: d10_label = "FN"
        else: d10_label = "TN"
        
        # Day 10 Net Saved (evaluate_decisions)
        baseline_cost = engine.c_rto if yt == 1 else 0
        if tier == 'ALLOW_COD':
            eng_cost = engine.cost_fn() if yt == 1 else 0
        elif tier == 'NUDGE_PREPAY':
            eng_cost = engine.cost_tp_m() if yt == 1 else engine.cost_fp_m()
        elif tier == 'SOFT_GATE_COD':
            eng_cost = engine.cost_tp_h() if yt == 1 else engine.cost_fp_h()
            
        d10_net_saved = baseline_cost - eng_cost
        
        print(f"Row {row_idx}: y_true={yt}, prob={yp_prob:.4f}, tier={tier}")
        print(f"  Day 10/11 Logic: Label={d10_label}, Net Saved={d10_net_saved}")

if __name__ == "__main__":
    main()
