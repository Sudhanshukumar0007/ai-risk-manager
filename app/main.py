"""AI Risk Manager — FastAPI application entry point.

Day 1 implements:
  GET /health  — per-dependency liveness check (DB, Redis, RabbitMQ broker)

Subsequent days add:
  POST /v1/orders/score
  POST /v1/webhooks/razorpay
"""

import asyncio
import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
import aio_pika
import asyncpg
from fastapi import FastAPI, status
from fastapi.responses import JSONResponse

from app.core.config import settings

logger = logging.getLogger(__name__)

# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    logger.info("Starting AI Risk Manager API (env=%s)", settings.app_env)
    yield
    logger.info("Shutting down AI Risk Manager API")


# ── FastAPI instance ──────────────────────────────────────────────────────────
app = FastAPI(
    title="AI Risk Manager",
    description="COD Return-to-Origin risk scoring and Razorpay payment integration",
    version="0.1.0",
    lifespan=lifespan,
)


# ── Dependency health helpers ─────────────────────────────────────────────────

async def _check_postgres() -> dict:
    """Attempt a lightweight Postgres connection."""
    try:
        # Use the sync DSN parts — asyncpg expects host/port/user/pass/db
        # We parse them from the async URL: postgresql+asyncpg://user:pass@host:port/db
        dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
        conn = await asyncio.wait_for(asyncpg.connect(dsn), timeout=3.0)
        await conn.execute("SELECT 1")
        await conn.close()
        return {"status": "ok"}
    except asyncio.TimeoutError:
        return {"status": "timeout"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


async def _check_redis() -> dict:
    """Attempt a Redis PING."""
    try:
        client = aioredis.from_url(settings.redis_url, socket_timeout=3.0)
        pong = await asyncio.wait_for(client.ping(), timeout=3.0)
        await client.aclose()
        return {"status": "ok"} if pong else {"status": "error", "detail": "no pong"}
    except asyncio.TimeoutError:
        return {"status": "timeout"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


async def _check_rabbitmq() -> dict:
    """Attempt an AMQP connection to RabbitMQ."""
    try:
        connection = await asyncio.wait_for(
            aio_pika.connect_robust(settings.rabbitmq_url),
            timeout=5.0,
        )
        await connection.close()
        return {"status": "ok"}
    except asyncio.TimeoutError:
        return {"status": "timeout"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get(
    "/health",
    summary="Per-dependency health check",
    response_description="JSON status for each dependency",
    tags=["infra"],
)
async def health() -> JSONResponse:
    """
    Returns individual health status for every backing service.
    A flat 200 only means the web process is alive; per-dependency status
    catches partial outages immediately (Day 1 plan step 5).
    """
    postgres_status, redis_status, rabbitmq_status = await asyncio.gather(
        _check_postgres(),
        _check_redis(),
        _check_rabbitmq(),
    )

    all_ok = all(
        s.get("status") == "ok"
        for s in [postgres_status, redis_status, rabbitmq_status]
    )

    payload = {
        "service": "ai-risk-manager",
        "overall": "ok" if all_ok else "degraded",
        "dependencies": {
            "postgres": postgres_status,
            "redis": redis_status,
            "rabbitmq": rabbitmq_status,
        },
    }

    http_status = status.HTTP_200_OK if all_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(content=payload, status_code=http_status)


@app.get("/", include_in_schema=False)
async def root():
    return {"message": "AI Risk Manager — see /health or /docs"}
