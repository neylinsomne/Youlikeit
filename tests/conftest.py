"""
Conftest global. Fixtures compartidos por toda la suite.

Filosofía:
  - Cero llamadas reales a internet en tests `not network`.
  - Cada test recibe una DB SQLite limpia (in-memory) con todo el SCHEMA.
  - Mocks de HTTP vía `responses`; mocks de tiempo vía `freezegun`.
  - Fixtures pequeños y composable; combinar con parametrize.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

# src/ se inyecta vía `pythonpath = ["src"]` en [tool.pytest.ini_options].
ROOT = Path(__file__).resolve().parent.parent


# ── DB con schema completo ──────────────────────────────────────────


@pytest.fixture
def conn() -> sqlite3.Connection:
    """SQLite in-memory con el SCHEMA completo del proyecto cargado.

    Cada test recibe una DB nueva → cero contaminación cruzada.
    """
    from core.db import SCHEMA, _migrate_columns
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    _migrate_columns(c)
    yield c
    c.close()


# ── Seeders / fixtures de datos ─────────────────────────────────────


@pytest.fixture
def sample_signals():
    """20 señales sintéticas cubriendo los 4 dominios + repeticiones para dedupe."""
    from apps.signals.market_signals import Signal
    return [
        # Anime cluster (Frieren) — 3 fuentes mencionan
        Signal("ann_features",     "editorial_rss",     "anime_manga",
               "Frieren wins anime of the year at MAL awards",
               url="https://ann/1", summary="Massive milestone", raw_score=10),
        Signal("reddit_r_anime",   "reddit_thread",     "anime_manga",
               "Frieren beats own record at MAL",
               url="https://reddit/1", raw_score=4500),
        Signal("animefeminist",    "editorial_rss",     "anime_manga",
               "Sousou no Frieren — feminist reading",
               url="https://af/1", raw_score=8),
        # Anime cluster (Vinland Saga) — 2 fuentes
        Signal("ann_features",     "editorial_rss",     "anime_manga",
               "Vinland Saga season 3 confirmed",
               url="https://ann/2", raw_score=10),
        Signal("reddit_r_anime",   "reddit_thread",     "anime_manga",
               "Thorfinn arc finale was perfect",
               url="https://reddit/2", raw_score=3200),
        # Gaming cluster (Elden Ring) — 3 fuentes; steam_charts + steamdb_charts
        # comparten normalized_title exacto ("elden ring") → capa 1 los agrupa.
        Signal("steam_charts",     "gaming_chart",      "gaming",
               "Elden Ring", url="https://steam/1", raw_score=42, raw_meta={"rank": 8}),
        Signal("steamdb_charts",   "gaming_chart",      "gaming",
               "Elden Ring", url="https://steamdb/1", raw_score=40, raw_meta={"rank": 5}),
        Signal("opencritic",       "gaming_review",     "gaming",
               "Elden Ring still the GOTY 3 years later",
               url="https://oc/1", raw_score=18),
        Signal("reddit_r_Games",   "reddit_thread",     "gaming",
               "Elden Ring DLC retrospective",
               url="https://reddit/3", raw_score=5800),
        # Gaming cluster (Helldivers 2) — 2 fuentes
        Signal("ign_games",        "editorial_rss",     "gaming",
               "Helldivers 2 patch notes break the meta",
               url="https://ign/1", raw_score=15),
        Signal("polygon",          "editorial_rss",     "gaming",
               "Helldivers 2: when satire meets crowd-pulling design",
               url="https://polygon/1", raw_score=12),
        # Cine cluster (Hannibal) — 2 fuentes
        Signal("variety",          "editorial_rss",     "movies_tv",
               "Mads Mikkelsen on Hannibal Lecter legacy",
               url="https://variety/1", raw_score=10),
        Signal("reddit_r_TrueFilm","reddit_thread",     "movies_tv",
               "Hannibal's silent dinner scene as visual poetry",
               url="https://reddit/4", raw_score=2100),
        # LatAm cluster (Betty la fea) — 2 fuentes
        Signal("variety",          "editorial_rss",     "latam",
               "Yo soy Betty la fea reboot announced",
               url="https://variety/2", raw_score=10),
        Signal("deadline",         "editorial_rss",     "latam",
               "Betty la fea: 25 anniversary special",
               url="https://deadline/1", raw_score=9),
        # Solo (sin cluster — no debería ganar)
        Signal("ign_games",        "editorial_rss",     "gaming",
               "Some random gaming news nobody else covers",
               url="https://ign/2", raw_score=2),
        # Cluster sin slug match en CATALOG (debe ir a unresolved)
        Signal("reddit_r_anime",   "reddit_thread",     "anime_manga",
               "Dandadan is the show of the decade",
               url="https://reddit/5", raw_score=4200),
        Signal("ann_features",     "editorial_rss",     "anime_manga",
               "Dandadan adapted by Science Saru",
               url="https://ann/3", raw_score=8),
    ]


@pytest.fixture
def seeded_db(conn, sample_signals):
    """DB con señales pre-insertadas. Lista para distill."""
    from apps.signals.market_signals import _persist_many
    _persist_many(conn, sample_signals)
    return conn


@pytest.fixture
def seeded_briefs_db(seeded_db):
    """DB con señales + briefs ya destilados (sin LLM)."""
    from apps.signals.signals_distiller import distill
    distill(seeded_db, settings=None, use_llm=False, window_days=7, top_per_persona=8)
    return seeded_db


# ── Tiempo controlado ──────────────────────────────────────────────


@pytest.fixture
def frozen_time():
    """Tiempo congelado en una fecha estable. Permite tests deterministas."""
    from freezegun import freeze_time
    with freeze_time("2026-05-29 10:00:00") as f:
        yield f


# ── HTTP mock ──────────────────────────────────────────────────────


@pytest.fixture
def mocked_http():
    """Activar `responses` para tests que invocan HTTP."""
    import responses
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        yield rsps


# ── Fixtures de archivos / temp paths ──────────────────────────────


@pytest.fixture
def tmp_outputs(tmp_path, monkeypatch):
    """Redirige outputs/ a tmp_path para tests que tocan disco."""
    out = tmp_path / "outputs"
    out.mkdir()
    (out / "produce").mkdir()
    monkeypatch.chdir(tmp_path)
    return out


# ── Defensive: nunca hacer HTTP real desde tests `not network` ─────


@pytest.fixture(autouse=True)
def no_real_http(request, monkeypatch):
    """Por defecto, intercepta requests.get/post fuera del marker `network`.

    Tests que necesitan HTTP real declaran `@pytest.mark.network` y este
    fixture no aplica.

    Tests que usan `mocked_http` siguen funcionando porque `responses`
    intercepta a nivel del adapter de sesión.
    """
    if "network" in request.keywords:
        return
    if "mocked_http" in request.fixturenames:
        # responses ya intercepta — no hace falta el doble guard
        return

    def _forbidden(*args, **kwargs):
        raise RuntimeError(
            f"Llamada HTTP real bloqueada (sin marker @pytest.mark.network ni mocked_http): "
            f"args={args[:1]}"
        )

    import requests
    # Nivel Session (pooling) …
    monkeypatch.setattr(requests.Session, "get", lambda *a, **k: _forbidden(*a, **k))
    monkeypatch.setattr(requests.Session, "post", lambda *a, **k: _forbidden(*a, **k))
    monkeypatch.setattr(requests.Session, "request", lambda *a, **k: _forbidden(*a, **k))
    # … y nivel módulo (requests.get/post directos, p.ej. trending_anime.py).
    # Sin esto, un módulo que llama requests.get(url, timeout=15) directo NO
    # queda cubierto y el test se cuelga ~15s por request contra red real.
    monkeypatch.setattr(requests, "get", lambda *a, **k: _forbidden(*a, **k))
    monkeypatch.setattr(requests, "post", lambda *a, **k: _forbidden(*a, **k))


# ── Env vars seguras por default ───────────────────────────────────


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Limpia API keys de los tests para evitar pegarle a la red real."""
    for key in ("GEMINI_API_KEY", "GROQ_API_KEY", "TMDB_API_KEY",
                "TRAKT_CLIENT_ID", "LASTFM_API_KEY"):
        monkeypatch.delenv(key, raising=False)
