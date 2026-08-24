# Day 02 — Synthetic Data Engine

**Date:** 2026-08-24  
**Status:** Complete (pending container test pass)  
**Phase:** Day 2 of 10-Day AI Risk Manager plan

---

## Objectives (from implementation plan)

1. Build `scripts/generate_data.py` with 15 features across five signal families.
2. Generate isolated seeded CSVs: `train.csv` (5,000), `val.csv` (750), `heldout.csv` (1,250).
3. Inject covariate shift on 10% of heldout only.
4. Log per-split positive-class counts to `data/generation_report.md` (issue #12).
5. Compute historical RTO rates strictly from train — no leakage.
6. Verify composition matches spec: ~62% COD, ~24% RTO-in-COD.
7. Pass `pytest tests/test_data_integrity.py`.

---

## Pre-Implementation Issue Found

**PDF verification step:** Before running, the initial draft of `generate_data.py` was
cross-referenced against the source document (`docs/pdf_extract.txt`). Seven mismatches
were found between the first-draft feature names and the PDF-authoritative names:

| Previous (wrong) | Corrected (PDF-exact) |
|---|---|
| `customer_rto_count` | `customer_past_rto_count` |
| `pincode_rto_rate` | `pincode_historical_rto_rate` |
| `category_rto_rate` | `category_baseline_rto_rate` |
| `cart_value` + `order_value_anomaly` | `cart_value_category_std_dev` |
| `item_count` | `item_quantity_anomaly_score` |
| `is_discount_applied` | `is_night_order` |
| `order_velocity_1h` + `order_velocity_24h` | `phone_order_velocity_7d` |
| `device_type_mobile` | `device_account_reuse_count` |
| *(missing)* | `account_age_days` |
| `is_pincode_city_mismatch` | `hub_distance_km` |
| `is_cod` | `is_cod_selected` |

The script was rewritten before any CSVs were generated.

**Instructions updated:** Section `1a` in `instructions .md` now points to
`docs/pdf_extract.txt` (the pre-extracted text) as the authoritative source reference.
The `ideation/` folder was removed from the repo.

---

## Implementation Steps Executed

### 1. `scripts/generate_data.py` (created + PDF-verified)

- 15 PDF-authoritative features across 5 signal families.
- Seeded splits: train=101, val=202, heldout=303.
- Heldout covariate shift: `is_novel_pincode=1` + `is_flash_sale_cart_value=1` on
  exactly 10% of rows (pincodes PIN_091–PIN_100, unseen in train/val).
- Historical rates (`pincode_historical_rto_rate`, `category_baseline_rto_rate`)
  computed STRICTLY from train.csv COD rows — function `compute_historical_rates()`.
- Rates serialised to `config/historical_rates.json` for Day 3 feature pipeline.

### 2. Data generation run (local, outside Docker)

```
train: rows=5,000  COD%=61.6%  RTO-in-COD%=24.0%  RTO_count=739  novel=0
val:   rows=750    COD%=61.5%  RTO-in-COD%=23.9%  RTO_count=110  novel=0
held:  rows=1,250  COD%=61.4%  RTO-in-COD%=24.0%  RTO_count=184  novel=125
```

All three splits pass the composition spec (62% ±5pp COD, 24% ±5pp RTO-in-COD).

### 3. Issue #12 — Val positive class count

val.csv RTO=1 count: **110** — below 150.  
Per the plan, **Day 5 bootstrap stability check is MANDATORY**.  
Flagged in `data/generation_report.md`.

### 4. `tests/test_data_integrity.py` (created)

Covers all 7 acceptance criteria:

| Test class | Criterion |
|---|---|
| `TestSchema` | All 15 PDF features present; correct row counts |
| `TestNoIDOverlap` | Zero order_id overlap across all 3 splits |
| `TestDistributions` | COD ratio and RTO-in-COD within ±5pp |
| `TestValPositiveClass` | val RTO=1 count > 0; actual count printed |
| `TestCovariateShift` | Heldout shift ≈10% ±2pp; novel+flash flags aligned |
| `TestNoDriftLeakage` | Train/val have zero drift indicator rows |
| `TestHistoricalRateTrainOnly` | Mock-patch confirms function called once with 5000-row train |

### 5. Minor fixes

- Two `UnicodeEncodeError` on Windows cp1252 terminal fixed (emoji in print + report write).
- `data/generation_report.md` written with `encoding='utf-8'`.

---

## Deliverables Produced

| File | Status |
|---|---|
| `scripts/generate_data.py` | Created (PDF-verified) |
| `data/train.csv` | Generated (5,000 rows, seed=101) |
| `data/val.csv` | Generated (750 rows, seed=202) |
| `data/heldout.csv` | Generated (1,250 rows, seed=303) |
| `data/generation_report.md` | Generated (per-split stats + issue #12 flag) |
| `config/historical_rates.json` | Generated (train-only rates for Day 3) |
| `tests/test_data_integrity.py` | Created (7 test classes, 17 test functions) |
| `docs/pdf_extract.txt` | Moved from ideation/ — authoritative spec reference |
| `instructions .md` §1a | Updated — PDF rule now points to pdf_extract.txt |

---

## Validation

**Command run (inside Docker container):**
```bash
docker compose exec api python -m pytest tests/test_data_integrity.py -v -s
```

**Result: 23/23 PASSED in 13.50s** — platform: Linux, Python 3.11.16

```
TestSchema::test_train_columns                                    PASSED
TestSchema::test_val_columns                                      PASSED
TestSchema::test_heldout_columns                                  PASSED
TestSchema::test_train_row_count                                  PASSED
TestSchema::test_val_row_count                                    PASSED
TestSchema::test_heldout_row_count                                PASSED
TestNoIDOverlap::test_train_val_no_overlap                        PASSED
TestNoIDOverlap::test_train_heldout_no_overlap                    PASSED
TestNoIDOverlap::test_val_heldout_no_overlap                      PASSED
TestDistributions::test_cod_ratio[train-train_df]                 PASSED
TestDistributions::test_cod_ratio[val-val_df]                     PASSED
TestDistributions::test_cod_ratio[heldout-heldout_df]             PASSED
TestDistributions::test_rto_in_cod_ratio[train-train_df]          PASSED
TestDistributions::test_rto_in_cod_ratio[val-val_df]              PASSED
TestDistributions::test_rto_in_cod_ratio[heldout-heldout_df]      PASSED
TestValPositiveClass::test_val_has_positive_rto_rows              PASSED
  [issue #12] val.csv RTO=1 count: 110  — WARNING < 150, Day 5 bootstrap MANDATORY
TestCovariateShift::test_heldout_shift_fraction                   PASSED
TestCovariateShift::test_heldout_novel_and_flash_aligned          PASSED
TestNoDriftLeakage::test_train_no_novel_pincode                   PASSED
TestNoDriftLeakage::test_train_no_flash_sale                      PASSED
TestNoDriftLeakage::test_val_no_novel_pincode                     PASSED
TestNoDriftLeakage::test_val_no_flash_sale                        PASSED
TestHistoricalRateTrainOnly::test_compute_historical_rates_...    PASSED
```

---

## Issues / Decisions

| # | Issue | Resolution |
|---|---|---|
| D2-01 | 7 feature name mismatches vs PDF | Rewrote generator before any CSV produced |
| D2-02 | Windows cp1252 UnicodeEncodeError | Replaced emojis in print/file write; added `encoding='utf-8'` |
| D2-03 | val.csv has only 110 RTO=1 rows (< 150) | Flagged per issue #12; Day 5 bootstrap check MANDATORY |

---

## Next: Day 3

Day 3 — Feature Engineering Pipeline:
- Build `app/feature_pipeline.py` consuming `config/historical_rates.json`.
- Implement sub-10ms TF-IDF address ambiguity engine (fitted at startup).
- Write `tests/test_feature_pipeline.py`.
