# AI Risk Manager — Agent Instructions

## 1. Purpose

This repository must be implemented according to the **10-Day AI Risk Manager implementation plan** in `implementation_plan.md`.

This file is the **operational contract for every coding/research agent** working on the project.

The agent must not treat the plan as a loose checklist. It must execute the plan phase-by-phase, preserve its evaluation boundaries, document every meaningful change, and stop at blocking gates when required.

The core implementation sequence is:

**Plan → Read recent phase log → Inspect current repository → Assess/give implementation suggestions → Implement → Validate → Review against plan → Write/update phase log → Proceed only when the phase gate permits it.**

The plan explicitly establishes two major checkpoints:
- **Checkpoint 1: End of Day 5**
- **Checkpoint 2: End of Day 10**

The plan also defines Days 1–7 as the must-ship core, Day 8 as should-ship, Day 9 as nice-to-have, and Day 10 as non-negotiable final evaluation/submission work.

Source: `implementation_plan.md`.

---

## 1a. Source Document Reference Rule

The original source document for this project has been pre-extracted to:

```
docs/pdf_extract.txt
```

The `ideation/` folder and the original PDF no longer exist in the repo.
`docs/pdf_extract.txt` is the **sole authoritative reference** for raw specification content (feature names, financial parameters, statistical thresholds).

**When to consult `docs/pdf_extract.txt`:**
The agent MUST read this file **only when `implementation_plan.md` explicitly instructs it to do so** — for example, a phrase like *"as specified in the feature table"* or *"confirm the threshold from the source document"* is a trigger.

**When NOT to consult it:**
Do not read it for general context or curiosity. Use `implementation_plan.md` as the sole day-to-day guide. The corrected plan already incorporates the verified content.

**If a value is genuinely absent:**
Use the fallback gate list defined in `implementation_plan.md` — do not invent a value.

**If `docs/pdf_extract.txt` conflicts with `implementation_plan.md`:**
`implementation_plan.md` takes precedence — it is the audited, corrected version.

---

# 2. Mandatory Agent Startup Procedure

Every agent session MUST begin by following this exact order.

## Step 1 — Read the governing documents

Read:

1. `INSTRUCTIONS.md` — this file.
2. `implementation_plan.md` — the authoritative implementation plan.
3. The latest relevant phase work log under `docs/worklogs/`.
4. Any architecture decision, threshold, evaluation, or design document referenced by the current phase.

Do not start coding before this review.

## Step 2 — Determine the current phase

Identify:

- Current implementation day/phase.
- Current checkpoint status.
- Completed tasks.
- Partially completed tasks.
- Failed acceptance tests.
- Known deviations from `implementation_plan.md`.
- Open technical risks.
- Files changed recently.
- Decisions already made by previous agents.

Never assume that the repository state corresponds to the last completed day.

Verify it from the logs and repository.

## Step 3 — Inspect the actual repository

Before implementing anything:

- Inspect the existing file structure.
- Inspect relevant source files.
- Inspect tests.
- Inspect configuration.
- Inspect Docker/service state when relevant.
- Inspect Git status and recent commits when useful.
- Run targeted tests or validation commands relevant to the current phase.

Do not recreate files or components that already exist without checking them first.

## Step 4 — Produce a short implementation assessment

Before changing code, write a concise internal/current-session assessment covering:

### Current state
What is already implemented?

### Plan alignment
Which exact plan steps are satisfied?

### Missing work
Which plan steps remain?

### Risks
What could break correctness, evaluation validity, security, or later phases?

### Recommended implementation order
What should be implemented first and why?

The agent should make useful engineering suggestions here, but **must not silently rewrite the implementation plan**.

## Step 5 — Implement only after the assessment

Implement the current phase in the smallest coherent increments.

After each meaningful increment:

- run the relevant test;
- inspect the result;
- fix failures before stacking unrelated changes.

## Step 6 — Validate against the plan

At the end of the session, explicitly verify:

- Every completed task from the current phase.
- Every required acceptance test.
- Every relevant phase gate.
- Every newly created artifact.
- Any deviations from the plan.
- Any assumptions introduced.

## Step 7 — Write the work log

The agent MUST create or update the work log for the phase before ending the session.

The log must record what actually happened, not what was intended.

---

# 3. Governing Principle: `implementation_plan.md` Is the Source of Truth

The implementation plan is authoritative unless the project owner explicitly changes it.

An agent must NOT:

- silently change thresholds;
- silently change dataset sizes;
- silently change train/validation/held-out boundaries;
- reuse `heldout.csv` for tuning;
- introduce validation leakage;
- remove required security controls;
- replace DB-enforced idempotency with application-only logic;
- put the LLM back onto the synchronous monetary request path;
- replace the two-cutoff router with a scalar threshold;
- remove required acceptance tests;
- mark a phase complete when its gate has not passed.

If a deviation is technically necessary, record it explicitly in the work log under **Deviation / Decision** and explain:

1. Why the deviation was necessary.
2. What the original plan required.
3. What changed.
4. Whether later phases are affected.
5. Whether the project owner needs to approve it.

Never hide deviations.

---

# 4. Phase Execution Rules

Each implementation phase must follow:

**Understand → Inspect → Suggest → Implement → Test → Review → Log.**

A phase is considered complete only when:

1. Its implementation tasks are done.
2. Its acceptance test passes.
3. Its deliverables exist.
4. No blocking issue remains undisclosed.
5. The work log has been updated.

A failed acceptance test means the phase is **not complete**.

An agent must not proceed to a dependent phase merely because the code appears mostly finished.

---

# 5. Checkpoint Rules

## Checkpoint 1 — End of Day 5

The following are blocking or required gates from the plan:

- Infrastructure/service topology is working.
- Dataset splits are isolated and reproducible.
- No-leakage model process is verified.
- Feature latency meets the defined budget.
- Calibration gates are resolved and passed.
- `Cost(TP_H)` regression behavior is correct.
- Threshold search is completed and stability is reported.
- Breakeven ratios are computed and cross-checked.

In particular:

### M03 — No-Leakage Model
Must pass before proceeding.

### M06 — Cost Engine
Must pass before proceeding to Razorpay integration.

If a blocking gate fails, the agent must stop downstream monetary integration work and fix the blocking issue first.

## Checkpoint 2 — End of Day 10

The final submission must satisfy the blocking criteria in `implementation_plan.md`, including:

- Held-out isolation.
- Correct tier cost accounting.
- Two-cutoff threshold reporting.
- Covariate-shift diagnostic without probability mutation.
- Feature latency target.
- Race-safe deduplication.
- Signature-verified Razorpay webhook handling.
- Payment-link reconciliation safety.
- LLM isolation from the synchronous response path.
- Immutable audit trail.
- Defense-only compliance review.
- Resolution of missing threshold values or explicit fallback gate list.

Never declare the project submission-ready while a blocking final criterion is failing.

---

# 6. Mandatory ML / Evaluation Integrity Rules

These rules are non-negotiable.

## Dataset boundaries

The project uses:

- `train.csv`
- `val.csv`
- `heldout.csv`

The held-out set is reserved for the final evaluation.

`heldout.csv` must not be used for:

- hyperparameter tuning;
- calibration;
- threshold selection;
- feature engineering decisions;
- model selection;
- debugging decisions based on performance.

## Model training

Hyperparameter tuning must remain inside `train.csv`.

Calibration must use the training-side calibration split described by the plan.

`val.csv` is for genuine out-of-sample evaluation and threshold selection as specified.

## Thresholds

The router uses:

```text
(t_low, t_high)
```

with three tiers:

```text
ALLOW_COD
NUDGE_PREPAY
SOFT_GATE_COD
```

Do not replace this with a single scalar threshold.

Production thresholds must be frozen after Day 5.

Day 10 may report operating points, but must not select a new production threshold using held-out results.

## Drift handling

Do not implement post-hoc probability movement toward `0.5` for `is_novel_pincode`.

Drift features should remain model inputs.

Shift behavior should be reported diagnostically, not used to mutate already calibrated predictions.

## Statistical honesty

Do not invent missing thresholds or statistical values.

If the original source does not contain a value, document the missing value and use the explicit fallback process described by the plan.

---

# 7. Mandatory Reliability / Idempotency Rules

Redis is an optimization/fast path.

The database is the durable source of truth.

The correct fallback pattern is:

```text
Redis SET NX
    ↓
if duplicate → return cached/replayed result

if Redis unavailable
    ↓
Postgres INSERT
    ↓
UNIQUE(event_id)
    ↓
constraint violation = duplicate
```

Never implement:

```text
SELECT whether event exists
        ↓
INSERT if missing
```

That SELECT→INSERT pattern is race-prone.

The database-level `UNIQUE(event_id)` constraint is mandatory.

If Postgres itself is unavailable, fail safely with `503`; do not process the event without durable deduplication.

---

# 8. Razorpay Rules

The payment path must remain deterministic and auditable.

Before payment-link creation:

1. Generate a deterministic `reference_id`.
2. Persist the pending payment-link state.
3. Call Razorpay.
4. Persist the returned link ID and state.

For ambiguous network failures:

- Do not blindly create another payment link.
- Reconcile using the deterministic reference.
- Create a new link only when reconciliation proves no existing link was created.

For `payment_link.paid` webhooks, the processing order is:

```text
Signature verification
        ↓
Event-ID deduplication
        ↓
State-transition validation
        ↓
Database update
```

Invalid signatures must be rejected before business logic executes.

---

# 9. LLM Architecture Rule

The LLM is an explanation layer.

It is **never** allowed to block the monetary execution path.

The correct flow is:

```text
Order
  ↓
Feature extraction
  ↓
Risk scoring
  ↓
Deterministic routing
  ↓
Payment action
  ↓
HTTP response
  ↓
Async Celery explanation task
  ↓
LLM / static fallback
  ↓
Persist explanation
```

The HTTP request must not wait for the LLM, including during the LLM timeout window.

The static explanation fallback belongs to the asynchronous task.

---

# 10. Testing Requirements

Every phase must have executable validation.

**IMPORTANT NOTE:** The environment is inside Docker. All Python scripts and tests MUST be executed via Docker using `docker compose exec api <command>` (if running) or `docker compose run --rm api <command>`. Do not run Python scripts directly on the host machine.

Prefer:

- `pytest`
- shell scripts for integration checks
- deterministic evaluation scripts
- Playwright or equivalent smoke checks where required

Manual observation can supplement testing but must not replace an acceptance test when the plan specifies an automated one.

Tests should validate behavior, not merely that files/imports exist.

Examples:

- duplicate requests → exactly one durable audit row;
- invalid webhook signature → 400 and no state mutation;
- Redis outage → Postgres unique constraint catches duplicate;
- LLM outage → monetary request still succeeds;
- held-out evaluation → frozen thresholds;
- final report → reproducible numbers.

---

# 11. Work Log Structure

Create:

```text
docs/
└── worklogs/
    ├── day-01.md
    ├── day-02.md
    ├── day-03.md
    ├── day-04.md
    ├── day-05.md
    ├── day-06.md
    ├── day-07.md
    ├── day-08.md
    ├── day-09.md
    └── day-10.md
```

If a phase spans multiple sessions, update the same phase log instead of creating random session logs.

Each log MUST use the following structure.

## Work Log Template

```markdown
# Day XX — <Phase Name>

## Status

- Phase status: `NOT_STARTED | IN_PROGRESS | BLOCKED | COMPLETE`
- Checkpoint impact: `<none | Checkpoint 1 | Checkpoint 2>`
- Date/session:
- Agent/session identifier:

## 1. Plan Tasks

| Plan Step | Requirement | Status |
|---|---|---|
| 1 | ... | DONE / PARTIAL / BLOCKED / NOT_STARTED |

## 2. Repository State Before Work

### Relevant files
- ...

### Existing implementation
- ...

### Existing tests
- ...

### Known failures
- ...

## 3. Pre-Implementation Assessment

### What was already correct
- ...

### What was missing
- ...

### Risks identified
- ...

### Recommended implementation order
- ...

## 4. Implementation Performed

### Changes
- ...

### Files created
- ...

### Files modified
- ...

### Files deleted
- ...

### Configuration/service changes
- ...

## 5. Validation

### Commands run
```text
...
```

### Test results
- ...

### Metrics/results
- ...

## 6. Plan Compliance Review

### Fully aligned
- ...

### Deviations
- ...

### Why deviations were necessary
- ...

### Impact on later phases
- ...

## 7. Problems Encountered

- Problem:
- Root cause:
- Fix:
- Remaining risk:

## 8. Decisions

- Decision:
- Reason:
- Alternatives rejected:

## 9. Suggestions for Next Session

- ...

## 10. Next Required Action

The next agent should:
1. ...
2. ...
3. ...

## 11. Completion Gate

- Acceptance test: PASS / FAIL
- Deliverables present: YES / NO
- Blocking issues: NONE / <list>
- Phase complete: YES / NO
```

---

# 12. What the Agent Must Record

The work log must capture **actual state changes**.

Always record:

- files created;
- files modified;
- files deleted;
- tests added;
- tests changed;
- commands run;
- test outcomes;
- metrics;
- configuration changes;
- architecture decisions;
- deviations from `implementation_plan.md`;
- unresolved failures;
- risks discovered;
- suggestions for the next phase.

Do not write vague entries such as:

> "Implemented the API."

Instead write:

> "Added `POST /v1/orders/score` in `app/api/routes.py`; added `audit_log` persistence; verified duplicate payloads produce one DB row using `scripts/test_idempotency.sh`."

The log should be useful to an agent that has never seen the previous session.

---

# 13. Agent Handoff Protocol

At the end of every session, the agent must make the repository recoverable by the next agent.

The next agent should be able to answer from the work log:

1. What was the previous agent trying to accomplish?
2. What actually changed?
3. What passed?
4. What failed?
5. Why did it fail?
6. What remains?
7. What should be done next?
8. Is proceeding safe?

The final section of every phase log must therefore contain:

```markdown
## Next Required Action

<Exact next implementation action>

## Blocking Issues

<None, or explicit list>

## Do Not Repeat

<Any failed approach, mistaken assumption, or known trap>
```

---

# 14. Git / Change Management

Use small, meaningful commits where Git is available.

Recommended commit boundaries:

- infrastructure;
- data engine;
- model/evaluation;
- cost engine;
- API/idempotency;
- Razorpay;
- LLM;
- dashboard;
- final evaluation.

Commit messages should describe the actual change.

Never rewrite history or discard another agent's work merely to make the branch look clean.

Before modifying an area touched by another recent session:

1. inspect the latest work log;
2. inspect the diff;
3. preserve valid existing work;
4. explain any replacement in the log.

---

# 15. Handling Uncertainty

When an agent encounters ambiguity:

### First
Check `implementation_plan.md`.

### Second
Check the relevant work log.

### Third
Check existing architecture/design documentation and code.

### Fourth
Inspect the source material or configuration responsible for the ambiguity.

Do not invent a value simply because the code needs one.

For example, the plan explicitly warns that missing KS/Brier values may be extraction artifacts. Confirm the original source before inventing a threshold.

When a value is genuinely unavailable, use the fallback process specified in `implementation_plan.md` and document it.

---

# 16. Scope Control

The agent must protect the must-ship path.

Priority order:

### P0 — Mandatory
Days 1–7 and final held-out evaluation.

### P1 — Important
Day 8 LLM explanation layer.

### P2 — Optional polish
Day 9 dashboard/UI polish beyond what is needed for testable fault-injection evidence.

When time is constrained, reduce UI polish and nonessential presentation work before compromising:

- evaluation integrity;
- payment safety;
- idempotency;
- webhook verification;
- deterministic routing;
- acceptance tests;
- held-out isolation.

---

# 17. Definition of Done

A phase is **DONE** only when all are true:

```text
[ ] Plan tasks completed
[ ] Required code implemented
[ ] Required tests implemented
[ ] Acceptance test passes
[ ] Required deliverables exist
[ ] Relevant architectural decisions documented
[ ] No hidden deviation from v5.md
[ ] Work log updated
[ ] Next-agent handoff written
```

A project is **FINAL** only when all Day 10 blocking gates pass.

---

# 18. Final Rule

The agent's job is not merely to produce code.

The agent must preserve the project's:

**correctness + reproducibility + evaluation integrity + reliability + security + auditability.**

Every session should leave three things behind:

1. **Working implementation**
2. **Evidence that it works**
3. **A clear log that allows the next agent to continue without guessing**

When in doubt:

**Read the plan.  
Read the latest log.  
Inspect the repository.  
Make the smallest defensible change.  
Test it.  
Log it.**
