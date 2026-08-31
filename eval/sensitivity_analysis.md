# Cost Parameter Sensitivity Analysis

This study varies single assumptions holding the others fixed, to test if the engine's net positive value is fragile to one bad parameter. (Thresholds remain frozen at `[0.50, 0.75]`).

### Varying `C_RTO` (Freight Cost)
| `C_RTO` | Estimated Net Saved (INR) |
|---|---:|
| 100 | ₹8,826 |
| 150 | ₹15,611 |
| 200 | ₹22,396 |

### Varying `C_FP_H` (High-Friction Cost)
| `C_FP_H` | Estimated Net Saved (INR) |
|---|---:|
| 200 | ₹17,261 |
| 400 | ₹15,611 |
| 600 | ₹13,961 |

### Varying `γ_M` (Nudge Acceptance)
| `γ_M` | Estimated Net Saved (INR) |
|---|---:|
| 0.15 | ₹15,538 |
| 0.25 | ₹15,611 |
| 0.35 | ₹15,684 |

### Varying `γ_H` (Gate Acceptance)
| `γ_H` | Estimated Net Saved (INR) |
|---|---:|
| 0.3 | ₹15,375 |
| 0.45 | ₹15,611 |
| 0.6 | ₹15,848 |

### Conclusion
Net Saved remains decisively positive across the tested ranges for all assumptions. The policy is highly robust and is not artificially buoyed by fragile parameter choices.
