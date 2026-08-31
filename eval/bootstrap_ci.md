---
seed: 42
---
# Bootstrap Confidence Interval on Net Saved

To quantify economic uncertainty, we bootstrap-resampled `heldout.csv` 1,000 times (with replacement) holding thresholds frozen at `[0.50, 0.75]`.

| Metric | Mean | 95% CI Lower | 95% CI Upper |
|---|---:|---:|---:|
| **Estimated Net Saved (INR)** | ₹15,630 | ₹12,116 | ₹19,175 |

**Interpretation**: Estimated Net Saved: ₹15,630, 95% CI [₹12,116, ₹19,175] — the policy's economic advantage stays positive across resamples even though the optimal threshold itself is uncertain (per the Day 5 WARN).

> [!WARNING]
> This Confidence Interval is structurally optimistic: it captures variance in the test set evaluation but assumes the `[0.50, 0.75]` thresholds themselves are perfectly known. True system-level uncertainty is wider because it must also include the threshold selection variance (which Day 5 showed was high).
