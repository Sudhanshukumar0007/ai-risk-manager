# Day 8: OpenRouter LLM Explanations

## Objective
Substitute the originally planned Anthropic integration with OpenRouter (Llama 3.1 8B Instruct) for generating natural language explanations of RTO scores, and ensure robust error handling with deterministic fallbacks.

## Changes
1. **Configuration**: Added `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, and `LLM_TIMEOUT_SECONDS` to `.env` and `app/core/config.py`.
2. **Database**: Implemented the `LLMExplanation` model with a `created_at` field to track creation time.
3. **LLM Service Refactor**:
   - Swapped the `anthropic` library for `openai` to interact with OpenRouter.
   - Refactored `llm_explain.py` with `_explain_order_async` for true async OpenRouter calls.
   - Implemented a robust `try/except Exception` around the LLM call that falls back to writing a static row (`status="fallback"`) on timeouts or errors.
4. **Scoring Dispatch**: Updated `app/services/scoring.py` to dispatch `explain_order_task.delay()` at the end of `score_order_task`.
5. **API Contract**: Validated that `GET /v1/orders/{event_id}/result` correctly surfaces the LLM explanation and its status (`pending`, `complete`, or `fallback`).
6. **Testing**: Rewrote `tests/test_llm_fallback.py` to test the new OpenRouter implementation, with 7 test cases covering happy path, timeouts, exceptions, duplicated posts, and HTTP endpoints. All 9 tests passed.

## Notes
- **Scope Decision: OpenRouter Substitution**: Substituted the Anthropic integration with OpenRouter (Llama 3.1 8B Instruct) due to API key constraints.
- **Scope Decision: Pending Detection**: `GET /v1/orders/{event_id}/result` uses a simplified approach to detect pending states. If an `llm_explanations` row does not exist, the API immediately returns `explanation_status: "pending"`. It does not attempt to distinguish between "in-flight task" and "not yet dispatched", saving complexity and extra polling while providing the correct UI semantic.
- OpenRouter integration is completely decoupled from the main critical path. 
- The Celery timeout is enforced by `asyncio.wait_for` internally, guaranteeing we never block indefinitely.
- The `openai` package was installed in the backend to support the OpenRouter API.
- Fixed a silent failure bug where the Celery task could exit immediately if it encountered a running asyncio loop, replacing it with a robust `asyncio.run` block and top-level crash handler.
