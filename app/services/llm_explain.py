"""LLM Explanation service.

Generates a merchant-facing explanation for the risk decision using the OpenRouter API.
This is implemented as a Celery task dispatched *after* the scoring response
has returned to the client, ensuring that LLM latency never blocks the monetary
request path.
"""

import logging
import asyncio
from typing import Any

import openai
from celery import shared_task
from sqlalchemy import text
from app.db.models import LLMExplanation
from app.services.scoring import _get_sync_session

from app.core.config import settings

logger = logging.getLogger(__name__)

STATIC_FALLBACK = "Flagged for manual review — explanation unavailable"

# Lazy singleton for the OpenRouter client
_openrouter_client = None

def get_openrouter_client() -> openai.AsyncOpenAI:
    global _openrouter_client
    if _openrouter_client is None:
        _openrouter_client = openai.AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.openrouter_api_key or "CHANGEME"
        )
    return _openrouter_client

def build_explanation_prompt(score: float, tier: str, shap_top3: list[dict[str, Any]]) -> str:
    """Pure function to build the LLM prompt."""
    return f"""
Please provide a 1-sentence explanation for a merchant about why this order was flagged.
Context:
- Risk Score: {score:.4f}
- Action Tier: {tier}
- Top 3 risk factors (SHAP):
{shap_top3}

Keep it professional, objective, and under 25 words.
"""

async def call_openrouter_api(prompt: str) -> str:
    """Raw LLM call that applies HTTP timeout and raises on failure."""
    if not settings.openrouter_api_key or settings.openrouter_api_key.endswith("CHANGEME"):
        raise ValueError("OpenRouter API key is not configured.")
        
    client = get_openrouter_client()
    
    # timeout applied at HTTP client level
    response = await client.chat.completions.create(
        model=settings.openrouter_model,
        messages=[
            {"role": "system", "content": "You are a risk analysis assistant writing concise notes for merchants."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=50,
        temperature=0.0,
        timeout=settings.llm_timeout_seconds
    )
    return response.choices[0].message.content.strip()

def _save_explanation_sync(event_id: str, order_id: str, explanation_text: str, status: str) -> None:
    """Save the explanation to the llm_explanations table synchronously."""
    session = _get_sync_session()
    try:
        row = LLMExplanation(
            event_id=event_id,
            order_id=order_id,
            explanation_text=explanation_text,
            status=status,
        )
        session.add(row)
        session.commit()
        logger.info("Saved LLM explanation for event_id=%s (status=%s)", event_id, status)
    except Exception as exc:
        session.rollback()
        # If it's a unique violation, we already have an explanation.
        if "unique" in str(exc).lower() or "duplicate key" in str(exc).lower():
            logger.info("LLM explanation already exists for event_id=%s", event_id)
        else:
            logger.error("Failed to save LLM explanation for event_id=%s: %s", event_id, exc)
    finally:
        session.close()

async def _explain_order_async(event_id: str, order_id: str, shap_top3: list[dict[str, Any]], score: float, tier: str) -> str:
    """Async core of explain_order_task that just fetches the explanation."""
    prompt = build_explanation_prompt(score, tier, shap_top3)
    return await call_openrouter_api(prompt)

@shared_task(bind=True, name="app.services.llm_explain.explain_order_task", max_retries=0)
def explain_order_task(self, event_id: str, order_id: str, shap_top3: list[dict[str, Any]], score: float, tier: str) -> None:
    """Celery task to generate an LLM explanation."""
    logger.info("Executing explain_order_task for event_id=%s (order_id=%s)", event_id, order_id)
    try:
        # Try the LLM call
        explanation_text = asyncio.run(_explain_order_async(event_id, order_id, shap_top3, score, tier))
        _save_explanation_sync(event_id, order_id, explanation_text, "complete")
    except Exception as exc:
        logger.error("LLM explanation failed for event_id=%s, falling back. Error: %s", event_id, exc)
        try:
            _save_explanation_sync(event_id, order_id, STATIC_FALLBACK, "fallback")
        except Exception as fallback_exc:
            logger.critical("CRITICAL: Fallback write also failed for event_id=%s! Error: %s", event_id, fallback_exc)

