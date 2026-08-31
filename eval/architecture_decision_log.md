# Architecture Decision Log

This file records all major architectural decisions made during the 10-day
AI Risk Manager build. Each entry is immutable once committed — superseding
decisions create a new entry rather than editing an old one.

---

## ADR-001 — Celery Message Broker: RabbitMQ (not Redis-only)

**Date:** Day 1  
**Status:** Decided  
**Decided by:** Day 1 implementation session  

### Context

The architecture narrative states:

> "Celery distributed task queue backed by RabbitMQ."

However, the original Day 1 `docker-compose.yml` listed only four services
(PostgreSQL, Redis, FastAPI, Celery worker) and omitted RabbitMQ entirely.
This was identified as **Issue #4** in the implementation plan audit.

Two options were available:

| Option | Broker | Notes |
|---|---|---|
| A (chosen) | **RabbitMQ 3** | Matches architecture narrative; separate AMQP broker; management UI at :15672 |
| B | Redis as broker | Simpler; one fewer container; contradicts architecture narrative |

### Decision

**Option A — RabbitMQ 3 (management image)** is used as the Celery broker.

- Celery `CELERY_BROKER_URL = amqp://risk_user:risk_pass@rabbitmq:5672/`
- Redis remains the **result backend** only (`CELERY_RESULT_BACKEND = redis://redis:6379/1`)
- This means the production stack has **five** services, as required.

### Consequences

- `docker-compose.yml` contains five services with proper `depends_on: condition: service_healthy` chains.
- All agents on Days 6–8 that write Celery tasks must use `from app.core.celery_app import celery_app` — never re-instantiate Celery with a different broker.
- Day 10 architecture docs must reflect this decision.

### Affected files

- `docker-compose.yml`
- `app/core/celery_app.py`
- `.env.example`

---

## ADR-002 — Idempotency Pattern: Insert-and-Catch (not SELECT→INSERT)

**Date:** Day 1 (pre-wired for Day 6 implementation)  
**Status:** Decided  
**Decided by:** Issue #5 fix in implementation plan  

### Decision

The idempotency path for duplicate webhook/order events uses:

```
Redis SET NX (fast path, 24h TTL)
  ↓ if key already present → return cached result (no DB hit)

If Redis is unavailable:
  ↓ Postgres INSERT
  ↓ catch UNIQUE constraint violation on event_id
  ↓ if caught → treat as duplicate, return cached/replayed result

If Postgres also unavailable → return HTTP 503
```

**Never** implement `SELECT ... WHERE event_id = ?` followed by a conditional
`INSERT` — the gap between those two statements is a race window that allows
two concurrent requests to both pass the existence check.

This decision is documented here so it cannot be silently changed during
Day 6 implementation.

---

## ADR-003 — LLM on Async Path Only (never blocking monetary response)

**Date:** Day 1 (pre-wired for Day 8 implementation)  
**Status:** Decided  
**Decided by:** Issue #10 fix in implementation plan  

### Decision

```
POST /v1/orders/score
  ↓ feature extraction
  ↓ risk scoring
  ↓ deterministic routing
  ↓ Razorpay payment action (if required)
  ↓ HTTP response returned  ← response ends HERE
  ↓ (async) Celery task dispatched
       ↓ LLM explanation call (2,500ms timeout)
       ↓ static fallback on timeout/failure
       ↓ write explanation to audit_log row
```

The HTTP response must never wait for the LLM — not even for the 2,500ms
timeout window. The Celery task is fire-and-forget from the request handler's
perspective.

---

*End of log. Add new ADRs below this line as they are decided.*
