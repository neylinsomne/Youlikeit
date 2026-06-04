"""
Fixtures del dominio analytics — respuestas sintéticas de la Plausible Stats API.

Reutiliza los fixtures globales (`conn`, `mocked_http`, `clean_env`) de
tests/conftest.py. Aquí solo añadimos payloads de Plausible y un helper para
registrarlos en `responses`.
"""

from __future__ import annotations

import pytest

TEST_BASE_URL = "http://test.plausible.local"
TEST_API_KEY = "test-key-abc123"
TEST_SITE_ID = "youlikeit.test"


# ── Payloads (forma real de la Stats API v1) ─────────────────────────


@pytest.fixture
def aggregate_payload() -> dict:
    return {
        "results": {
            "visitors": {"value": 142},
            "pageviews": {"value": 318},
            "bounce_rate": {"value": 47.0},
            "visit_duration": {"value": 88.0},
        }
    }


@pytest.fixture
def breakdown_pages_payload() -> dict:
    return {
        "results": [
            {"page": "/", "visitors": 88, "pageviews": 140,
             "bounce_rate": 40.0, "visit_duration": 95.0},
            {"page": "/dashboard.html", "visitors": 33, "pageviews": 60,
             "bounce_rate": 52.0, "visit_duration": 70.0},
            {"page": "/contact.html", "visitors": 21, "pageviews": 28,
             "bounce_rate": 61.0, "visit_duration": 40.0},
        ]
    }


@pytest.fixture
def breakdown_goals_payload() -> dict:
    return {
        "results": [
            {"goal": "cta_click", "visitors": 30, "events": 41},
            {"goal": "persona_click", "visitors": 12, "events": 15},
        ]
    }


@pytest.fixture
def timeseries_payload() -> dict:
    return {
        "results": [
            {"date": "2026-05-26", "visitors": 10},
            {"date": "2026-05-27", "visitors": 18},
            {"date": "2026-05-28", "visitors": 25},
        ]
    }


@pytest.fixture
def health_payload() -> dict:
    return {"clickhouse": "ok", "postgres": "ok"}


# ── Helpers ──────────────────────────────────────────────────────────


@pytest.fixture
def register_stats(mocked_http):
    """Devuelve un registrador: register_stats(endpoint, payload)."""
    import responses

    def _reg(endpoint: str, payload: dict, status: int = 200):
        mocked_http.add(
            responses.GET,
            f"{TEST_BASE_URL}/api/v1/stats/{endpoint}",
            json=payload,
            status=status,
        )
        return mocked_http

    return _reg


@pytest.fixture
def no_plausible_key(monkeypatch):
    """Garantiza que no haya PLAUSIBLE_API_KEY en el entorno."""
    monkeypatch.delenv("PLAUSIBLE_API_KEY", raising=False)
    monkeypatch.delenv("PLAUSIBLE_BASE_URL", raising=False)
