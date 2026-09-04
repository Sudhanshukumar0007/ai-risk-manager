import pandas as pd
import requests
import json
import uuid
import time
import random
from datetime import datetime, timedelta

def main():
    print("Reading heldout.csv...")
    df = pd.read_csv("data/heldout.csv")
    
    # Use all rows
    # df = df.sample(...)  # removed
    
    url = "http://localhost:8000/v1/orders/score"
    headers = {"Content-Type": "application/json"}
    
    success_count = 0
    
    for idx, row in df.iterrows():
        # Approximate raw features that would result in similar computed features
        order_timestamp = datetime.utcnow()
        if row['is_night_order'] == 1:
            order_timestamp = order_timestamp.replace(hour=random.choice([0, 1, 2, 3, 4]))
        else:
            order_timestamp = order_timestamp.replace(hour=random.choice(range(8, 22)))
            
        address_len = int(row['address_char_length']) if not pd.isna(row['address_char_length']) else 20
        address = "A" * address_len
        
        cart_value = max(100.0, 1500.0 + (float(row['cart_value_category_std_dev']) * 500.0))
        item_qty = max(1, int(2 + float(row['item_quantity_anomaly_score'])))
        
        payload = {
            "event_id": str(uuid.uuid4()),
            "order_id": str(row['order_id']),
            "pincode": str(row['pincode']),
            "customer_id": f"cust-{row['order_id']}",
            "category": str(row['category']),
            "cart_value": float(cart_value),
            "item_quantity": int(item_qty),
            "order_timestamp": order_timestamp.isoformat() + "Z",
            "address_line_1": address,
            "address_line_2": "",
            "payment_method": "COD" if row['is_cod_selected'] == 1 else "PREPAID",
            "customer_past_rto_count": int(row['customer_past_rto_count']),
            "phone_order_velocity_7d": int(row['phone_order_velocity_7d']),
            "device_account_reuse_count": int(row['device_account_reuse_count']),
            "account_age_days": int(row['account_age_days'])
        }
        
        try:
            resp = requests.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                success_count += 1
                print(f"[{success_count}/50] Successfully scored {payload['order_id']} -> Tier: {resp.json().get('tier')}")
            else:
                print(f"Failed to score {payload['order_id']}: {resp.status_code} - {resp.text}")
        except Exception as e:
            print(f"Error sending request: {e}")
            
        # Small delay to allow Celery tasks to start
        # time.sleep(0.5)

    print(f"Done! Successfully sent {success_count} requests.")

if __name__ == '__main__':
    main()
