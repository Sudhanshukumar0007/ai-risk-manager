# Day 05 Audit - Checkpoint 1

Date/session: 2026-08-25
Auditor: Codex GPT-5
Scope: Day 05 implementation and cumulative Checkpoint 1 gates, reviewed against `instructions .md`, `Implementation_plan.md`, `docs/worklogs/day-05.md`, `app/ml/costs.py`, `scripts/optimize_thresholds.py`, `tests/test_threshold_optimizer.py`, generated threshold artifacts, Docker service state, and earlier audit status through Day 04.

## Audit Verdict

Checkpoint 1 is not cleanly cleared.

The Day 05 cost engine and threshold-search artifacts exist, and the Docker pytest checkpoint suite passed 30/30. However, two checkpoint gates are currently failing outside that green test result:

1. The five-service Docker topology is not clean because `celery_worker` is restarting on `ModuleNotFoundError: No module named 'app.services.llm_explain'`.
2. The Day 05 breakeven report explicitly records `Medium Tier Check: FAIL`, while the worklog still marks `Blocking issues: NONE` and tells the next agent to proceed to Day 06.

The optimizer output also shows unstable bootstrap thresholds and unresolved formula disagreement between the corrected plan's approximate breakeven ratios and the implemented ratios. Those are not necessarily impossible to resolve, but they are not documented as a safe checkpoint decision today.

## Governing Workflow Check

| Workflow Requirement | Status | Evidence |
|---|---|---|
| Read governing instructions | PASS | `instructions .md` reviewed. |
| Read implementation plan | PASS | Day 05 and Checkpoint 1 gates reviewed. |
| Read latest relevant worklog | PASS | `docs/worklogs/day-05.md` reviewed. |
| Inspect actual repository | PASS | Day 05 source, tests, config, eval artifacts, Docker status, and Git status inspected. |
| Validate via Docker | PASS WITH CHECKPOINT FAILURE | `docker compose exec api pytest ...` passed 30/30, but `docker compose ps` shows `risk_celery` restarting. |
| Preserve evaluation boundaries | PASS FOR DAY 05 | Threshold optimizer reads `val.csv`; no Day 05 `heldout.csv` access found. |

## Checkpoint 1 Gate Review

| Gate | Status | Evidence |
|---|---|---|
| M01 Infra | FAIL | `risk_celery` is restarting; logs show missing `app.services.llm_explain`. |
| M02 Data Engine | PASS | Reproducibility and no-leakage data tests passed in Docker. |
| M03 No-Leakage Model | PASS CURRENTLY | Current `scripts/train_model.py` has no `heldout.csv` reference and model tests passed. Earlier Day 04 audit issue appears remediated in current code/worklog. |
| M04 Feature Latency | PASS | Docker test passed; tracked report shows p99 under 10 ms. |
| M05 Calibration | PASS | Model tests passed; calibration report shows Brier 0.0216 and ECE 0.0145. |
| M06 Cost Engine | PASS | `Cost(TP_H)` zero freight-loss branch test passed. |
| M07 Threshold Search | PARTIAL | 2D search and bootstrap report exist, but instability is not interpreted or gated. |
| M08 Breakeven Ratios | FAIL | `eval/breakeven_ratios.md` records Medium Tier Check as FAIL. |

## Validation Evidence

Commands run:

```text
docker compose ps
docker compose logs --tail=80 celery_worker
docker compose exec api pytest tests/test_health.py tests/test_data_reproducibility.py tests/test_feature_pipeline.py tests/test_feature_latency.py tests/test_model_performance.py tests/test_threshold_optimizer.py -v
```

Results:

```text
30 passed, 3 warnings in 23.57s
```

Important service evidence:

```text
risk_api        Up (healthy)
risk_postgres   Up (healthy)
risk_redis      Up (healthy)
risk_rabbitmq   Up (healthy)
risk_celery     Restarting (1)
```

Celery log evidence:

```text
ModuleNotFoundError: No module named 'app.services.llm_explain'
```

Generated Day 05 artifact evidence:

```text
config/thresholds.json: t_low=0.500, t_high=0.675
eval/breakeven_ratios.md: Medium Tier Check: FAIL; High Tier Check: PASS
eval/threshold_stability.md: t_low variance=0.008000; t_high variance=0.008625
eval/threshold_heatmap.png exists locally but is ignored by .gitignore
```

## Findings

### A-CP1-001 - Celery Worker Crashes Because It Imports A Day 8 Module

Severity: Blocking

Evidence:

- `app/core/celery_app.py:17` configures explicit Celery imports.
- `app/core/celery_app.py:18` includes `app.services.llm_explain`.
- No `app/services/llm_explain.py` exists in the repository.
- `docker compose ps` shows `risk_celery` restarting.
- `docker compose logs --tail=80 celery_worker` shows `ModuleNotFoundError: No module named 'app.services.llm_explain'`.

Risk:

Checkpoint 1 requires the five-service infrastructure topology to come up cleanly before Day 06. The API health test still passes because `/health` checks Postgres, Redis, and RabbitMQ, but it does not verify the Celery worker process. Proceeding to Day 06 with a crashing worker hides an infrastructure failure that later Day 8 async explanation work depends on.

Recommendation:

Do one of the following before Day 06:

1. Remove the explicit `include=["app.services.llm_explain"]` until the Day 8 task module is created, relying on later Day 8 code to add it.
2. Add a minimal `app/services/llm_explain.py` module with a valid Celery task stub that does not call the LLM or affect the monetary path.

Then rerun `docker compose up`/`docker compose ps` and add a test or smoke check that fails when `celery_worker` is unhealthy.

### A-D5-001 - Do Not Mark Checkpoint 1 Complete While The Medium-Tier Breakeven Cross-Check Fails

Severity: Blocking

Evidence:

- `eval/breakeven_ratios.md:10` records Medium Tier empirical TP:FP ratio as `1.000`.
- `eval/breakeven_ratios.md:15` records `Medium Tier Check: FAIL`.
- `docs/worklogs/day-05.md:117` through `docs/worklogs/day-05.md:121` acknowledge the M-tier cross-check failure.
- `docs/worklogs/day-05.md:127` says "Checkpoint 1 is reached."
- `docs/worklogs/day-05.md:138` through `docs/worklogs/day-05.md:141` mark the completion gate as passing with no blocking issues.
- `Implementation_plan.md:137` requires the model's TP:FP ratio at the selected threshold to exceed breakeven, otherwise the threshold choice contradicts the cost model.
- `Implementation_plan.md:154` marks M08 Breakeven Ratios as `Must pass`.

Risk:

The frozen Day 05 thresholds route a medium-risk band whose observed validation economics fail the project's own breakeven rule. Day 06 would wire these thresholds into deterministic API routing, converting a documented validation failure into product behavior.

Recommendation:

Treat M08 as failed until the medium-tier economics are resolved. Either adjust the cost model/threshold constraints with documented plan approval, choose thresholds that do not create a loss-making medium tier, or formally document that `NUDGE_PREPAY` is disabled/deferred. Do not proceed to Razorpay/payment integration with the current checkpoint verdict.

### A-D5-002 - Breakeven Ratio Implementation Conflicts With The Corrected Plan And Is Not Resolved

Severity: High

Evidence:

- `Implementation_plan.md:137` expects closed-form breakeven ratios of approximately M-tier `1.70` and H-tier `1.66`.
- `app/ml/costs.py:61` through `app/ml/costs.py:81` compute M-tier `1.600` and H-tier `2.930`.
- `eval/breakeven_ratios.md:5` through `eval/breakeven_ratios.md:6` report `1.600` and `2.930`.
- `tests/test_threshold_optimizer.py:21` through `tests/test_threshold_optimizer.py:25` comments on the H-tier mismatch but then executes `pass`.
- `tests/test_threshold_optimizer.py:40` through `tests/test_threshold_optimizer.py:46` again notes the mismatch and avoids asserting it.

Risk:

Checkpoint 1 freezes thresholds derived from ratios that do not match the authoritative corrected plan. If the plan ratios are correct, the cost implementation is wrong. If the implementation is correct and the plan is wrong, the deviation still needs an explicit resolution note because downstream Day 10 reporting will compare against the plan.

Recommendation:

Reconcile the formulas before freezing thresholds. Record the source of truth in a short decision note, update `eval/breakeven_ratios.md`, and make `tests/test_threshold_optimizer.py` assert the resolved closed-form values instead of carrying non-asserting comments.

### A-D5-003 - Threshold Optimizer Tests Do Not Assert The Actual Day 05 Acceptance Criteria

Severity: Medium

Evidence:

- `tests/test_threshold_optimizer.py:17` through `tests/test_threshold_optimizer.py:25` names a breakeven test but does not assert the H-tier value.
- `tests/test_threshold_optimizer.py:27` through `tests/test_threshold_optimizer.py:46` computes H-tier gain but never asserts `h_ratio`.
- `tests/test_threshold_optimizer.py:48` through `tests/test_threshold_optimizer.py:65` proves a synthetic perfect router outperforms baseline, but does not run the actual `val.csv` grid search or check `config/thresholds.json`.
- `scripts/optimize_thresholds.py:170` through `scripts/optimize_thresholds.py:174` writes PASS/FAIL strings but never exits nonzero when a cross-check fails.

Risk:

The command `pytest tests/test_threshold_optimizer.py -v` can pass even when the generated breakeven report fails M08. That is exactly the current state. The acceptance test is therefore green while the checkpoint gate is red.

Recommendation:

Add a test that runs the optimizer against a temporary output directory, asserts non-negative Net Saved on the actual validation probabilities, asserts both empirical TP:FP ratios meet the resolved breakeven ratios, and fails if any generated cross-check is `FAIL`.

### A-D5-004 - Threshold Stability Is Reported But Not Interpreted As A Gate

Severity: Medium

Evidence:

- `eval/threshold_stability.md:9` through `eval/threshold_stability.md:13` shows bootstrap-selected cutoffs moving from `(0.500, 0.850)` to `(0.300, 0.625)`.
- `eval/threshold_stability.md:16` through `eval/threshold_stability.md:17` reports `t_low variance: 0.008000` and `t_high variance: 0.008625`.
- `docs/worklogs/day-05.md:117` through `docs/worklogs/day-05.md:121` mentions the breakeven issue, but not whether the bootstrap movement is acceptable.
- `Implementation_plan.md:154` says threshold stability must pass and high variance must be flagged.

Risk:

The validation split has only about 110 positive RTO rows. A 2D threshold search over this small set can overfit. The current report gives raw variance but no pass/fail threshold, no interpretation, and no decision about whether the observed swing is acceptable for frozen production thresholds.

Recommendation:

Define an explicit stability tolerance for this project, add it to `eval/threshold_stability.md`, and mark the gate PASS/WARN/FAIL. If the current movement is accepted for the hackathon, document the residual risk and require Day 10 to report threshold sensitivity without retuning on heldout.

### A-D5-005 - Day 05 Deliverables Are Not In A Recoverable Git State

Severity: Medium

Evidence:

- `git status --short --untracked-files=all` shows these Day 05 deliverables as untracked: `app/ml/costs.py`, `config/thresholds.json`, `docs/worklogs/day-05.md`, `eval/breakeven_ratios.md`, `eval/threshold_stability.md`, `scripts/optimize_thresholds.py`, and `tests/test_threshold_optimizer.py`.
- `.gitignore:25` ignores `eval/*.png`, so `eval/threshold_heatmap.png` is not tracked by default.
- `git ls-files` does not include the Day 05 deliverables above.

Risk:

Checkpoint 1 artifacts are local workspace state rather than recoverable repository state. A later agent, CI job, or judge consuming the repo from Git would miss the threshold optimizer, frozen threshold config, reports, and tests.

Recommendation:

After fixing the blocking gates, intentionally add the Day 05 source/config/report/test files to version control. For the heatmap, either stop ignoring this required deliverable or document/regenerate it deterministically from `scripts/optimize_thresholds.py`.

## Non-Issues Confirmed

- `scripts/optimize_thresholds.py` uses `val.csv` for threshold search and does not read `heldout.csv`.
- `config/thresholds.json` contains a two-cutoff router, not a scalar threshold.
- `app/ml/costs.py` includes a zero-cost abandoned high-risk branch.
- `tests/test_threshold_optimizer.py` verifies the abandoned high-risk branch does not scale with `C_RTO`.
- Docker pytest passed for health, data reproducibility, feature pipeline, feature latency, model performance, and threshold optimizer tests.
- Day 04 heldout contamination appears remediated in current code, despite the older Day 04 audit file still showing the issue as open.

## Proceed / Stop Decision

Stop before Day 06 implementation.

Checkpoint 1 should remain open until:

1. `celery_worker` is healthy in Docker.
2. M08 breakeven cross-check is resolved or the routing economics are changed with explicit documentation.
3. The breakeven-ratio formula mismatch is reconciled.
4. The threshold stability report has an explicit gate decision.
5. Day 05 deliverables are made recoverable in Git or documented as generated artifacts.

## Remediation Status

Status: OPEN / BLOCKING

Blocking items:

1. Fix the Celery worker import crash.
2. Resolve the medium-tier breakeven cross-check failure before freezing the checkpoint.

Required follow-ups:

1. Strengthen `tests/test_threshold_optimizer.py` so it fails on generated report cross-check failures.
2. Reconcile the plan/code breakeven ratio mismatch.
3. Add an explicit stability pass/warn/fail decision to `eval/threshold_stability.md`.
4. Track or reproducibly regenerate all Day 05 deliverables.
