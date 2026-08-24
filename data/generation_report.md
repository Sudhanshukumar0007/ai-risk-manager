# Day 02 — Data Generation Report

_Source authority: `ideation/Ten Day Implementation Plan Roadmap.pdf` (feature table)_

## Split Summary

| Split | Rows | COD % | RTO % (in COD) | RTO=1 Count | Novel-Pincode Rows | Seed |
|---|---|---|---|---|---|---|
| **train**   | 5,000 | 61.6% | 24.0% | 739 | 0 | 101 |
| **val**     |   750 | 61.5% | 23.9% | 110 | 0 | 202 |
| **heldout** | 1,250 | 61.4% | 24.0% | 184 | 125 | 303 |

## Feature Families — PDF-authoritative (15 features)

| # | PDF Feature Name | Signal Family |
|---|---|---|
| 1 | `customer_past_rto_count` | Delivery History |
| 2 | `pincode_historical_rto_rate` | Delivery History |
| 3 | `category_baseline_rto_rate` | Delivery History |
| 4 | `cart_value_category_std_dev` | Order Anomaly |
| 5 | `item_quantity_anomaly_score` | Order Anomaly |
| 6 | `is_night_order` | Order Anomaly |
| 7 | `phone_order_velocity_7d` | Identity & Velocity |
| 8 | `device_account_reuse_count` | Identity & Velocity |
| 9 | `account_age_days` | Identity & Velocity |
| 10 | `address_char_length` | Address Quality |
| 11 | `address_tfidf_ambiguity_score` | Address Quality |
| 12 | `hub_distance_km` | Address Quality |
| 13 | `is_cod_selected` | Payment Context |
| 14 | `is_novel_pincode` | Drift Indicators |
| 15 | `is_flash_sale_cart_value` | Drift Indicators |

## Covariate Shift Injection (heldout.csv only)

- `125` rows (≈10%) in `heldout.csv` have `is_novel_pincode=1` AND
  `is_flash_sale_cart_value=1`.
- These rows use pincodes `PIN_091–PIN_100`, absent from train/val.
- Cart value z-scores inflated 2.5× to simulate flash-sale behaviour.

## Historical Rate Computation

- `pincode_historical_rto_rate` and `category_baseline_rto_rate` derived
  **strictly from `train.csv`** (COD rows only).
- Global fallback rate for unseen pincodes: `0.2399`
- Serialised to: `config/historical_rates.json`

## Issue #12 — Validation Positive-Class Count

val.csv RTO=1 count: **110**

⚠️  BELOW 150 — Day 5 bootstrap stability check is MANDATORY.
