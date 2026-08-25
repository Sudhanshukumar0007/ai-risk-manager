# Day 02 Suggestions

## Priority Fixes

1. Replace stale `ideation/Ten Day Implementation Plan Roadmap.pdf` references in `scripts/generate_data.py` and generated `data/generation_report.md` with `docs/track02_spec_reference.md`.

2. Rewrite `docs/worklogs/day-02.md` into the mandatory template from `instructions .md`. Keep the existing facts, but add the missing sections: repository state before work, pre-implementation assessment, plan compliance review, problems encountered, decisions, next required action, blocking issues, and do-not-repeat.

3. Add a stronger no-leakage test for historical lookups. The current test only proves `compute_historical_rates()` receives a 5,000-row DataFrame once. It should also fail if validation or heldout data is read during rate construction.

4. Add deterministic regeneration checks. At minimum, compare regenerated split hashes or exact DataFrame equality for `train.csv`, `val.csv`, `heldout.csv`, and `config/historical_rates.json`.

5. Treat the Day 5 bootstrap threshold-stability report as mandatory. `val.csv` has only 110 positive RTO rows, so a single validation-grid optimum is not enough evidence for freezing thresholds.

## Suggested Test Additions

```text
pytest tests/test_data_reproducibility.py -v
```

Suggested assertions:

- rerunning `scripts/generate_data.py` with seeds 101/202/303 produces byte-identical CSVs or exactly identical DataFrames;
- `config/historical_rates.json` is identical across reruns;
- `PIN_091` through `PIN_100` never appear in train or validation;
- historical-rate construction cannot read validation or heldout files.

## Suggested Change-Management Decision

Resolve the generated-artifact policy:

- Option A: Track Day 2 CSVs and reports as reproducible deliverables, then remove the conflicting ignore rules for `data/*.csv` and `data/generation_report.md`.
- Option B: Keep generated artifacts ignored, remove currently tracked generated data from the Git index, and require regeneration during setup and evaluation.

For this project, Option A is more convenient for judge reproducibility if file sizes remain small.

