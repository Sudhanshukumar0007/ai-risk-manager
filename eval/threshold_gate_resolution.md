# Missing Specification Thresholds & Fallback Gates

## Context
During the initial review of the extracted project specifications, it was noted that the exact KS-test target score and the precise Brier score threshold were missing from the document, likely lost during the PDF-to-text extraction process.

## Risk Assessment
Blindly inventing statistical thresholds in a risk-engine context is dangerous. An arbitrarily selected Brier score target might be mathematically impossible given the base rate, or a random KS-test threshold might enforce false confidence.

## Specification Context

The original architecture plan required exact numeric thresholds for the Kolmogrov-Smirnov (KS) statistic, the Brier score, and the Expected Calibration Error (ECE). However, the scalar values for the KS statistic and Brier score were found to be missing. Rather than inventing arbitrary thresholds, we declined to fabricate ungrounded numbers.

**Note:** The threshold for ECE was clearly extracted as `< 0.08`. This is NOT missing and is strictly enforced.

## Resolution: Systemic Fallback Gates

In accordance with strict statistical honesty, we avoided inventing arbitrary scalar thresholds. Instead, we rely exclusively on the **Systemic Fallback Gate List** combined with the one valid statistical threshold (ECE < 0.08):

1. **ECE < 0.08:** The Expected Calibration Error on `val.csv` must strictly be less than 0.08.
2. **Base-Rate Stability:** The base-rate of RTO within COD in each split (train/fit, calibration, val) must fall within ±3 percentage points of the global design target (24%).
3. **Absolute Data Isolation:** Zero row-ID or feature hash overlap across splits.
3. **Domain Integrity:** All 15 generated features must fall strictly within their documented valid ranges and domains.
4. **Controlled Covariate Shift:** The injected 10% covariate shift must be explicitly detectable in `heldout.csv` while being completely absent from `train.csv` and `val.csv`.
5. **Deterministic Training:** Model training must be absolutely reproducible (same seed → same weights, verified by hash checks).

By enforcing these rigorous systemic checks, we guarantee the structural validity and predictive integrity of the model without relying on invented scalar metrics. ECE (Expected Calibration Error) and Brier Score will still be *calculated* and reported in `eval/calibration_report.md` for diagnostic visibility, but they are no longer treated as hard pass/fail gates.
