"""Celery application instance.

Broker  : RabbitMQ  (aligns with architecture_decision_log.md — issue #4 fix)
Backend : Redis

Tasks are discovered automatically from app.services.*
"""

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "risk_manager",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        # "app.services.llm_explain",  # Day 8 — async LLM task
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    # Retry policy defaults
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)
