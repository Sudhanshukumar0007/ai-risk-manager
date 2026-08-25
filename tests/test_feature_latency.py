import time
import pytest
import numpy as np
import os
import json

from app.features.pipeline import extract_features
from app.features.address import _vectorizer

def test_feature_latency_and_singleton():
    payload = {
        "pincode": "PIN_001",
        "customer_id": "CUST_123",
        "category": "Apparel",
        "cart_value": 1500.0,
        "item_quantity": 2,
        "order_timestamp": "2026-08-25T02:30:00Z",
        "address_line_1": "123 main street, near temple",
        "address_line_2": "city center",
        "payment_method": "COD"
    }

    # 1. Verify Singleton Behavior
    # We can check memory address of the vectorizer or ensure that re-importing 
    # gives the exact same object.
    from app.features.address import _vectorizer as vec2
    assert id(_vectorizer) == id(vec2), "Vectorizer is not a module-level singleton!"
    
    # Check that it's already fitted by checking vocabulary
    assert hasattr(_vectorizer, 'vocabulary_'), "Vectorizer was not fitted at startup!"

    # 2. Latency Benchmarking
    # Warm-up phase
    for _ in range(10):
        _ = extract_features(payload)

    iterations = 1000
    latencies = []

    for _ in range(iterations):
        start = time.perf_counter()
        _ = extract_features(payload)
        end = time.perf_counter()
        latencies.append((end - start) * 1000) # in ms

    latencies_array = np.array(latencies)
    p50 = np.percentile(latencies_array, 50)
    p95 = np.percentile(latencies_array, 95)
    p99 = np.percentile(latencies_array, 99)

    # Save latency report for deliverable
    report_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'eval', 'latency_report.md')
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("# Day 3 Feature Extraction Latency Report\n\n")
        f.write(f"- Iterations: {iterations}\n")
        f.write(f"- p50 latency: {p50:.4f} ms\n")
        f.write(f"- p95 latency: {p95:.4f} ms\n")
        f.write(f"- p99 latency: {p99:.4f} ms\n")
        f.write("\n## Status\n")
        status = "PASSED" if p99 < 10.0 else "FAILED"
        f.write(f"Target Budget: < 10 ms\n")
        f.write(f"Result: {status}\n")

    print(f"\nLatency Benchmarking (n={iterations}):")
    print(f"p50: {p50:.4f} ms")
    print(f"p95: {p95:.4f} ms")
    print(f"p99: {p99:.4f} ms")

    # Assert p99 latency stays under the target budget of 10ms
    assert p99 < 10.0, f"p99 latency ({p99:.4f} ms) exceeded 10ms budget!"
