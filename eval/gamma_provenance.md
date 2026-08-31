# Gamma Assumptions Provenance

## Overview
In the Day 5 `CostEngine`, we model the likelihood of a customer successfully completing a prepaid checkout after being inconvenienced. This relies on two parameters:
- `gamma_M`: The conversion rate when subjected to a soft nudge (default: 0.25).
- `gamma_H`: The conversion rate when subjected to a hard gate (default: 0.45).

## Data Provenance
Currently, these parameters are **synthetic assumptions**. The dataset (`train.csv`, `val.csv`, `heldout.csv`) does not contain historical logs of nudge or gate interventions. 

### Why this matters
Because these parameters were not empirically derived from past A/B tests on this specific traffic, the actual "Net Saved" in production may vary if the real-world friction acceptance is significantly different.

## Mitigation
- We performed a **Sensitivity Analysis** (see `sensitivity_analysis.md`) which varied `gamma_M` between `0.15` and `0.35`, and `gamma_H` between `0.30` and `0.60`.
- Under all tested variations, the model policy remains strictly net-positive and outperforms the baselines.
- **Future Action**: Once the engine goes live in a shadow or limited A/B release, we must immediately measure the empirical `gamma_M` and `gamma_H` to calibrate the Cost Engine.

