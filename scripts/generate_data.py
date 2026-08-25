"""
Day 2 — Synthetic Data Engine  (PDF-verified)
==============================================
Generates three isolated, seeded CSV splits with exactly 15 features across
five signal families, using the EXACT feature names from the source PDF:

  ideation/Ten Day Implementation Plan Roadmap.pdf
  (pre-extracted to: docs/pdf_extract.txt — ideation/ folder no longer exists)

Signal families and feature names (PDF authoritative):
  1. Delivery History    — pincode_historical_rto_rate, customer_past_rto_count,
                           category_baseline_rto_rate
  2. Order Anomaly       — cart_value_category_std_dev, item_quantity_anomaly_score,
                           is_night_order
  3. Identity & Velocity — phone_order_velocity_7d, device_account_reuse_count,
                           account_age_days
  4. Address Quality     — address_char_length, address_tfidf_ambiguity_score,
                           hub_distance_km
  5. Payment Context     — is_cod_selected
  6. Drift Indicators    — is_novel_pincode, is_flash_sale_cart_value

Constraints (non-negotiable per plan):
  - train.csv   : 5,000 rows, seed=101
  - val.csv     :   750 rows, seed=202
  - heldout.csv : 1,250 rows, seed=303
  - ~62% COD ratio across all splits
  - ~24% RTO rate within COD orders
  - Covariate shift (is_novel_pincode=1 + is_flash_sale_cart_value=1) on
    exactly 10% of heldout.csv ONLY — never in train or val.
  - Historical pincode/category RTO rates computed STRICTLY from train.csv.
"""

import json
import os

import numpy as np
import pandas as pd

# ── Constants ────────────────────────────────────────────────────────────────
CATEGORIES = ["Electronics", "Apparel", "Home", "Beauty", "Books"]
CATEGORY_WEIGHTS = [0.30, 0.35, 0.15, 0.10, 0.10]

# Category median cart values and 95th-pctile basket sizes (for anomaly scores)
CATEGORY_MEDIAN_CART = {
    "Electronics": 4500.0,
    "Apparel": 900.0,
    "Home": 1800.0,
    "Beauty": 600.0,
    "Books": 350.0,
}
CATEGORY_P95_BASKET = {  # item count 95th-pctile per category
    "Electronics": 3,
    "Apparel": 5,
    "Home": 4,
    "Beauty": 6,
    "Books": 4,
}

# 100 pincodes: PIN_001–PIN_090 appear in train/val.
# PIN_091–PIN_100 are "novel" — injected in heldout's shift subset only.
ALL_PINCODES = [f"PIN_{i:03d}" for i in range(1, 101)]
STANDARD_PINCODES = ALL_PINCODES[:90]
NOVEL_PINCODES = ALL_PINCODES[90:]

# Approximate hub distances (km) per pincode — deterministically seeded
HUB_DISTANCES_BASE = {p: 10 + (int(p.split("_")[1]) * 1.7) % 180 for p in ALL_PINCODES}

TARGET_COD_RATIO = 0.62
TARGET_RTO_IN_COD = 0.24
HELDOUT_SHIFT_FRACTION = 0.10


# ── Feature generation helpers ────────────────────────────────────────────────

def _family1_delivery_history(rng, n):
    """customer_past_rto_count (pincode/category rates added later from train)."""
    customer_past_rto_count = rng.negative_binomial(n=0.5, p=0.7, size=n)
    return customer_past_rto_count


def _family2_order_anomaly(rng, n, categories, is_flash_sale):
    """
    cart_value_category_std_dev  — z-score relative to category median
    item_quantity_anomaly_score  — ratio to category 95th-pctile basket
    is_night_order               — order placed 00:00–05:00 IST
    """
    raw_cart_value = rng.exponential(scale=1_500, size=n) + 150
    raw_cart_value = np.clip(raw_cart_value, 150, 20_000)

    # Inflate flash-sale rows (heldout shift)
    raw_cart_value[is_flash_sale == 1] = np.clip(
        raw_cart_value[is_flash_sale == 1] * 2.5, 150, 20_000
    )

    cat_medians = np.array([CATEGORY_MEDIAN_CART[c] for c in categories])
    cat_std = cat_medians * 0.5  # assume std ≈ 50% of median
    cart_value_category_std_dev = np.clip(
        (raw_cart_value - cat_medians) / cat_std, -4.0, 4.0
    )

    raw_item_count = rng.zipf(a=2.5, size=n)
    raw_item_count = np.clip(raw_item_count, 1, 10)
    cat_p95 = np.array([CATEGORY_P95_BASKET[c] for c in categories])
    item_quantity_anomaly_score = np.round(raw_item_count / cat_p95.astype(float), 4)

    # Night order: hour uniformly drawn from 0-23; flag if 0–4
    order_hour = rng.integers(0, 24, size=n)
    is_night_order = (order_hour < 5).astype(int)

    return (
        np.round(cart_value_category_std_dev, 4),
        item_quantity_anomaly_score,
        is_night_order,
        raw_cart_value,  # returned only for RTO logit
    )


def _family3_identity_velocity(rng, n):
    """
    phone_order_velocity_7d    — total orders linked to phone number in 7 days
    device_account_reuse_count — distinct account IDs per device fingerprint
    account_age_days           — days since account registration
    """
    phone_order_velocity_7d = rng.poisson(lam=2.5, size=n)
    device_account_reuse_count = rng.negative_binomial(n=0.4, p=0.8, size=n) + 1
    account_age_days = rng.exponential(scale=300, size=n).astype(int)
    account_age_days = np.clip(account_age_days, 0, 3000)
    return phone_order_velocity_7d, device_account_reuse_count, account_age_days


def _family4_address_quality(rng, n, pincodes):
    """
    address_char_length          — raw character length of address string
    address_tfidf_ambiguity_score — cosine similarity to bad-address matrix [0,1]
                                  (NOTE: Generated synthetically offline. True TF-IDF parity is not in scope for the simulation.)
    hub_distance_km              — geodesic distance to nearest fulfillment hub
    """
    address_char_length = rng.normal(loc=45, scale=15, size=n).astype(int)
    address_char_length = np.clip(address_char_length, 10, 150)

    address_tfidf_ambiguity_score = rng.beta(a=2, b=5, size=n)

    base_dist = np.array([HUB_DISTANCES_BASE[p] for p in pincodes], dtype=float)
    jitter = rng.normal(loc=0, scale=8, size=n)
    hub_distance_km = np.clip(base_dist + jitter, 1.0, 350.0)

    return (
        address_char_length,
        np.round(address_tfidf_ambiguity_score, 4),
        np.round(hub_distance_km, 2),
    )


def _build_rto_logit(
    categories,
    customer_past_rto_count,
    phone_order_velocity_7d,
    address_tfidf_ambiguity_score,
    hub_distance_km,
    address_char_length,
    account_age_days,
    device_account_reuse_count,
    is_novel_pincode,
    is_flash_sale_cart_value,
):
    """
    Deterministic logit combining all feature families.
    Calibrated so ~24% of COD rows become RTO=1 after rank-based thresholding.
    """
    cat_vec = np.array(categories)
    logit = (
        -1.30
        + 1.60 * (cat_vec == "Electronics").astype(float)
        + 1.00 * (cat_vec == "Apparel").astype(float)
        + 0.70 * np.clip(customer_past_rto_count, 0, 5)
        + 0.40 * np.log1p(phone_order_velocity_7d)
        + 2.00 * address_tfidf_ambiguity_score
        + 0.003 * np.clip(hub_distance_km, 0, 350)
        - 0.008 * np.clip(address_char_length, 10, 150)
        - 0.001 * np.clip(account_age_days, 0, 3000)
        + 0.50 * np.clip(device_account_reuse_count - 1, 0, 5)
        + 0.70 * is_novel_pincode
        + 0.50 * is_flash_sale_cart_value
    )
    return logit


# ── Main split generator ──────────────────────────────────────────────────────

def generate_split(n_rows: int, seed: int, is_heldout: bool = False) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    # ── order IDs ──────────────────────────────────────────────────────────
    order_ids = [f"ORD_{seed}_{i:05d}" for i in range(n_rows)]

    # ── categories ─────────────────────────────────────────────────────────
    categories = rng.choice(CATEGORIES, size=n_rows, p=CATEGORY_WEIGHTS)

    # ── pincodes + drift indicators ────────────────────────────────────────
    if is_heldout:
        n_shift = int(n_rows * HELDOUT_SHIFT_FRACTION)
        n_standard = n_rows - n_shift
        standard_pins = rng.choice(STANDARD_PINCODES, size=n_standard)
        novel_pins = rng.choice(NOVEL_PINCODES, size=n_shift)
        pincodes_arr = np.concatenate([standard_pins, novel_pins])
        idx_shuffle = rng.permutation(n_rows)
        pincodes_arr = pincodes_arr[idx_shuffle]
        is_novel_pincode = (
            np.array([int(p.split("_")[1]) for p in pincodes_arr]) > 90
        ).astype(int)
        is_flash_sale_cart_value = is_novel_pincode.copy()  # co-injected per plan
    else:
        pincodes_arr = rng.choice(STANDARD_PINCODES, size=n_rows)
        is_novel_pincode = np.zeros(n_rows, dtype=int)
        is_flash_sale_cart_value = np.zeros(n_rows, dtype=int)

    # ── feature families ───────────────────────────────────────────────────
    # Family 1
    customer_past_rto_count = _family1_delivery_history(rng, n_rows)

    # Family 2
    (
        cart_value_category_std_dev,
        item_quantity_anomaly_score,
        is_night_order,
        raw_cart_value,
    ) = _family2_order_anomaly(rng, n_rows, categories, is_flash_sale_cart_value)

    # Family 3
    phone_order_velocity_7d, device_account_reuse_count, account_age_days = (
        _family3_identity_velocity(rng, n_rows)
    )

    # Family 4
    address_char_length, address_tfidf_ambiguity_score, hub_distance_km = (
        _family4_address_quality(rng, n_rows, pincodes_arr)
    )

    # ── payment method (~62% COD) ──────────────────────────────────────────
    is_cod_selected = rng.binomial(n=1, p=TARGET_COD_RATIO, size=n_rows)

    # ── RTO label: target exactly 24% within COD ───────────────────────────
    logit = _build_rto_logit(
        categories, customer_past_rto_count, phone_order_velocity_7d,
        address_tfidf_ambiguity_score, hub_distance_km,
        address_char_length, account_age_days,
        device_account_reuse_count, is_novel_pincode, is_flash_sale_cart_value,
    )
    prob = 1.0 / (1.0 + np.exp(-logit))

    is_rto = np.zeros(n_rows, dtype=int)
    cod_idx = np.where(is_cod_selected == 1)[0]
    n_target_rto = int(len(cod_idx) * TARGET_RTO_IN_COD)
    if n_target_rto > 0:
        top_rto_idx = cod_idx[np.argsort(prob[cod_idx])[-n_target_rto:]]
        is_rto[top_rto_idx] = 1

    df = pd.DataFrame({
        "order_id": order_ids,
        "pincode": pincodes_arr,
        "category": categories,
        # Family 1 — Delivery History
        "customer_past_rto_count": customer_past_rto_count,
        # pincode_historical_rto_rate + category_baseline_rto_rate added after
        # train-side rate computation (see attach_historical_rates)
        # Family 2 — Order Anomaly
        "cart_value_category_std_dev": cart_value_category_std_dev,
        "item_quantity_anomaly_score": item_quantity_anomaly_score,
        "is_night_order": is_night_order,
        # Family 3 — Identity & Velocity
        "phone_order_velocity_7d": phone_order_velocity_7d,
        "device_account_reuse_count": device_account_reuse_count,
        "account_age_days": account_age_days,
        # Family 4 — Address Quality
        "address_char_length": address_char_length,
        "address_tfidf_ambiguity_score": address_tfidf_ambiguity_score,
        "hub_distance_km": hub_distance_km,
        # Family 5 — Payment Context
        "is_cod_selected": is_cod_selected,
        # Family 6 — Drift Indicators
        "is_novel_pincode": is_novel_pincode,
        "is_flash_sale_cart_value": is_flash_sale_cart_value,
        # Target
        "is_rto": is_rto,
    })

    return df


# ── Historical rate computation (train-only) ──────────────────────────────────

def compute_historical_rates(train_df: pd.DataFrame) -> dict:
    """
    Compute pincode- and category-level RTO rates STRICTLY from train_df.

    Must never receive val.csv or heldout.csv as input.
    The unit test in tests/test_data_integrity.py enforces this via a
    call-count assertion.
    """
    cod = train_df[train_df["is_cod_selected"] == 1]
    pincode_rates = cod.groupby("pincode")["is_rto"].mean().to_dict()
    category_rates = cod.groupby("category")["is_rto"].mean().to_dict()
    global_rate = float(cod["is_rto"].mean()) if len(cod) > 0 else TARGET_RTO_IN_COD
    return {
        "pincode_rto_rates": pincode_rates,
        "category_rto_rates": category_rates,
        "global_cod_rto_rate": global_rate,
    }


def attach_historical_rates(df: pd.DataFrame, rates: dict) -> pd.DataFrame:
    """
    Map pre-computed train-side rates onto any split (train, val, heldout).
    Uses global fallback for pincodes/categories unseen in train.
    """
    global_rate = rates["global_cod_rto_rate"]
    df = df.copy()
    df["pincode_historical_rto_rate"] = (
        df["pincode"].map(rates["pincode_rto_rates"]).fillna(global_rate)
    )
    df["category_baseline_rto_rate"] = (
        df["category"].map(rates["category_rto_rates"]).fillna(global_rate)
    )
    return df


# ── Canonical column order ────────────────────────────────────────────────────

FEATURE_COLUMNS = [
    # Identifiers
    "order_id", "pincode", "category",
    # Family 1 — Delivery History
    "customer_past_rto_count",
    "pincode_historical_rto_rate",
    "category_baseline_rto_rate",
    # Family 2 — Order Anomaly
    "cart_value_category_std_dev",
    "item_quantity_anomaly_score",
    "is_night_order",
    # Family 3 — Identity & Velocity
    "phone_order_velocity_7d",
    "device_account_reuse_count",
    "account_age_days",
    # Family 4 — Address Quality
    "address_char_length",
    "address_tfidf_ambiguity_score",
    "hub_distance_km",
    # Family 5 — Payment Context
    "is_cod_selected",
    # Family 6 — Drift Indicators
    "is_novel_pincode",
    "is_flash_sale_cart_value",
    # Target (always last)
    "is_rto",
]


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 65)
    print("Day 2 — Synthetic Data Engine  (PDF-verified feature names)")
    print("=" * 65)

    # Step 1: Generate raw splits
    print("\nGenerating splits...")
    train_df = generate_split(5_000, seed=101, is_heldout=False)
    val_df   = generate_split(750,   seed=202, is_heldout=False)
    heldout_df = generate_split(1_250, seed=303, is_heldout=True)

    # Step 2: Historical rates STRICTLY from train
    print("Computing historical RTO rates from train.csv only...")
    rates = compute_historical_rates(train_df)

    # Step 3: Attach derived features to all splits
    train_df   = attach_historical_rates(train_df, rates)
    val_df     = attach_historical_rates(val_df, rates)
    heldout_df = attach_historical_rates(heldout_df, rates)

    # Step 4: Canonical column order
    train_df   = train_df[FEATURE_COLUMNS]
    val_df     = val_df[FEATURE_COLUMNS]
    heldout_df = heldout_df[FEATURE_COLUMNS]

    # Step 5: Save CSVs
    os.makedirs("data", exist_ok=True)
    train_df.to_csv("data/train.csv", index=False)
    val_df.to_csv("data/val.csv", index=False)
    heldout_df.to_csv("data/heldout.csv", index=False)
    print("Saved: data/train.csv, data/val.csv, data/heldout.csv")

    # Step 6: Save historical rates for Day 3 feature pipeline
    os.makedirs("config", exist_ok=True)
    with open("config/historical_rates.json", "w") as f:
        json.dump(rates, f, indent=2)
    print("Saved: config/historical_rates.json")

    with open("config/feature_constants.json", "w") as f:
        json.dump({
            "CATEGORY_MEDIAN_CART": CATEGORY_MEDIAN_CART,
            "CATEGORY_P95_BASKET": CATEGORY_P95_BASKET,
            "HUB_DISTANCES_BASE": HUB_DISTANCES_BASE,
            "NOVEL_PINCODES": NOVEL_PINCODES,
        }, f, indent=2)
    print("Saved: config/feature_constants.json")

    # Step 7: Composition stats + Issue #12 check
    def split_stats(df, name):
        cod_ratio = df["is_cod_selected"].mean()
        cod_df = df[df["is_cod_selected"] == 1]
        rto_in_cod = cod_df["is_rto"].mean() if len(cod_df) > 0 else 0.0
        total_rto = int(df["is_rto"].sum())
        novel_count = int(df["is_novel_pincode"].sum())
        print(
            f"  {name:>8s}: rows={len(df):,}  COD%={cod_ratio:.1%}  "
            f"RTO-in-COD%={rto_in_cod:.1%}  RTO_count={total_rto}  "
            f"novel_pincode_rows={novel_count}"
        )
        return cod_ratio, rto_in_cod, total_rto, novel_count

    print("\nDataset composition:")
    t_cod, t_rto, t_total_rto, t_novel = split_stats(train_df, "train")
    v_cod, v_rto, v_total_rto, v_novel = split_stats(val_df, "val")
    h_cod, h_rto, h_total_rto, h_novel = split_stats(heldout_df, "heldout")

    if v_total_rto < 150:
        print(
            f"\n  [WARNING issue #12]: val.csv has only {v_total_rto} RTO=1 rows. "
            f"Day 5 grid search bootstrap stability check is MANDATORY."
        )

    # Step 8: generation_report.md
    global_rate = rates["global_cod_rto_rate"]
    report = f"""# Day 02 — Data Generation Report

_Source authority: `ideation/Ten Day Implementation Plan Roadmap.pdf` (feature table)_

## Split Summary

| Split | Rows | COD % | RTO % (in COD) | RTO=1 Count | Novel-Pincode Rows | Seed |
|---|---|---|---|---|---|---|
| **train**   | 5,000 | {t_cod:.1%} | {t_rto:.1%} | {t_total_rto} | 0 | 101 |
| **val**     |   750 | {v_cod:.1%} | {v_rto:.1%} | {v_total_rto} | 0 | 202 |
| **heldout** | 1,250 | {h_cod:.1%} | {h_rto:.1%} | {h_total_rto} | {h_novel} | 303 |

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

- `{h_novel}` rows (≈10%) in `heldout.csv` have `is_novel_pincode=1` AND
  `is_flash_sale_cart_value=1`.
- These rows use pincodes `PIN_091–PIN_100`, absent from train/val.
- Cart value z-scores inflated 2.5× to simulate flash-sale behaviour.

## Historical Rate Computation

- `pincode_historical_rto_rate` and `category_baseline_rto_rate` derived
  **strictly from `train.csv`** (COD rows only).
- Global fallback rate for unseen pincodes: `{global_rate:.4f}`
- Serialised to: `config/historical_rates.json`

## Issue #12 — Validation Positive-Class Count

val.csv RTO=1 count: **{v_total_rto}**

{"⚠️  BELOW 150 — Day 5 bootstrap stability check is MANDATORY." if v_total_rto < 150 else "✅  Above 150 — acceptable for Day 5 grid search."}
"""

    with open("data/generation_report.md", "w", encoding="utf-8") as f:
        f.write(report)
    print("\nSaved: data/generation_report.md")
    print("\n[OK] Day 2 data generation complete.")


if __name__ == "__main__":
    main()
