# Day 02 Audit — Synthetic Data Engine

Date/session: 2026-08-24
Auditor: Codex GPT-5
Scope: Day 02 implementation only, reviewed against `instructions .md`, `Implementation_plan.md`, `docs/worklogs/day-01.md`, `docs/worklogs/day-02.md`, and the feature-table passages in `docs/track02_spec_reference.md`.

## Audit Verdict

Day 02 is functionally acceptable for proceeding to Day 03, but it should not be treated as fully clean. The generated datasets pass the stated Day 02 acceptance test, train/val/heldout boundaries are isolated, and train-only historical rate computation matches the generated `config/historical_rates.json`.

The main risks are auditability and future evaluation validity:

- the generated report and generator still reference the removed `ideation/...pdf` source path;
- the Day 02 worklog does not follow the mandatory work-log template;
- validation has only 110 positive RTO rows, which makes the Day 5 bootstrap threshold-stability check mandatory;
- the train-only historical-rate test checks the function call path but does not prove that `val.csv` or `heldout.csv` cannot be read by future generator changes;
- generated CSVs and `data/generation_report.md` are tracked despite `.gitignore` declaring them generated artifacts.

## Governing Workflow Check

| Workflow Requirement | Status | Evidence |
|---|---|---|
| Read governing instructions | PASS | `instructions .md` read. |
| Read implementation plan | PASS | `Implementation_plan.md` read. |
| Read relevant work logs | PASS | `docs/worklogs/day-01.md`, `docs/worklogs/day-02.md` read. |
| Consult source feature table only when required | PASS | Day 2 plan explicitly references the feature table; reviewed `docs/track02_spec_reference.md` feature-table lines around delivery history, order anomaly, identity/velocity, address quality, payment context, and drift indicators. |
| Inspect repository state | PASS | Source, tests, generated artifacts, Git state inspected. |
| Validate current phase | PASS WITH WARNING | `python -m pytest tests/test_data_integrity.py -v -s` passed 23/23 with one pytest config warning and the expected low-positive-count warning. |

## Plan Alignment

| Day 02 Plan Step | Audit Status | Notes |
|---|---|---|
| Build `scripts/generate_data.py` with 15 features across required signal families | PASS WITH DOC ISSUE | Feature columns match the source feature names. The script comments describe "five signal families" but list six groups because Payment Context is separated from Drift Indicators. |
| Generate `train.csv` 5,000 seed=101, `val.csv` 750 seed=202, `heldout.csv` 1,250 seed=303 | PASS | Row counts verified by tests and independent audit. |
| Inject held-out covariate shift on 10% heldout only | PASS | 125 heldout rows have both drift flags; train/val have zero drift flags. |
| Log positive-class counts per split to `data/generation_report.md` | PASS | Counts are present; val has 110 RTO positives. |
| Compute pincode/category historical RTO rates strictly from train | PASS WITH TEST GAP | Independent recomputation from `train.csv` COD rows exactly matched `config/historical_rates.json`. Existing unit test does not fully enforce future file-read isolation. |
| Verify composition: approx 62% COD, approx 24% RTO within COD | PASS | train 61.6% COD / 24.0% RTO-in-COD; val 61.5% / 23.9%; heldout 61.4% / 24.0%. |
| Acceptance test `pytest tests/test_data_integrity.py` | PASS | 23/23 passed locally on Windows Python 3.14.2. |

## Validation Evidence

Command run:

```text
python -m pytest tests/test_data_integrity.py -v -s
```

Result:

```text
23 passed, 1 warning in 8.77s
```

Warning:

```text
PytestConfigWarning: Unknown config option: asyncio_mode
```

The warning is not Day 02-specific, but it indicates the local pytest environment does not have the async plugin/config support expected by `pytest.ini`.

Independent artifact checks:

```text
train_sha256=ad901b61c7e32b9a1556ceb2545ba33bfb86b31c466fb32610e1ec5e7c57ade2
val_sha256=ddfc7f31d6b9c03266bd7fdcadb43a1872d956e14af3dcb503e88225f2d50f11
heldout_sha256=a150979d9a755342f659147842a5f82ba3f46058291882d35cdffdf0ae0196a3
rates_sha256=04a540110c8daa1dc325fc8048d9795865b4d652c7f0ea59c50737c89041b452
```

Split counts:

```text
rows: train=5000, val=750, heldout=1250
COD counts: train=3081, val=461, heldout=767
RTO counts: train=739, val=110, heldout=184
non-COD RTO counts: train=0, val=0, heldout=0
```

Historical-rate verification:

```text
pincode rate mismatches versus train COD aggregation: 0
category rate mismatches versus train COD aggregation: 0
global COD RTO rate: 0.23985718922427784
```

Covariate-shift verification:

```text
train/val max standard pincode: PIN_090
heldout novel pincodes: PIN_091 through PIN_100
heldout novel rows: 125
```

## Findings

### A-D2-001 — Stale Source Authority Path

Severity: Medium

Evidence:

- `scripts/generate_data.py:7` references `ideation/Ten Day Implementation Plan Roadmap.pdf`.
- `scripts/generate_data.py:425` emits that stale path into `data/generation_report.md`.
- `data/generation_report.md:3` contains `_Source authority: ideation/Ten Day Implementation Plan Roadmap.pdf_`.
- `instructions .md` now says the original PDF and `ideation/` folder no longer exist and `docs/track02_spec_reference.md` is the sole raw-spec reference.

Risk:

This weakens auditability. A later agent may look for a non-existent source path or treat the wrong source as authoritative.

Recommendation:

Update the generator docstring and report template to cite `docs/track02_spec_reference.md` for feature-table verification, while preserving `Implementation_plan.md` as the day-to-day source of truth.

### A-D2-002 — Day 02 Worklog Does Not Use Mandatory Template

Severity: Medium

Evidence:

- `docs/worklogs/day-02.md` uses custom sections such as "Objectives", "Implementation Steps Executed", and "Issues / Decisions".
- The required template in `instructions .md` requires sections like "Repository State Before Work", "Pre-Implementation Assessment", "Plan Compliance Review", "Problems Encountered", "Decisions", "Next Required Action", "Blocking Issues", and "Do Not Repeat".

Risk:

The log is useful but not compliant with the handoff protocol. A later agent or final audit may need consistent logs to prove phase-by-phase discipline.

Recommendation:

Normalize `docs/worklogs/day-02.md` to the required template without changing the factual content.

### A-D2-003 — Validation Positive Class Is Low For Day 5 Threshold Search

Severity: High downstream risk, non-blocking for Day 02

Evidence:

- `data/generation_report.md:49` logs `val.csv RTO=1 count: 110`.
- The Day 2 log and tests also print this warning.
- The corrected plan explicitly says the small validation positive class makes Day 5 bootstrap stability mandatory.

Risk:

Day 5's 2D threshold search can overfit a 750-row validation split with only 110 positives. This can make `config/thresholds.json` unstable even if all Day 5 tests pass superficially.

Recommendation:

Make `eval/threshold_stability.md` and bootstrap variance reporting a Day 5 hard gate. Do not freeze production thresholds until the selected `(t_low, t_high)` pair is shown to be stable enough or the instability is explicitly documented.

### A-D2-004 — Train-Only Historical-Rate Test Is Weaker Than It Claims

Severity: Medium

Evidence:

- `tests/test_data_integrity.py:206` tests that `compute_historical_rates()` is called once with a 5,000-row DataFrame during `gd.main()`.
- The test does not patch or forbid reads of `data/val.csv` or `data/heldout.csv`.
- It would not catch a future change where `compute_historical_rates(train_df)` is still called correctly but another leakage-prone aggregation also reads validation or heldout data.

Risk:

This could miss a future regression that uses validation or heldout data for derived lookup values while preserving the current call-count behavior.

Recommendation:

Add a stronger leakage regression test that runs generation in a temp workspace with poisoned `val.csv` and `heldout.csv`, or patches `pandas.read_csv`/file open paths to fail if validation or heldout are accessed during historical-rate construction.

### A-D2-005 — Tracked Generated Artifacts Conflict With `.gitignore`

Severity: Low to Medium

Evidence:

- `.gitignore` ignores `data/*.csv` and `data/generation_report.md`.
- `git ls-files` shows `data/train.csv`, `data/val.csv`, `data/heldout.csv`, and `data/generation_report.md` are tracked.

Risk:

This is not a correctness bug, but it creates confusing change-management semantics. Future regenerations may appear as tracked diffs even though the ignore file says they should be local/generated.

Recommendation:

Decide explicitly whether these Day 2 deliverables are submission artifacts to track. If yes, adjust `.gitignore` to stop claiming they are ignored. If no, remove them from the index with `git rm --cached` and ensure regeneration is deterministic from `scripts/generate_data.py`.

### A-D2-006 — Acceptance Test Does Not Enforce Exact Reproducibility

Severity: Medium

Evidence:

- The test suite verifies current generated files and reruns `gd.main()` in a temp directory, but it does not compare regenerated file hashes or DataFrame equality against committed/generated artifacts.
- Independent audit hashes are listed above, but they are not part of an automated regression test.

Risk:

A generator change could preserve broad distributions while changing examples, labels, or lookup rates. That may invalidate downstream model metrics without an obvious Day 2 test failure.

Recommendation:

Add deterministic snapshot checks for row counts, schema, split hashes, and `config/historical_rates.json` hash, or explicitly document that regenerated data is allowed to change only before Day 4 training begins.

## Non-Issues Confirmed

- No order ID overlap across train, validation, and heldout.
- `heldout.csv` shift is isolated to heldout and uses `PIN_091` through `PIN_100`.
- `train.csv` and `val.csv` contain only standard pincodes through `PIN_090`.
- All `is_rto=1` rows are COD rows; non-COD RTO count is zero in all splits.
- Historical pincode/category rates in `config/historical_rates.json` exactly match train COD aggregations.
- The generated schema includes the 15 planned feature columns plus identifiers and target.

## Proceed / Stop Decision

Proceed to Day 03 is acceptable.

Conditions attached:

1. Carry A-D2-003 into Day 5 as a hard stability gate.
2. Fix A-D2-001 before final submission documentation.
3. Normalize Day 02 worklog formatting before Day 5 checkpoint review.
4. Strengthen leakage and reproducibility tests before relying on Day 2 artifacts for Day 4/Day 5 claims.

## Remediation Status

**Status: CLOSED (All conditions met)**

1. **A-D2-003**: Carried to Day 5 as a hard stability gate (logged).
2. **A-D2-001**: Fixed docstring in `scripts/generate_data.py` to point to `docs/track02_spec_reference.md`.
3. **A-D2-002**: Normalized `docs/worklogs/day-02.md` to the mandatory template format.
4. **A-D2-004 & A-D2-006**: Added `tests/test_data_reproducibility.py` which guards against val/heldout leakage during generation and verifies deterministic SHA-256 hashes against authoritative container output.
5. **A-D2-005**: Fixed `.gitignore` to explicitly track data artifacts and audit reports.

All Day 02 audit conditions have been remediated. Proceeding to Day 03 is fully cleared.
