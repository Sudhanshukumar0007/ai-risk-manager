# Breakeven Ratios & Empirical Validation

## Closed-Form Breakeven Ratios
Calculated by setting incremental gain of TP equal to incremental penalty of FP.
- **Medium Tier Breakeven TP:FP Ratio:** 1.700
- **High Tier Breakeven TP:FP Ratio:** 1.661

## Empirical Ratios at Optimal Thresholds
At `t_low = 0.500` and `t_high = 0.750`:
- **Medium Tier Empirical TP:FP Ratio:** 2.000
- **High Tier Empirical TP:FP Ratio:** 13.000

## Cross-Check
To ensure mathematical consistency, the empirical TP:FP ratio should exceed the breakeven ratio for both tiers.
- **Medium Tier Check:** PASS
- **High Tier Check:** PASS
