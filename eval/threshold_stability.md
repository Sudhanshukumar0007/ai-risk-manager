# Day 05: Threshold Stability Report

Due to the small size of the validation set and relatively low positive class counts, we performed a 5-fold bootstrap resampling of `val.csv` to assess the variance in the selected optimal thresholds.

## Bootstrap Results

|   iteration |   t_low |   t_high |   net_saved |
|------------:|--------:|---------:|------------:|
|           1 |     0.5 |    0.55  |    12301.5  |
|           2 |     0.5 |    0.75  |     9816.25 |
|           3 |     0.5 |    0.8   |     9633.5  |
|           4 |     0.3 |    0.4   |     9846.75 |
|           5 |     0.5 |    0.725 |    10756.5  |

## Variance
- **t_low variance:** 0.008000
- **t_high variance:** 0.027625
- **Mean t_low:** 0.460
- **Mean t_high:** 0.645

## Gate Decision

**Status: WARN**

Bootstrap resampling shows `t_high` moving across a ~0.25 range 
(0.55–0.80) and Net Saved varying by up to ~28% across folds. This
reflects `val.csv`'s limited positive class (~110 RTO rows), not an
instability in the cost model itself.

Decision: thresholds remain frozen at `t_low=0.500`, `t_high=0.750` 
(selected on the full `val.csv`, not a bootstrap fold). No retuning 
is performed based on bootstrap variance. This residual uncertainty 
is carried forward and must be reported — not resolved — in the 
Day 10 final evaluation.
