# Confusion Matrix & False Positive Rate

Using the frozen production thresholds `[0.50, 0.75]`, we collapse ALLOW_COD vs (NUDGE_PREPAY + SOFT_GATE_COD) to measure the overall friction rate.

## Binary Intervention Matrix
- **True Positives (TP)**: 148 (RTO correctly flagged)
- **False Positives (FP)**: 22 (Legitimate inconvenienced)
- **False Negatives (FN)**: 36 (RTO missed)
- **True Negatives (TN)**: 1044 (Legitimate untouched)

- **False Positive Rate (FPR)**: 2.1%
- **Specificity**: 97.9%

**Plain-language translation**: Exactly 2.1% of all legitimate (non-RTO) orders were subjected to friction (Nudge or Gate) by this policy.
