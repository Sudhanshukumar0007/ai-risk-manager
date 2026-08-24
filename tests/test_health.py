"""
Day 1 Acceptance Test — Health endpoint.

Asserts:
  1. GET /health returns HTTP 200.
  2. The JSON body contains an "overall": "ok" field.
  3. Every individual dependency key (postgres, redis, rabbitmq)
     is present in the response and reports "ok".

Run against the live Docker stack:
    pytest tests/test_health.py -v

The test reads API_BASE_URL from the environment (default: http://localhost:8000)
so it can also run in CI against a deployed environment.
"""

import os

import pytest
import requests

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")
REQUIRED_DEPS = {"postgres", "redis", "rabbitmq"}


def test_health_returns_200():
    """Health endpoint must return HTTP 200 when all deps are up."""
    resp = requests.get(f"{API_BASE}/health", timeout=10)
    assert resp.status_code == 200, (
        f"Expected 200 but got {resp.status_code}. Body: {resp.text}"
    )


def test_health_body_overall_ok():
    """Response body must contain overall='ok'."""
    resp = requests.get(f"{API_BASE}/health", timeout=10)
    data = resp.json()
    assert data.get("overall") == "ok", (
        f"Expected overall='ok', got: {data}"
    )


def test_health_all_dependencies_present():
    """Response body must contain a 'dependencies' key with all expected services."""
    resp = requests.get(f"{API_BASE}/health", timeout=10)
    data = resp.json()
    deps = data.get("dependencies", {})
    missing = REQUIRED_DEPS - set(deps.keys())
    assert not missing, f"Missing dependency keys in response: {missing}"


def test_health_each_dependency_ok():
    """Every individual dependency must report status='ok'."""
    resp = requests.get(f"{API_BASE}/health", timeout=10)
    data = resp.json()
    deps = data.get("dependencies", {})
    failures = {
        name: info
        for name, info in deps.items()
        if info.get("status") != "ok"
    }
    assert not failures, (
        f"The following dependencies are not healthy: {failures}"
    )


def test_health_response_has_service_field():
    """Response must identify the service by name."""
    resp = requests.get(f"{API_BASE}/health", timeout=10)
    data = resp.json()
    assert "service" in data, f"Missing 'service' field in: {data}"
    assert data["service"] == "ai-risk-manager"
