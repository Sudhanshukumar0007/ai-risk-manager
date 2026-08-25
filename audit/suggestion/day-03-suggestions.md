# Day 03 Suggestions

## Priority Fixes

1. Eliminate training/serving skew in order-anomaly features. Move category medians and category p95 basket sizes into shared config, then use that config from both `scripts/generate_data.py` and `app/features/pipeline.py`.

2. Replace hash-derived pincode coordinates with a shared simulated distance lookup. If the project keeps a simulator, generate and persist `config/pincode_hub_distances.json` from Day 2 constants and have Day 3 read it.

3. Resolve address ambiguity parity. Either generate synthetic address text in Day 2 and compute `address_tfidf_ambiguity_score` with the Day 3 vectorizer, or document that the offline training feature is a synthetic proxy and not equivalent to runtime TF-IDF.

4. Normalize `order_timestamp` to IST before computing `is_night_order`, or explicitly require local IST timestamps in the API contract.

5. Deepen `historical_rates.json` validation. Check nested mapping types, numeric finite values, `[0, 1]` bounds, and expected category coverage.

## Suggested Test Additions

```text
pytest tests/test_feature_pipeline.py -v
```

Add assertions for:

- category-specific cart z-score for Electronics, Apparel, Home, Beauty, and Books;
- category-specific item quantity anomaly score;
- unknown pincode fallback to global RTO rate;
- known pincode mapped rate exactness;
- timestamp conversion around UTC/IST boundary cases;
- malformed historical-rate config rejection.

## Suggested Day 6 Carry-Forward

Before wiring `extract_features()` into `POST /v1/orders/score`, add one end-to-end scorer test that feeds a realistic API payload through feature extraction, model scoring, and SHAP attribution. This is where train/serve skew becomes user-visible.
