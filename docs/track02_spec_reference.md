# Comprehensive 10-Day Phase-Wise Implementation Plan and Engineering Specification for Track 02 AI Risk Manager

> Clean-text reference extracted from `Ten_Day_Implementation_Plan_Roadmap.pdf`. Replaces the earlier lossy `docs/pdf_extract.txt` (which dropped all inline math notation). All formulas below were reconstructed directly from the PDF's rendered equation images, not guessed.

## System Architecture and Reconciled Financial Cost Model

The AI Risk Manager architecture operates on a strict separation of probabilistic machine learning intelligence and deterministic financial execution. Machine learning decision loops must never directly execute ungated monetary actions; probabilistic models evaluate risk context while deterministic routers enforce business constraints, rate limits, and financial safety boundaries.

The physical system topology consists of **five decoupled service components**:

1. Asynchronous FastAPI ingestion gateway (port 8000) receiving order-payload webhooks.
2. Atomic Redis deduplication store — 24-hour TTL key check guaranteeing idempotency, ahead of processing queues.
3. Celery distributed task queue backed by **RabbitMQ**.
4. Sub-10ms Feature Extraction Engine merging tabular order data with pre-cached character-level TF-IDF string ambiguity scores.
5. PostgreSQL database recording an immutable, append-only audit entry.

Flow: webhook → Redis dedup → Celery/RabbitMQ → Feature Extraction Engine → XGBoost classifier (outputs calibrated `P(RTO)`) → simultaneously to (a) SHAP TreeExplainer (top-3 local feature attributions) and (b) Postgres audit log → `P(RTO)` passes to the 2D Threshold Router (`config/thresholds.json`) → one of three deterministic actions:

- **Tier 1 — ALLOW_COD**: standard Cash-on-Delivery fulfillment.
- **Tier 2 — NUDGE_PREPAY**: Razorpay Sandbox API call generating an incentivized prepaid conversion link.
- **Tier 3 — SOFT_GATE_COD**: interactive verification flags prior to dispatch.

An asynchronous LLM copy generator parses SHAP outputs into localized WhatsApp outreach copy and merchant explanations, protected by a circuit-breaker fallback to static templates so the LLM never sits on the monetary execution path.

## Reconciled Financial Cost Formulation

Prior cost models wrongly treated every TP and FP as financially equivalent across all action tiers. A low-friction action (WhatsApp nudge with small discount) has a very different false-positive penalty than a high-friction action (hard address-verification gate). Cost accounting for high-risk gating must also reflect pre-dispatch cancellations: when a gated high-risk COD order is not verified, it's canceled before fulfillment, producing **zero two-way freight loss** — charging it full RTO cost would mathematically disincentivize the router from ever using soft gates.

Action tiers: **Medium Risk (M)** = NUDGE_PREPAY, **High Risk (H)** = SOFT_GATE_COD.

```
Baseline Loss = N_RTO × C_RTO
```
`N_RTO` = total count of actual RTO events; `C_RTO` = two-way shipping freight + packaging write-off cost.

```
Engine Loss = Cost(FN) + Cost(TP_M) + Cost(FP_M) + Cost(TP_H) + Cost(FP_H)
```

Cost components:

```
Cost(FN)   = FN × C_RTO

Cost(TP_M) = TP_M × [ α_M · Discount_M + (1 − α_M) · C_RTO ]

Cost(FP_M) = FP_M × [ α_M · Discount_M + (1 − α_M) · C_Lost_M ]

Cost(TP_H) = TP_H × [ (1 − α_H) · 0 + α_H · (Friction_Cost_H + r_residual · C_RTO) ]

Cost(FP_H) = FP_H × [ (1 − α_H) · C_Lost_H + α_H · Friction_Cost_H ]

Net Saved  = Baseline Loss − Engine Loss
```

Note the `(1 − α_H) · 0` term in `Cost(TP_H)`: this is the zero-freight-loss cancellation branch — when a true-RTO high-risk order is gated and the buyer doesn't confirm, the cost is exactly zero (order never ships), not `C_RTO`.

### Parameter table

| Parameter | Definition | Base Value | Sensitivity Range |
|---|---|---|---|
| `C_RTO` | Return-to-Origin cost (two-way freight + packaging write-off) | ₹150 | ₹120–₹200 |
| `C_Lost_M` | FP cost, Medium tier (soft churn from an ignorable discount offer) | ₹40 | ₹20–₹80 |
| `C_Lost_H` | FP cost, High tier (margin + unrecoverable CAC when a valid buyer abandons a hard gate) | ₹400 | ₹300–₹600 |
| `α_M` | Nudge conversion rate (medium-risk COD → prepaid after WhatsApp nudge) | 0.25 | 0.15–0.35 |
| `α_H` | Gate confirmation rate (high-risk buyers completing IVR/address verification) | 0.45 | 0.30–0.60 |
| `Discount_M` | Prepaid incentive discount | ₹50 | ₹30–₹70 |
| `Friction_Cost_H` | Verification operational cost (IVR/WhatsApp session) | ₹15 | ₹10–₹25 |
| `r_residual` | Residual RTO rate after successful high-risk address confirmation | 0.10 | 0.05–0.20 |

## Closed-Form Breakeven Derivations

Breakeven `TP:FP` ratio per tier is found by setting incremental net profit to zero.

**Medium Tier:**
```
Gain(TP_M) = C_RTO − [α_M·Discount_M + (1−α_M)·C_RTO] = α_M·(C_RTO − Discount_M)
Loss(FP_M) = α_M·Discount_M + (1−α_M)·C_Lost_M

(TP/FP)_breakeven_M = Loss(FP_M) / Gain(TP_M)
```
With base values: `Gain(TP_M) = 0.25×(150−50) = ₹25.00`; `Loss(FP_M) = (0.25×50)+(0.75×40) = ₹42.50`
```
(TP/FP)_breakeven_M = 42.50 / 25.00 = 1.70
```

**High Tier:**
```
Gain(TP_H) = C_RTO − α_H·(Friction_Cost_H + r_residual·C_RTO)
Loss(FP_H) = (1−α_H)·C_Lost_H + α_H·Friction_Cost_H

(TP/FP)_breakeven_H = Loss(FP_H) / Gain(TP_H)
```
With base values: `Gain(TP_H) = 150 − 0.45×(15+0.10×150) = 150 − 13.50 = ₹136.50`; `Loss(FP_H) = (0.55×400)+(0.45×15) = ₹226.75`
```
(TP/FP)_breakeven_H = 226.75 / 136.50 ≈ 1.66
```

## 2D Joint Threshold Grid Optimization

Two boundary cutoffs: `t_low` separates ALLOW_COD from NUDGE_PREPAY; `t_high` separates NUDGE_PREPAY from SOFT_GATE_COD. Optimizing a single global threshold is invalid — a 2D grid search on validation data maximizes total Net Saved:

```
(t_low*, t_high*) = argmax_{t_low, t_high} NetSaved(ValSet | t_low, t_high, CostMatrix)
```

Search constraints: `t_low ∈ [0.15, 0.50]` in steps of `0.025`; `t_high ∈ [t_low + 0.05, 0.85]` in steps of `0.025`. Optimal cutoffs are serialized to `config/thresholds.json` and remain **frozen** during held-out evaluation.

## Multi-Signal Feature Engineering (15 features, 5 signal families)

| Signal Family | Feature Name | Type | Computation / Ingestion |
|---|---|---|---|
| Delivery History | `pincode_historical_rto_rate` | Float | Target-encoded historical RTO probability for delivery pincode (Redis lookup) |
| Delivery History | `customer_past_rto_count` | Integer | Historical count of returned shipments tied to customer ID/phone (Redis lookup) |
| Delivery History | `category_baseline_rto_rate` | Float | Baseline return rate per product category (memory lookup) |
| Order Anomaly | `cart_value_category_std_dev` | Float | Z-score of order amount vs. category median price (in-memory) |
| Order Anomaly | `item_quantity_anomaly_score` | Float | Ratio of cart item count to category 95th-percentile basket size (in-memory) |
| Order Anomaly | `is_night_order` | Binary | Order timestamp between 00:00–05:00 IST (timestamp parsing) |
| Identity & Velocity | `phone_order_velocity_7d` | Integer | Order attempts linked to phone number, prior 7 days (Redis sliding window) |
| Identity & Velocity | `device_account_reuse_count` | Integer | Distinct account IDs on current device fingerprint (Redis set cardinality) |
| Identity & Velocity | `account_age_days` | Integer | Days since customer account registration (DB/cache lookup) |
| Address Quality | `address_char_length` | Integer | Raw character length of address line 1 + 2 (string length) |
| Address Quality | `address_tfidf_ambiguity_score` | Float | Cosine similarity of char 2–4 n-grams vs. precomputed bad-address matrix (pre-fitted vectorizer) |
| Address Quality | `hub_distance_km` | Float | Geodesic distance, delivery pincode centroid → nearest fulfillment hub (KD-Tree query) |
| Payment Context | `is_cod_selected` | Binary | Customer selected COD at checkout (payload parsing) |
| Drift Indicators | `is_novel_pincode` | Binary | Pincode unobserved in historical training baseline (Bloom filter / set lookup) |
| Drift Indicators | `is_flash_sale_cart_value` | Binary | Cart value exceeds 99th-percentile historical baseline (threshold comparison) |

### Sub-10ms TF-IDF Address Ambiguity Engine
Vectorizer is fitted **once at startup** against a reference corpus of ambiguous/incomplete Indian address patterns (e.g. "near main road", "behind bus stand", "house number zero"). Live inference transforms incoming strings against the cached vectorizer and computes cosine similarity to the pre-fitted bad-address matrix. Guarantees p99 feature extraction under **8.5ms**. Fitting per-request would add 150–300ms — explicitly disallowed.

## Synthetic Data Generation and Distributional Realism Protocol

Three isolated random seeds, single-directional statistical lookups only (train → val/heldout, never reverse):

1. **Training**: 5,000 samples, seed=101, standard baseline distribution.
2. **Validation**: 750 samples, seed=202, used for joint threshold optimization.
3. **Held-Out Test**: 1,250 samples, seed=303, injected 10% covariate shift via unseen pincodes (`is_novel_pincode=1`) and extreme cart values (`is_flash_sale_cart_value=1`).

Pincode historical RTO rates and novel-pincode designations are computed **strictly from `train.csv`**; heldout is never queried for reference aggregations.

Data fidelity gates:
- Continuous features: KS-test `p > [threshold, unspecified in extract]` across numeric dims, train vs. non-shifted validation.
- Categorical features: Total Variation distance `< 0.05`.
- Correlation structure: Frobenius norm `‖Σ_real − Σ_synth‖_F < 0.15`.

Calibration:
```
ECE = Σ_b (|B_b| / N) · |acc(B_b) − conf(B_b)|      (10 uniform probability bins)
Brier Score = (1/N) · Σ_i (p_i − y_i)²
```
Target: `Brier Score < [threshold, unspecified in extract]`, `ECE < 0.08` on validation data.

## Detailed Phase-Wise 10-Day Plan (summary)

| Day | Phase | Key Deliverables | Acceptance Test |
|---|---|---|---|
| 1 | Infrastructure scaffolding, service wiring, API baseline | `docker-compose.yml` (Postgres, Redis, FastAPI, Celery), `.env.example`, `/health` route | `tests/test_health.py` — HTTP 200 from `/health` in running containers |
| 2 | Synthetic data engine, triple-seeded generation, drift injection | `scripts/generate_data.py`, `train/val/heldout.csv`, `generation_report.md` | `tests/test_data_integrity.py` — zero UUID overlap across splits, target distributions validated |
| 3 | Feature extraction engine, latency benchmarking | `app/features/address.py`, `app/features/pipeline.py`, `eval/latency_report.md` | `tests/test_feature_latency.py` — p99 < 10.0ms over 1,000 calls |
| 4 | Model training, calibration, SHAP explainability | `models/xgboost_rto_v1.bin`, `app/ml/shap_engine.py`, `eval/calibration_report.md` | `tests/test_model_performance.py` — PR-AUC > 0.70, Brier Score < [threshold], valid SHAP top-3 JSON |
| 5 | Financial cost engine, 2D threshold search, **Checkpoint 1 freeze** | `app/ml/costs.py`, `config/thresholds.json`, `eval/threshold_heatmap.png`, `eval/breakeven_ratios.md` | `tests/test_threshold_optimizer.py` — selected thresholds give non-negative Net Saved, beat baseline |
| 6 | FastAPI ingestion, Redis dedup, audit schema | `app/api/routes.py`, `app/db/models.py`, `app/core/idempotency.py` | `scripts/test_idempotency.sh` — duplicate webhook → DB row count stays 1 |
| 7 | Action router, Razorpay Sandbox integration | `app/services/router.py`, `app/services/razorpay_client.py`, `app/api/webhooks.py` | `tests/test_razorpay_integration.py` — sandbox payment link creation + webhook state update |
| 8 | Async LLM explanation layer, circuit-breaker fallback | `app/services/llm_explain.py`, `eval/llm_examples.md` | `tests/test_llm_fallback.py` — mocked API timeout still returns HTTP success w/ static fallback copy |
| 9 | Operational dashboard, fault-injection demo videos | `dashboard/app.py`, 2 fault-injection video clips (LLM outage, webhook replay) | Manual audit of dashboard responsiveness under load |
| 10 | Final held-out evaluation, submission freeze | `eval/final_report.md`, `README.md`, `docs/architecture_spec.md` | `scripts/evaluate_heldout.py` — reproduces all `final_report.md` values exactly |

### Day 5 detail
1. Program tier-conditioned financial loss functions in `app/ml/costs.py`.
2. Execute 2D grid search over `t_low ∈ [0.15,0.50]`, `t_high ∈ [t_low+0.05, 0.85]` using `val.csv`.
3. Generate 2D Net Saved heatmap (`eval/threshold_heatmap.png`).
4. Compute explicit breakeven ratios for M-tier and H-tier; serialize optimal cutoffs to `config/thresholds.json`.
- Risk: overfitting cutoffs to validation noise. Mitigation: coarse 0.025 grid steps with cross-validation smoothing.

### Day 8 detail
- `app/services/llm_explain.py` calls the Anthropic Claude API with top-3 SHAP features + risk score + action tier as prompt context.
- Hard 2,500ms timeout via try/except; on failure, static fallback copy ("Flagged for manual review — explanation unavailable") while score/tier/payment-link creation proceed unaffected.

## Mid-Point Verification Tracker (Day 5 Checkpoint 1)

| Milestone | Benchmark | Target Artifact | Status (per plan) |
|---|---|---|---|
| M01 System Scaffolding | Clean 4-service docker stack, `/health` 200 | `docker-compose.yml`, `app/main.py` | Complete (Day 1) |
| M02 Data Engine | 3 seeded splits, 7k records, zero leakage | `data/train.csv`, `val.csv`, `heldout.csv` | Complete (Day 2) |
| M03 Distribution Realism | KS-test, TV distance, correlation-diff bounds | `data/generation_report.md` | Complete (Day 2) |
| M04 Feature Extraction | p99 latency under budget, 1,000 calls | `eval/latency_report.md` | Complete (Day 3) |
| M05 Risk Classifier | XGBoost + valid SHAP top-3 attributions | `models/xgboost_rto_v1.bin` | Complete (Day 4) |
| M06 Calibration Engine | Brier/ECE under shift | `eval/calibration_report.md` | Complete (Day 4) |
| M07 Reconciled Financial Costs | Tier-conditioned formulas, ₹0 cancellation branch | `app/ml/costs.py` | Complete (Day 5) |
| M08 Breakeven Formulas | Closed-form ratios: **M-tier = 1.70, H-tier = 1.66** | `eval/breakeven_ratios.md` | Complete (Day 5) |
| M09 2D Threshold Search | Joint `(t_low, t_high)` optimization on `val.csv` | `config/thresholds.json` | Complete (Day 5) |
| M10 Mid-Point Heatmap | Net Saved surface across joint thresholds | `eval/threshold_heatmap.png` | Complete (Day 5) |

**Note:** the plan's own tracker states the authoritative M08 values as **1.70 (M-tier)** and **1.66 (H-tier)** — this is the traceable source for the ratio dispute in the Day 5 audit; see conversation notes on the `costs.py` FP-loss weighting bug.

## Final Submission Verification Checklist (Day 10)

| Criterion | Verification | Artifact |
|---|---|---|
| Held-Out Isolation | `heldout.csv` read exactly once, at final eval, with frozen thresholds | `eval/final_report.md` |
| Tier Cost Accounting | `TP_H` cancellation branch charged ₹0 freight loss | `app/ml/costs.py` |
| Breakeven Reporting | Explicit TP:FP ratios (M=1.70, H=1.66) from empirical parameters | `eval/breakeven_ratios.md` |
| 2D Threshold Search | Joint `(t_low, t_high)` optimization on validation data before locking config | `config/thresholds.json` |
| Covariate Drift Check | Calibration/confidence comparison on shifted heldout rows | `eval/calibration_report.md` |
| Sub-10ms Feature Latency | p99 extraction time under budget, 1,000 calls | `eval/latency_report.md` |
| Live Webhook Dedupe | Duplicate webhook replay → DB row count stays 1 | `app/core/idempotency.py` |
| Razorpay API Integration | Sandbox payment link creation + webhook state update | `app/services/razorpay_client.py` |
| Deterministic Isolation | Thresholds strictly dictate API calls; LLM generates copy only | `app/services/router.py` |
| Fault Injection: LLM Down | Live demo — scoring/routing/link creation continue when LLM key revoked | `docs/videos/fault_injection_llm.mp4` |
| Fault Injection: Replay | Live demo — duplicate webhook silently discarded by Redis key check | `docs/videos/fault_injection_idempotency.mp4` |
| Immutable Audit Trail | Append-only triggers on `audit_log`; UPDATE statements blocked | `app/db/models.py` |
| Defense-Only Compliance | `grep -r -i "exploit\|bypass\|attack"` returns zero hits | Entire codebase |
| Sensitivity Sweep | Net Saved variation across `C_Lost` and conversion-rate ranges | `eval/final_report.md` |
| Multi-Threshold Table | Precision/Recall/F1/Net Saved at cutoffs 0.50/0.60/0.70/0.80 on heldout | `eval/final_report.md` |

## Strategic Risk Mitigation and Operational Failure Modes

| Failure Mode | Mitigation Mechanism | Fallback State |
|---|---|---|
| Redis node partition | Try/except → synchronous Postgres unique-key check (`CONSTRAINT unique_event_id UNIQUE (event_id)`) | DB ingestion at slower rate |
| Celery queue backup (>3,000ms queue age) | Worker auto-scaling; if backpressure persists, switch to synchronous in-process scoring | Synchronous ingestion path |
| LLM API timeout (>2,500ms) | Async circuit breaker trips | Static local copy template; scoring/routing/payment-link creation unaffected |
| Razorpay gateway down | Exponential backoff retries (5s, 15s, 45s, 135s) | Order → `PENDING_RETRY` status in Postgres |
| Distribution drift (novel pincode / flash-sale cart value) | Explicit `is_novel_pincode` / `is_flash_sale_cart_value` flags shift probability output toward 0.5 | Ambiguous orders routed to manual verification |

## Works Cited (per PDF)
1. Razorpay Buildathon Ideas & Requirements.pdf
2. razorpay_buildathon_research_validation_and_inspirations.md
3. Implementaion_guide_V3.md
4. track02_risk_manager_rigorous_guide.md
5. track02_implementation_guide_v2.md
6. deep-research-report.md
