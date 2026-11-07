"""
Plausible Stats API client — capa de lectura de tráfico del sitio público.

Consume la Stats API v1 de una instancia Plausible **self-hosted**
(`analytics.vara-alta.lat`) y devuelve JSON normalizado. Es la fuente de
`plausible_pageviews` / `plausible_events` y, vía `internal_signals`, alimenta
`market_signals` como dominio `internal`.

Diseño:
  - Síncrono, usa `http_client.api_get` (mismo helper que el resto del repo —
    NO `httpx`/async).
  - Auth por `Authorization: Bearer {PLAUSIBLE_API_KEY}` desde env var.
  - Cache opcional de 1h en SQLite (`plausible_cache`) para no martillar la API.
  - Cero PII: solo agregados (visitors, pageviews, bounce_rate, ...). Plausible
    ya no recolecta IPs ni user agents; mantenemos esa propiedad end-to-end.

Env vars:
    PLAUSIBLE_BASE_URL   default https://analytics.vara-alta.lat
    PLAUSIBLE_API_KEY    (requerida para llamadas reales)
    PLAUSIBLE_SITE_ID    default youlikeit.vara-alta.lat

API pública:
    from apps.analytics.plausible_client import (
        fetch_aggregate, fetch_breakdown, fetch_timeseries,
    )

    # Visitas + pageviews + bounce en los últimos 7 días
    agg = fetch_aggregate(period="7d",
                          metrics=["visitors", "pageviews", "bounce_rate"])
    # → {"results": {"visitors": {"value": 142}, ...}}

    # Top páginas por visitantes (30 días), cacheado en `conn`
    top = fetch_breakdown(property="event:page", period="30d",
                         metrics=["visitors"], conn=conn)
    # → {"results": [{"page": "/", "visitors": 88}, ...]}

    # Serie temporal diaria de visitantes
    ts = fetch_timeseries(period="30d", metrics=["visitors"])
    # → {"results": [{"date": "2026-05-01", "visitors": 12}, ...]}

Ref: https://plausible.io/docs/stats-api
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import time
from typing import Iterable

from utils.http_client import api_get

log = logging.getLogger(__name__)


# ── Config (env-driven, nunca hardcodeada) ───────────────────────────

DEFAULT_BASE_URL = "https://analytics.vara-alta.lat"
DEFAULT_SITE_ID = "youlikeit.vara-alta.lat"
CACHE_TTL_SECONDS = 3600  # 1h


class PlausibleConfigError(RuntimeError):
    """Falta una variable de entorno requerida (p.ej. PLAUSIBLE_API_KEY)."""


def _base_url(override: str | None = None) -> str:
    return (override or os.getenv("PLAUSIBLE_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")


def _site_id(override: str | None = None) -> str:
    return override or os.getenv("PLAUSIBLE_SITE_ID", DEFAULT_SITE_ID)


def _api_key(override: str | None = None) -> str:
    key = override or os.getenv("PLAUSIBLE_API_KEY", "")
    if not key:
        raise PlausibleConfigError(
            "PLAUSIBLE_API_KEY no está en el entorno. Generala en el panel "
            "(Site Settings → API Keys) y exportala antes de llamar a la Stats API."
        )
    return key


def _auth_headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


# ── Cache (SQLite, opcional) ──────────────────────────────────────────


def _params_hash(endpoint: str, params: dict) -> str:
    """Hash estable de (endpoint + params ordenados). Clave de cache."""
    payload = endpoint + "|" + json.dumps(params, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_get(conn: sqlite3.Connection, endpoint: str, phash: str,
               ttl: int = CACHE_TTL_SECONDS) -> dict | None:
    """Devuelve el JSON cacheado si existe y no expiró; si no, None."""
    try:
        row = conn.execute(
            """SELECT json, strftime('%s','now') - strftime('%s', fetched_at) AS age
                 FROM plausible_cache
                WHERE endpoint = ? AND params_hash = ?""",
            (endpoint, phash),
        ).fetchone()
    except sqlite3.Error as e:
        log.debug("cache_get skip: %s", e)
        return None
    if not row:
        return None
    age = row["age"] if isinstance(row, sqlite3.Row) else row[1]
    if age is None or int(age) > ttl:
        return None
    raw = row["json"] if isinstance(row, sqlite3.Row) else row[0]
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _cache_put(conn: sqlite3.Connection, endpoint: str, phash: str, data: dict) -> None:
    """Guarda/actualiza la respuesta en cache. Idempotente por (endpoint, hash)."""
    try:
        conn.execute(
            """INSERT INTO plausible_cache (endpoint, params_hash, json, fetched_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(endpoint, params_hash)
                    DO UPDATE SET json = excluded.json, fetched_at = CURRENT_TIMESTAMP""",
            (endpoint, phash, json.dumps(data, ensure_ascii=False)),
        )
        conn.commit()
    except sqlite3.Error as e:
        log.warning("cache_put failed (%s): %s", endpoint, e)


# ── Núcleo de request ─────────────────────────────────────────────────


def _stats_request(
    endpoint: str,
    params: dict,
    *,
    conn: sqlite3.Connection | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    ttl: int = CACHE_TTL_SECONDS,
) -> dict | None:
    """GET a /api/v1/stats/{endpoint} con auth, cache y rate-limit.

    `endpoint` es uno de: 'aggregate' | 'breakdown' | 'timeseries'.
    Devuelve el dict JSON de Plausible o None si la llamada falla.
    """
    # Limpieza: dropear params None para hash y request estables.
    clean = {k: v for k, v in params.items() if v is not None}
    phash = _params_hash(endpoint, clean)

    if conn is not None:
        cached = _cache_get(conn, endpoint, phash, ttl)
        if cached is not None:
            log.debug("[plausible] cache hit %s %s", endpoint, phash[:8])
            return cached

    key = _api_key(api_key)
    url = f"{_base_url(base_url)}/api/v1/stats/{endpoint}"

    t0 = time.time()
    data = api_get(
        url,
        params=clean,
        service="plausible",
        headers=_auth_headers(key),
        timeout=15,
    )
    dur_ms = (time.time() - t0) * 1000
    if dur_ms > 500:
        log.warning("[plausible] %s tardó %.0fms (p95 target <500ms)", endpoint, dur_ms)

    if not isinstance(data, dict):
        log.warning("[plausible] %s respuesta no-JSON o vacía: %r", endpoint, data)
        return None

    if conn is not None:
        _cache_put(conn, endpoint, phash, data)
    return data


def _csv(metrics: Iterable[str] | str) -> str:
    """Normaliza metrics a CSV (acepta lista o string ya CSV)."""
    if isinstance(metrics, str):
        return metrics
    return ",".join(metrics)


# ── API pública ───────────────────────────────────────────────────────


def fetch_aggregate(
    *,
    site_id: str | None = None,
    period: str = "7d",
    metrics: Iterable[str] | str = ("visitors", "pageviews", "bounce_rate", "visit_duration"),
    conn: sqlite3.Connection | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    **extra,
) -> dict | None:
    """Métricas agregadas del sitio para un periodo.

    Ejemplo:
        >>> fetch_aggregate(period="30d", metrics=["visitors", "pageviews"])
        {"results": {"visitors": {"value": 412}, "pageviews": {"value": 980}}}

    `period`: '12mo' | '6mo' | 'month' | '30d' | '7d' | 'day' | 'custom' ...
    `extra` se pasa tal cual como query params (p.ej. filters="event:page==/dashboard.html").
    """
    params = {"site_id": _site_id(site_id), "period": period, "metrics": _csv(metrics)}
    params.update(extra)
    return _stats_request("aggregate", params, conn=conn, base_url=base_url, api_key=api_key)


def fetch_breakdown(
    *,
    property: str = "event:page",
    site_id: str | None = None,
    period: str = "7d",
    metrics: Iterable[str] | str = ("visitors",),
    limit: int = 100,
    page: int = 1,
    conn: sqlite3.Connection | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    **extra,
) -> dict | None:
    """Breakdown por una propiedad (páginas, eventos, fuentes...).

    Ejemplo (top páginas):
        >>> fetch_breakdown(property="event:page", period="30d", metrics=["visitors"])
        {"results": [{"page": "/", "visitors": 88}, {"page": "/dashboard.html", ...}]}

    Ejemplo (custom events):
        >>> fetch_breakdown(property="event:goal", period="30d", metrics=["events"])

    `property`: 'event:page' | 'event:goal' | 'visit:source' | 'event:props:persona' ...
    """
    params = {
        "site_id": _site_id(site_id),
        "period": period,
        "property": property,
        "metrics": _csv(metrics),
        "limit": limit,
        "page": page,
    }
    params.update(extra)
    return _stats_request("breakdown", params, conn=conn, base_url=base_url, api_key=api_key)


def fetch_timeseries(
    *,
    site_id: str | None = None,
    period: str = "30d",
    metrics: Iterable[str] | str = ("visitors",),
    interval: str | None = None,
    conn: sqlite3.Connection | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    **extra,
) -> dict | None:
    """Serie temporal de una métrica.

    Ejemplo:
        >>> fetch_timeseries(period="7d", metrics=["visitors"])
        {"results": [{"date": "2026-05-26", "visitors": 10}, ...]}

    `interval`: 'date' (diario) | 'month'. Default lo decide Plausible por period.
    """
    params = {
        "site_id": _site_id(site_id),
        "period": period,
        "metrics": _csv(metrics),
        "interval": interval,
    }
    params.update(extra)
    return _stats_request("timeseries", params, conn=conn, base_url=base_url, api_key=api_key)


# ── Salud ─────────────────────────────────────────────────────────────


def health_check(base_url: str | None = None) -> bool:
    """True si /api/health responde 200 con postgres+clickhouse ok.

    No requiere API key (endpoint público de healthcheck).
    """
    url = f"{_base_url(base_url)}/api/health"
    data = api_get(url, service="plausible", timeout=10)
    if isinstance(data, dict):
        vals = [str(v).lower() for v in data.values()]
        return all(v in ("ok", "true") for v in vals) if vals else True
    return False
