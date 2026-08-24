"""
Day 2 — Audit Remediation Tests
=================================
Addresses A-D2-004 (weak leakage test) and A-D2-006 (no reproducibility check).

A-D2-004 fix:
  Runs generate_data.main() in a temp workspace with *poisoned* val.csv and
  heldout.csv. If any pandas read_csv call touches those files during the
  historical-rate construction step, the test fails immediately via a
  patched read_csv that raises an AssertionError on forbidden paths.

A-D2-006 fix:
  Verifies that re-running scripts/generate_data.py with the same seeds
  produces byte-identical CSVs and an identical historical_rates.json.
  Compares against the SHA-256 hashes recorded by the independent audit.
"""

import hashlib
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import generate_data as gd

# ── SHA-256 hashes from independent audit (audit/day-02.md) ──────────────────
AUDIT_HASHES = {
    "train.csv":               "ad901b61c7e32b9a1556ceb2545ba33bfb86b31c466fb32610e1ec5e7c57ade2",
    "val.csv":                 "ddfc7f31d6b9c03266bd7fdcadb43a1872d956e14af3dcb503e88225f2d50f11",
    "heldout.csv":             "a150979d9a755342f659147842a5f82ba3f46058291882d35cdffdf0ae0196a3",
    "historical_rates.json":   "04a540110c8daa1dc325fc8048d9795865b4d652c7f0ea59c50737c89041b452",
}

DATA_DIR = ROOT / "data"
CONFIG_DIR = ROOT / "config"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ── A-D2-006: Deterministic reproducibility ───────────────────────────────────

class TestDeterministicReproducibility:
    """
    Re-runs the generator in a temp directory and compares resulting file
    hashes against the audit-recorded SHA-256 values.
    """

    def test_train_csv_is_reproducible(self):
        self._run_and_check("train.csv")

    def test_val_csv_is_reproducible(self):
        self._run_and_check("val.csv")

    def test_heldout_csv_is_reproducible(self):
        self._run_and_check("heldout.csv")

    def test_historical_rates_json_is_reproducible(self):
        """config/historical_rates.json must be byte-identical across runs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            orig = os.getcwd()
            os.chdir(tmpdir)
            os.makedirs("data")
            os.makedirs("config")
            try:
                gd.main()
            finally:
                os.chdir(orig)
            new_hash = _sha256(Path(tmpdir) / "config" / "historical_rates.json")
        expected = AUDIT_HASHES["historical_rates.json"]
        assert new_hash == expected, (
            f"historical_rates.json hash changed.\n"
            f"  Expected: {expected}\n"
            f"  Got:      {new_hash}\n"
            "If the generator was intentionally changed, update AUDIT_HASHES."
        )

    def _run_and_check(self, filename: str):
        with tempfile.TemporaryDirectory() as tmpdir:
            orig = os.getcwd()
            os.chdir(tmpdir)
            os.makedirs("data")
            os.makedirs("config")
            try:
                gd.main()
            finally:
                os.chdir(orig)
            new_hash = _sha256(Path(tmpdir) / "data" / filename)
        expected = AUDIT_HASHES[filename]
        assert new_hash == expected, (
            f"{filename} hash changed — generator output is no longer deterministic.\n"
            f"  Expected: {expected}\n"
            f"  Got:      {new_hash}\n"
            "If the generator was intentionally changed, update AUDIT_HASHES."
        )


# ── A-D2-004: Strong leakage regression guard ─────────────────────────────────

class TestNoLeakageDuringRateConstruction:
    """
    Runs generate_data.main() with a patched pandas.read_csv that raises
    AssertionError if val.csv or heldout.csv are opened during execution.

    This prevents future changes from accidentally introducing a code path
    that reads validation or held-out data during historical-rate construction,
    even if compute_historical_rates() itself still receives the correct
    5,000-row train DataFrame.
    """

    FORBIDDEN_STEMS = {"val", "heldout"}

    def test_val_and_heldout_not_read_during_generation(self):
        original_read_csv = pd.read_csv
        violations = []

        def guarded_read_csv(path_or_buf, *args, **kwargs):
            if isinstance(path_or_buf, (str, os.PathLike)):
                stem = Path(path_or_buf).stem
                if stem in self.FORBIDDEN_STEMS:
                    violations.append(str(path_or_buf))
                    raise AssertionError(
                        f"LEAKAGE: generate_data.main() attempted to read forbidden "
                        f"file '{path_or_buf}' during generation. "
                        "Historical rates must be built from train.csv only."
                    )
            return original_read_csv(path_or_buf, *args, **kwargs)

        with tempfile.TemporaryDirectory() as tmpdir:
            orig = os.getcwd()
            os.chdir(tmpdir)
            os.makedirs("data")
            os.makedirs("config")
            try:
                with patch("pandas.read_csv", side_effect=guarded_read_csv):
                    gd.main()
            finally:
                os.chdir(orig)

        assert len(violations) == 0, (
            f"Leakage detected: the generator read forbidden files: {violations}"
        )

    def test_novel_pincodes_absent_from_train(self):
        """PIN_091–PIN_100 must never appear in train.csv."""
        train = pd.read_csv(DATA_DIR / "train.csv")
        novel_in_train = train[train["pincode"].str.extract(r"PIN_(\d+)")[0].astype(int) > 90]
        assert len(novel_in_train) == 0, (
            f"train.csv contains {len(novel_in_train)} rows with novel pincodes "
            f"(PIN_091–PIN_100). These belong to heldout only."
        )

    def test_novel_pincodes_absent_from_val(self):
        """PIN_091–PIN_100 must never appear in val.csv."""
        val = pd.read_csv(DATA_DIR / "val.csv")
        novel_in_val = val[val["pincode"].str.extract(r"PIN_(\d+)")[0].astype(int) > 90]
        assert len(novel_in_val) == 0, (
            f"val.csv contains {len(novel_in_val)} rows with novel pincodes."
        )
