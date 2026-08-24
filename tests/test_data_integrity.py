"""
Day 2 — Acceptance Tests: Data Integrity
==========================================
Acceptance criteria (from implementation_plan.md Day 2):

  (a) Zero order_id overlap across the three splits.
  (b) Target distributions match spec within tolerance:
        - COD ratio:      62% ± 5 percentage points
        - RTO-in-COD:     24% ± 5 percentage points
  (c) Positive-class count in val.csv > 0 (printed for manual sanity review).
  (d) Covariate shift rows in heldout.csv are exactly ~10% (±2pp).
  (e) is_novel_pincode and is_flash_sale_cart_value are always 0 in train/val.
  (f) Historical RTO rate computation reads train.csv ONLY — verified via
      mock-patching compute_historical_rates to count its calls.
  (g) All 15 PDF-authoritative feature columns are present in every split.
"""

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
TRAIN_PATH = DATA_DIR / "train.csv"
VAL_PATH = DATA_DIR / "val.csv"
HELDOUT_PATH = DATA_DIR / "heldout.csv"

# ── Expected feature columns (PDF-authoritative) ──────────────────────────────
EXPECTED_FEATURES = [
    "order_id",
    "pincode",
    "category",
    "customer_past_rto_count",
    "pincode_historical_rto_rate",
    "category_baseline_rto_rate",
    "cart_value_category_std_dev",
    "item_quantity_anomaly_score",
    "is_night_order",
    "phone_order_velocity_7d",
    "device_account_reuse_count",
    "account_age_days",
    "address_char_length",
    "address_tfidf_ambiguity_score",
    "hub_distance_km",
    "is_cod_selected",
    "is_novel_pincode",
    "is_flash_sale_cart_value",
    "is_rto",
]

TOLERANCE_PP = 0.05  # ±5 percentage points


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def train_df():
    assert TRAIN_PATH.exists(), f"Missing: {TRAIN_PATH}"
    return pd.read_csv(TRAIN_PATH)


@pytest.fixture(scope="module")
def val_df():
    assert VAL_PATH.exists(), f"Missing: {VAL_PATH}"
    return pd.read_csv(VAL_PATH)


@pytest.fixture(scope="module")
def heldout_df():
    assert HELDOUT_PATH.exists(), f"Missing: {HELDOUT_PATH}"
    return pd.read_csv(HELDOUT_PATH)


# ── (g) Schema ────────────────────────────────────────────────────────────────

class TestSchema:
    def test_train_columns(self, train_df):
        missing = set(EXPECTED_FEATURES) - set(train_df.columns)
        assert not missing, f"train.csv missing columns: {missing}"

    def test_val_columns(self, val_df):
        missing = set(EXPECTED_FEATURES) - set(val_df.columns)
        assert not missing, f"val.csv missing columns: {missing}"

    def test_heldout_columns(self, heldout_df):
        missing = set(EXPECTED_FEATURES) - set(heldout_df.columns)
        assert not missing, f"heldout.csv missing columns: {missing}"

    def test_train_row_count(self, train_df):
        assert len(train_df) == 5_000, f"Expected 5000 rows, got {len(train_df)}"

    def test_val_row_count(self, val_df):
        assert len(val_df) == 750, f"Expected 750 rows, got {len(val_df)}"

    def test_heldout_row_count(self, heldout_df):
        assert len(heldout_df) == 1_250, f"Expected 1250 rows, got {len(heldout_df)}"


# ── (a) Zero ID overlap ───────────────────────────────────────────────────────

class TestNoIDOverlap:
    def test_train_val_no_overlap(self, train_df, val_df):
        overlap = set(train_df["order_id"]) & set(val_df["order_id"])
        assert len(overlap) == 0, f"train/val share {len(overlap)} order_ids: {list(overlap)[:5]}"

    def test_train_heldout_no_overlap(self, train_df, heldout_df):
        overlap = set(train_df["order_id"]) & set(heldout_df["order_id"])
        assert len(overlap) == 0, f"train/heldout share {len(overlap)} order_ids"

    def test_val_heldout_no_overlap(self, val_df, heldout_df):
        overlap = set(val_df["order_id"]) & set(heldout_df["order_id"])
        assert len(overlap) == 0, f"val/heldout share {len(overlap)} order_ids"


# ── (b) Distribution spec ─────────────────────────────────────────────────────

class TestDistributions:
    @pytest.mark.parametrize("split_name,fixture_name", [
        ("train", "train_df"),
        ("val",   "val_df"),
        ("heldout", "heldout_df"),
    ])
    def test_cod_ratio(self, split_name, fixture_name, request):
        df = request.getfixturevalue(fixture_name)
        cod_ratio = df["is_cod_selected"].mean()
        assert abs(cod_ratio - 0.62) <= TOLERANCE_PP, (
            f"{split_name}.csv COD ratio={cod_ratio:.3f}, expected 0.62 ±{TOLERANCE_PP}"
        )

    @pytest.mark.parametrize("split_name,fixture_name", [
        ("train", "train_df"),
        ("val",   "val_df"),
        ("heldout", "heldout_df"),
    ])
    def test_rto_in_cod_ratio(self, split_name, fixture_name, request):
        df = request.getfixturevalue(fixture_name)
        cod_df = df[df["is_cod_selected"] == 1]
        rto_in_cod = cod_df["is_rto"].mean()
        assert abs(rto_in_cod - 0.24) <= TOLERANCE_PP, (
            f"{split_name}.csv RTO-in-COD={rto_in_cod:.3f}, expected 0.24 ±{TOLERANCE_PP}"
        )


# ── (c) Positive class count in val (issue #12) ───────────────────────────────

class TestValPositiveClass:
    def test_val_has_positive_rto_rows(self, val_df):
        """Acceptance criterion: val positive count > 0. Actual count printed for manual review."""
        rto_count = int(val_df["is_rto"].sum())
        print(f"\n[issue #12] val.csv RTO=1 count: {rto_count}")
        if rto_count < 150:
            print(
                f"  [WARNING] val RTO count ({rto_count}) < 150. "
                "Day 5 bootstrap stability check is MANDATORY."
            )
        assert rto_count > 0, "val.csv has zero RTO=1 rows — data generation is broken"


# ── (d) Covariate shift in heldout ───────────────────────────────────────────

class TestCovariateShift:
    def test_heldout_shift_fraction(self, heldout_df):
        shift_frac = heldout_df["is_novel_pincode"].mean()
        assert abs(shift_frac - 0.10) <= 0.02, (
            f"heldout shift fraction={shift_frac:.3f}, expected 0.10 ±0.02"
        )

    def test_heldout_novel_and_flash_aligned(self, heldout_df):
        """is_novel_pincode and is_flash_sale_cart_value must be identical in heldout."""
        mismatch = (
            heldout_df["is_novel_pincode"] != heldout_df["is_flash_sale_cart_value"]
        ).sum()
        assert mismatch == 0, (
            f"{mismatch} rows in heldout.csv have mismatched novel_pincode/flash_sale flags"
        )


# ── (e) No drift in train or val ─────────────────────────────────────────────

class TestNoDriftLeakage:
    def test_train_no_novel_pincode(self, train_df):
        count = int(train_df["is_novel_pincode"].sum())
        assert count == 0, f"train.csv has {count} rows with is_novel_pincode=1 (must be 0)"

    def test_train_no_flash_sale(self, train_df):
        count = int(train_df["is_flash_sale_cart_value"].sum())
        assert count == 0, f"train.csv has {count} rows with is_flash_sale_cart_value=1"

    def test_val_no_novel_pincode(self, val_df):
        count = int(val_df["is_novel_pincode"].sum())
        assert count == 0, f"val.csv has {count} rows with is_novel_pincode=1 (must be 0)"

    def test_val_no_flash_sale(self, val_df):
        count = int(val_df["is_flash_sale_cart_value"].sum())
        assert count == 0, f"val.csv has {count} rows with is_flash_sale_cart_value=1"


# ── (f) Historical rates computed from train only ─────────────────────────────

class TestHistoricalRateTrainOnly:
    def test_compute_historical_rates_called_once_with_train_only(self):
        """
        Verify that compute_historical_rates is called exactly once during
        generate_data.main() and receives a DataFrame of the expected train size (5000).
        Val/heldout DataFrames must never be passed to it.
        """
        sys.path.insert(0, str(ROOT / "scripts"))
        import generate_data as gd

        call_args = []
        original_fn = gd.compute_historical_rates

        def recording_wrapper(df):
            call_args.append(len(df))
            return original_fn(df)

        with patch.object(gd, "compute_historical_rates", side_effect=recording_wrapper):
            # Re-run main in a temp dir context so it doesn't overwrite real files
            import os, tempfile
            with tempfile.TemporaryDirectory() as tmpdir:
                orig_dir = os.getcwd()
                os.chdir(tmpdir)
                os.makedirs("data", exist_ok=True)
                os.makedirs("config", exist_ok=True)
                try:
                    gd.main()
                finally:
                    os.chdir(orig_dir)

        assert len(call_args) == 1, (
            f"compute_historical_rates was called {len(call_args)} times; expected exactly 1"
        )
        assert call_args[0] == 5_000, (
            f"compute_historical_rates received {call_args[0]} rows; expected 5000 (train only)"
        )
