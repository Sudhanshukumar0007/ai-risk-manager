# Day 03 Audit — Feature Extraction Engine & Latency Benchmarking

Date/session: 2026-08-25
Auditor: Codex GPT-5
Scope: Day 03 implementation only, reviewed against `instructions .md`, `Implementation_plan.md`, `docs/worklogs/day-03.md`, `scripts/generate_data.py`, `app/features/*`, and Day 03 tests.

## Audit Verdict

Day 03 is acceptable for the latency gate, but it is not fully clean for production-style scoring. The implementation creates the required feature modules, returns the exact 15 feature names, caches the TF-IDF vectorizer and historical rates at module scope, and the Day 03 tests pass locally.

The main risk is training/serving skew. Several runtime feature calculations in `app/features/pipeline.py` use hardcoded or synthetic approximations that do not match the Day 2 generator's feature definitions. This is survivable for a hackathon simulation if documented, but it must be addressed before the API scorer is treated as equivalent to the trained model's feature space.

## Governing Workflow Check

| Workflow Requirement | Status | Evidence |
|---|---|---|
| Read governing instructions | PASS | Day 03 worklog states `instructions .md` was consulted. |
| Read implementation plan | PASS | Day 03 worklog maps against Day 3 tasks. |
| Inspect repository state | PASS | `app/features/address.py`, `app/features/pipeline.py`, and tests were inspected. |
| Validate current phase | PASS | Local run of `python -m pytest tests\test_feature_pipeline.py tests\test_feature_latency.py -v` passed 4/4. |
| Worklog uses mandatory template | PASS | `docs/worklogs/day-03.md` follows the required phase-log structure. |

## Plan Alignment

| Day 03 Plan Step | Audit Status | Notes |
|---|---|---|
| Build TF-IDF address vectorizer | PASS WITH SKEW RISK | `app/features/address.py` defines a singleton vectorizer, but it is fitted on a small hand-written corpus while Day 2 training data uses synthetic beta-distributed ambiguity scores. |
| Build feature extraction pipeline | PASS WITH SKEW RISK | Exact keys are returned, but several formulas differ from Day 2 generation. |
| Load and validate `historical_rates.json` | PASS WITH WEAK VALIDATION | Top-level schema is validated, but nested key/value types and numeric ranges are not. |
| Add hub-distance logic | PASS WITH DOC ISSUE | Haversine distance exists, but coordinates are derived from an MD5 hash of pincode. |
| Add correctness tests | PASS WITH COVERAGE GAP | Tests validate shape/types and a few hand-computed values. They do not prove parity with Day 2's canonical feature generation. |
| Add latency tests | PASS | p99 is under 10 ms in both worklog and local run. |

## Validation Evidence

Command run:

```text
python -m pytest tests\test_feature_pipeline.py tests\test_feature_latency.py -v
```

Result:

```text
4 passed, 1 warning in 3.17s
```

Warning:

```text
PytestConfigWarning: Unknown config option: asyncio_mode
```

The warning is environmental and already appeared in earlier local validation. The Day 03 latency report records:

```text
p50: 0.9872 ms
p95: 1.9031 ms
p99: 2.8417 ms
target: < 10 ms
```

## Findings

### A-D3-001 — Runtime Feature Formulas Do Not Match Training Feature Generation

Severity: High downstream risk

Evidence:

- `app/features/pipeline.py:105` hardcodes `cat_median = 1000.0` and `cat_std = 500.0` for every category.
- `app/features/pipeline.py:113` hardcodes `cat_95th_qty = 5.0`.
- `scripts/generate_data.py` uses category-specific medians and basket p95 values when creating the training columns.

Risk:

The model is trained on one feature distribution but the future API scorer will emit another. This can degrade score calibration, threshold behavior, and SHAP explanations even if offline validation remains excellent.

Recommendation:

Move category medians and p95 basket values into a versioned config artifact, then make Day 2 generation and Day 3 extraction consume the same constants. Add a parity test for a fixed payload where expected `cart_value_category_std_dev` and `item_quantity_anomaly_score` are category-specific.

### A-D3-002 — Hub Distance Is Mathematically Haversine But Semantically Arbitrary

Severity: Medium

Evidence:

- `app/features/pipeline.py:48` derives pincode coordinates from an MD5 hash.
- `app/features/pipeline.py:73` then computes distance to hardcoded hub centroids.
- Day 03 worklog says the implementation "avoids random hashes," but the implementation still uses a hash-derived location surrogate.

Risk:

The output is deterministic and fast, but it is not geospatially meaningful and does not match Day 2's `HUB_DISTANCES_BASE` simulation. The worklog overstates the quality of this implementation detail.

Recommendation:

Either document this as a deterministic simulator or replace it with a shared pincode-to-distance lookup generated from the same Day 2 constants.

### A-D3-003 — Address Ambiguity Has No Training/Serving Parity

Severity: Medium

Evidence:

- `app/features/address.py` fits a TF-IDF model on a small reference corpus.
- `scripts/generate_data.py` generates `address_tfidf_ambiguity_score` directly from a beta distribution rather than from address text.

Risk:

Offline model metrics are not proving that the real TF-IDF address signal is predictive. The Day 8 explanation layer may expose address-based SHAP reasons that are artifacts of synthetic training data rather than runtime extraction.

Recommendation:

For the simulation, generate synthetic address text and compute ambiguity with the same vectorizer during Day 2, or persist a deterministic ambiguity score contract and clearly document that raw-address parity is out of scope.

### A-D3-004 — Night-Order Parsing Uses Timestamp Hour Without Timezone Normalization

Severity: Medium

Evidence:

- `app/features/pipeline.py:121` parses ISO timestamps and checks `dt.hour` directly.
- `scripts/generate_data.py` defines night order as 00:00-05:00 IST.

Risk:

If production payloads send UTC timestamps, a 02:30 UTC order is treated as night even though it is 08:00 IST. This can create inconsistent risk scores by integration source.

Recommendation:

Normalize incoming timestamps to IST before computing `is_night_order`, or require local-time timestamps in the API contract and test that behavior.

### A-D3-005 — Historical-Rate Config Validation Is Shallow

Severity: Low to Medium

Evidence:

- `app/features/pipeline.py` checks only the presence of `pincode_rto_rates`, `category_rto_rates`, and `global_cod_rto_rate`.

Risk:

A malformed config with string rates, out-of-range rates, missing standard pincodes, or invalid categories could pass import and fail later in scoring.

Recommendation:

Validate nested dictionaries, numeric coercion, finite values, and `[0, 1]` bounds. Fail fast with an actionable error.

## Non-Issues Confirmed

- The pipeline returns exactly 15 feature keys.
- Module-level loading avoids per-request file I/O.
- TF-IDF vectorizer is fitted once at import time.
- Feature extraction is comfortably under the 10 ms p99 latency budget.
- `eval/latency_report.md` exists and records the benchmark.

## Proceed / Stop Decision

Proceed to Day 04 was acceptable for the hackathon sequence because the Day 03 acceptance gate passed. Carry the training/serving skew issues into Day 6 before wiring the scorer into the API path.

## Remediation Status

Status: OPEN

Open items:

1. Share feature constants between Day 2 generation and Day 3 extraction.
2. Replace or document hash-derived hub distance.
3. Resolve address ambiguity parity.
4. Normalize or contractually define timestamp timezone behavior.
