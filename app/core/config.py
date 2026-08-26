"""Application settings — loaded from environment / .env file."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────────────────
    app_env: str = "development"
    log_level: str = "INFO"
    secret_key: str = "changeme"

    # ── Database ─────────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://risk_user:risk_pass@postgres:5432/risk_db"
    database_url_sync: str = "postgresql://risk_user:risk_pass@postgres:5432/risk_db"

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = "redis://redis:6379/0"

    # ── RabbitMQ / Celery ────────────────────────────────────────────────────
    rabbitmq_url: str = "amqp://risk_user:risk_pass@rabbitmq:5672/"
    celery_broker_url: str = "amqp://risk_user:risk_pass@rabbitmq:5672/"
    celery_result_backend: str = "redis://redis:6379/1"

    # ── Razorpay ─────────────────────────────────────────────────────────────
    razorpay_key_id: str = "rzp_test_CHANGEME"
    razorpay_key_secret: str = "CHANGEME"
    razorpay_webhook_secret: str = "whsec_CHANGEME"

    # ── Anthropic / Claude ────────────────────────────────────────────────────
    anthropic_api_key: str = "sk-ant-CHANGEME"


settings = Settings()
