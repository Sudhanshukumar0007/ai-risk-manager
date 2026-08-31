# Baseline Comparison

| Policy | Estimated Net Saved | Observed Orders Inconvenienced (FPR) |
|---|---:|---:|
| **Baseline A (No Intervention)** | ₹0 | 0.0% |
| **Baseline B (Static Rule, RTO_Hist > 0.3)** | ₹-39,309 | 17.4% |
| **ML Policy (Frozen `[0.50, 0.75]`)** | **₹15,611** | **2.1%** |

The static rule uses the strongest single historical feature but causes more unnecessary friction or saves significantly less net value than the ML policy's multivariate approach.
