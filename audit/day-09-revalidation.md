# Day 09 Audit Revalidation

Date/session: 2026-08-28 IST  
Scope: Revalidation of the pasted "Day 09 Audit - End-to-End System Integration, Resiliency & Audit Trail" against the current repository and live Docker worker state.

## Verdict

The pasted Day 09 audit is partially valid.

The two operational blockers are valid and still present:

1. Celery only registers `app.services.scoring.score_order_task`; payment-link and LLM tasks are not registered in the live worker.
2. Redis-down Postgres fallback can leave placeholder `audit_log` rows with `score`, `tier`, and `action` unset because the later Celery scorer catches the duplicate insert and does not update the placeholder.

However, the pasted audit contains one material false finding:

- The claim that `cost_tp_h_abandoned()` should return friction cost `3 * 15 = 45` is incorrect. Current specs require the abandoned/canceled high-risk branch to be zero freight-loss and zero branch cost. The confirmed branch carries `Friction_Cost_H + r_residual * C_RTO`, weighted by `alpha_H`.

Therefore the correct Day 09 verdict remains:

**PARTIAL PASS / NOT CLEAN FOR CHECKPOINT 2**

But the remediation list must be corrected: do not change `cost_tp_h_abandoned()` to 45.

## Revalidated Findings

| Pasted Finding | Revalidation Status | Current Evidence | Auditor Decision |
|---|---|---|---|
| A-DAY09-001 Celery worker task registration failure | VALID | `celery inspect registered` shows only `app.services.scoring.score_order_task`; `app/core/celery_app.py` includes only `app.services.scoring`; recent `risk_celery` logs show `Received unregistered task` for `app.services.llm_explain.explain_order_task` | Blocking |
| Payment task unregistered | VALID | `app/services/payment_tasks.py` defines `create_payment_link_task` with `@shared_task`, but it is not imported in Celery app startup include/imports; historical logs show `app.services.payment_tasks.create_payment_link_task` unregistered | Blocking |
| A-DAY09-002 Redis-down Postgres fallback scoring fails to complete | VALID BY CODE | `app/api/routes.py` inserts placeholder row through `insert_audit_log()` when Redis is down; `app/services/scoring.py` later calls `_insert_audit_log_sync()` and returns existing duplicate row without updating it | High |
| A-DAY09-003 abandoned high-risk path should cost 45 | INVALID | `docs/track02_spec_reference.md` states `Cost(TP_H) = TP_H * [(1-alpha_H)*0 + alpha_H*(Friction_Cost_H + r_residual*C_RTO)]`; `Implementation_plan.md` requires zero freight-loss branch; `app/ml/costs.py` matches this | Remove this finding |
| A-DAY09-004 training script reads val at initialization | PARTIALLY VALID / LOW | `scripts/train_model.py` reads `val.csv` before fitting, but CV and calibration still use train internal splits only; no evidence val labels enter model selection/calibration | Low hygiene issue only |
| A-DAY09-005 placeholder Razorpay credentials | VALID | `.env` contains `RAZORPAY_KEY_ID=rzp_test_CHANGEME`, `RAZORPAY_KEY_SECRET=CHANGEME`, and `RAZORPAY_WEBHOOK_SECRET=whsec_CHANGEME` | Config blocker for live sandbox demo, not unit tests |
| Health evidence body shape | MINOR INACCURACY | Actual `/health` shape uses `{"overall":"ok","dependencies":{"postgres":{"status":"ok"},...}}`, not flat dependency strings | Correct wording in final audit |
| Full test suite passed | TRUE BUT INSUFFICIENT | User-provided run: 85 passed; tests do not prove live Celery registry includes payment/LLM tasks | Keep as test evidence, not operational sign-off |

## Corrected Remediation List

1. Update `app/core/celery_app.py` so the worker registers all runtime-dispatched tasks at startup:
   - `app.services.scoring`
   - `app.services.payment_tasks`
   - `app.services.llm_explain`

2. Restart the Celery worker and verify:
   - `celery -A app.core.celery_app inspect registered`
   - Expected registry includes `app.services.payment_tasks.create_payment_link_task` and `app.services.llm_explain.explain_order_task`.

3. Fix Redis-down fallback completion:
   - Either do not create an incomplete placeholder that the scorer later treats as a duplicate, or
   - teach `score_order_task` to update the existing placeholder row when it finds one with null score/tier/action, then commit the completed result.

4. Add an integration test that simulates Redis unavailable and asserts eventual durable completion:
   - POST returns 202 or a documented fallback response.
   - Polling result eventually returns non-null `score`, `tier`, `action`, and `shap_top3`.

5. Keep `cost_tp_h_abandoned()` returning `0`.
   - Do not apply the pasted remediation suggesting `3 * 15`.
   - The current cost formula is aligned with the authoritative financial math.

6. Optional hygiene: defer `val.csv` loading in `scripts/train_model.py` until after training/calibration to make the no-leakage story cleaner.

7. Replace placeholder Razorpay/OpenRouter credentials before any live sandbox demo.

## Final Revalidation Decision

The pasted audit is valid enough to block a clean Checkpoint 2 sign-off because the Celery task registration and Redis-down fallback defects are real. It is not valid as a direct patch checklist because the cost-engine remediation is mathematically wrong.
