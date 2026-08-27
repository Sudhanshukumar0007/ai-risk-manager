import urllib.request
import json
import uuid
import random
from datetime import datetime, timedelta

def get_random_order(i):
    # Base configuration
    order = {
        "event_id": str(uuid.uuid4()),
        "order_id": f"order-test-{i}-{random.randint(1000, 9999)}",
        "customer_id": f"cust-{random.randint(1, 100)}",
        "category": random.choice(["Electronics", "Fashion", "Groceries", "Home", "Beauty"]),
        "order_timestamp": (datetime.utcnow() - timedelta(minutes=random.randint(1, 1440))).isoformat() + "Z",
        "address_line_1": f"{random.randint(1, 999)} Main St",
        "address_line_2": "",
        "payment_method": "COD",  # We want to test COD routing
    }
    
    # 20% high risk, 30% medium risk, 50% low risk
    risk_level = random.random()
    if risk_level < 0.2:
        # High Risk (SOFT_GATE_COD)
        order.update({
            "cart_value": round(random.uniform(5000, 20000), 2),
            "pincode": random.choice(["110001", "400001", "700001"]),
            "item_quantity": random.randint(3, 10),
            "customer_past_rto_count": random.randint(3, 8),
            "phone_order_velocity_7d": random.randint(5, 15),
            "device_account_reuse_count": random.randint(3, 10),
            "account_age_days": random.randint(0, 10)
        })
    elif risk_level < 0.5:
        # Medium Risk (NUDGE_PREPAY)
        order.update({
            "cart_value": round(random.uniform(2000, 8000), 2),
            "pincode": random.choice(["110002", "400002", "500001"]),
            "item_quantity": random.randint(2, 5),
            "customer_past_rto_count": random.randint(1, 3),
            "phone_order_velocity_7d": random.randint(2, 6),
            "device_account_reuse_count": random.randint(1, 3),
            "account_age_days": random.randint(10, 60)
        })
    else:
        # Low Risk (ALLOW_COD)
        order.update({
            "cart_value": round(random.uniform(100, 2500), 2),
            "pincode": random.choice(["600001", "800001", "411001"]),
            "item_quantity": random.randint(1, 3),
            "customer_past_rto_count": 0,
            "phone_order_velocity_7d": random.randint(0, 2),
            "device_account_reuse_count": 0,
            "account_age_days": random.randint(100, 1000)
        })
        
    return order

url = "http://localhost:8000/v1/orders/score"
headers = {'Content-Type': 'application/json'}

success = 0
for i in range(25):
    order = get_random_order(i)
    req = urllib.request.Request(url, data=json.dumps(order).encode('utf-8'), headers=headers)
    try:
        urllib.request.urlopen(req)
        success += 1
    except Exception as e:
        print(f"Error on order {i}: {e}")

print(f"Successfully generated {success} diverse orders.")
