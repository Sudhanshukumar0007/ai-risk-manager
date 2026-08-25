# Issue #8 Resolution: Missing Threshold Values & Fallback Gates

## Context
During the Day 1 review of the extracted project specifications (`docs/track02_spec_reference.md`), it was noted that the exact KS-test target score and the precise Brier score threshold were inexplicably missing from the document, likely lost during the PDF-to-text extraction process. This was formally logged as **Issue #8**.

## Risk Assessment
Blindly inventing statistical thresholds in a risk-engine context is dangerous. An arbitrarily selected Brier score target might be mathematically impossible given the base rate, or a random KS-test threshold might enforce false confidence.

## Issue Context

The original architecture plan required exact numeric thresholds for the Kolmogrov-Smirnov (KS) statistic, the Brier score, and the Expected Calibration Error (ECE). However, upon checking the `docs/track02_spec_reference.md` (which contains the parsed contents of the authoritative `ideation/Ten Day Implementation Plan Roadmap.pdf`), the scalar values for the KS statistic and Brier score were found to be completely blank/missing. As we are strictly prohibited from inventing arbitrary thresholds, we have abandoned the missing KS/Brier scalars.

**Note:** The threshold for ECE was clearly extracted as `< 0.08`. This is NOT missing and will be strictly enforced.

## Resolution: Systemic Fallback Gates

In accordance with the governing instructions ("Statistical honesty: Do not invent missing thresholds... use the explicit fallback process described by the plan"), we are officially abandoning the missing KS and Brier scalar thresholds.

Instead, we will rely exclusively on the **Fallback Gate List** defined in the master plan for the Day 4 acceptance test, combined with the one valid statistical threshold (ECE < 0.08):

1. **ECE < 0.08:** The Expected Calibration Error on `val.csv` must strictly be less than 0.08.
2. **Base-Rate Stability:** The base-rate of RTO within COD in each split (train/fit, calibration, val) must fall within ±3 percentage points of the global design target (24%).
3. **Absolute Data Isolation:** Zero row-ID or feature hash overlap across splits.
3. **Domain Integrity:** All 15 generated features must fall strictly within their documented valid ranges and domains.
4. **Controlled Covariate Shift:** The injected 10% covariate shift must be explicitly detectable in `heldout.csv` while being completely absent from `train.csv` and `val.csv`.
5. **Deterministic Training:** Model training must be absolutely reproducible (same seed → same weights, verified by hash checks).

By enforcing these rigorous systemic checks, we guarantee the structural validity and predictive integrity of the model without relying on invented scalar metrics. ECE (Expected Calibration Error) and Brier Score will still be *calculated* and reported in `eval/calibration_report.md` for diagnostic visibility, but they are no longer treated as hard pass/fail gates.
