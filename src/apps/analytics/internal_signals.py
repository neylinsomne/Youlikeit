"""
Internal Signals — bridge de tráfico propio (Plausible) → `market_signals`.

Convierte el engagement del sitio público en señales de dominio `internal` que
pueden competir en el rotator junto a las señales externas (Steam, Reddit, ...).
La idea MLOps: cerrar el loop — lo que la audiencia mira en NUESTRO sitio es
una señal de demanda tan válida como un trending de Trakt.

Flujo:
    Stats API → persist_pageviews / persist_events (tablas plausible_*)
              → signals_from_plausible(conn, persona) → list[Signal]
              → [coordinación Signals Agent] → market_signals (domain='internal')

⚠️  CONTRATO DE COORDINACIÓN (NO auto-mergear):
    `domain='internal'` NO está todavía en el enum de `signals_validation.
    check_domain_enum` (set actual: gaming/anime_manga/movies_tv/music/latam).
    Persistir señales internal en la DB real haría fallar ese check HARD.
    Por eso `persist_signals_to_market()` es OPT-IN y NO se llama desde la cron.
    Para activarlo en producción hace falta la sub-tarea documentada en
    docs/agents/SIGNALS_AGENT.md § "Pendiente: domain += internal".

Privacy: estas tablas y señales NO contienen IPs, user agents ni PII —
solo agregados (visitors, pageviews, bounce_rate). Ver anti-patrones del handbook.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date, datetime, timedelta

from apps.signals.market_signals import Signal, _persist_signal

log = logging.getLogger(__name__)

INTERNAL_SOURCE = "plausible_internal"
INTERNAL_SOURCE_TYPE = "own_engagement"
INTERNAL_DOMAIN = "internal"


# ── Mapeo persona → páginas del sitio ────────────────────────────────
# Cuando existan páginas por persona (/persona/deep_mind, ...) el match es
# directo. Mientras tanto, una persona "owns" sus rutas declaradas aquí.

PERSONA_PAGES: dict[str, list[str]] = {
    "deep_mind": ["/persona/deep_mind", "/dashboard.html"],
    "pop_oracle": ["/persona/pop_oracle", "/"],
    "latam": ["/persona/latam", "/contact.html"],
}


def _page_persona(page: str) -> str | None:
    """Persona dueña de una página, o None si no está mapeada."""
    for persona, pages in PERSONA_PAGES.items():
        if page in pages:
            return persona
    return None


# ── Persistencia de Stats API → tablas plausible_* ───────────────────


def persist_pageviews(
    conn: sqlite3.Connection,
    results: list[dict],
    period_start: str,
    period_end: str,
) -> int:
    """Persiste un breakdown de `event:page` en `plausible_pageviews`.

    `results` es la lista `breakdown(...)["results"]`. Cada item trae al menos
    `page` y `visitors`; opcionalmente pageviews/bounce_rate/visit_duration.
    Idempotente por UNIQUE(page, period_start, period_end). Retorna filas escritas.
    """
    n = 0
    for r in results or []:
        page = r.get("page") or r.get("event:page")
        if not page:
            continue
        try:
            conn.execute(
                """INSERT OR REPLACE INTO plausible_pageviews
                     (page, visitors, pageviews, bounce_rate, visit_duration,
                      period_start, period_end, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'plausible')""",
                (
                    page,
                    int(r.get("visitors", 0) or 0),
                    int(r.get("pageviews", 0) or 0),
                    _to_float(r.get("bounce_rate")),
                    _to_float(r.get("visit_duration")),
                    period_start,
                    period_end,
                ),
            )
            n += 1
        except sqlite3.Error as e:
            log.warning("persist_pageviews skip %s: %s", page, e)
    conn.commit()
    return n


def persist_events(
    conn: sqlite3.Connection,
    results: list[dict],
    period_start: str,
    period_end: str,
    page: str | None = None,
) -> int:
    """Persiste un breakdown de `event:goal` en `plausible_events`.

    Cada item trae `goal` (nombre del evento) y `events`/`visitors`. Props
    extra se serializan en raw_props (sin PII). Retorna filas escritas.
    """
    n = 0
    for r in results or []:
        name = r.get("goal") or r.get("event:goal") or r.get("event_name")
        if not name:
            continue
        count = int(r.get("events", r.get("visitors", 0)) or 0)
        props = {k: v for k, v in r.items()
                 if k not in ("goal", "event:goal", "event_name", "events", "visitors")}
        try:
            conn.execute(
                """INSERT OR REPLACE INTO plausible_events
                     (event_name, page, count, period_start, period_end, raw_props)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (name, page, count, period_start, period_end,
                 json.dumps(props, ensure_ascii=False) if props else None),
            )
            n += 1
        except sqlite3.Error as e:
            log.warning("persist_events skip %s: %s", name, e)
    conn.commit()
    return n


# ── Bridge: plausible_pageviews → Signal(domain='internal') ──────────


def signals_from_plausible(
    conn: sqlite3.Connection,
    persona: str,
    *,
    min_visitors: int = 1,
) -> list[Signal]:
    """Genera señales `internal` para una persona a partir de su tráfico.

    Lee de `plausible_pageviews` las páginas que pertenecen a `persona`
    (ver PERSONA_PAGES), toma el periodo más reciente por página y construye
    un `Signal` con:
        source='plausible_internal', source_type='own_engagement',
        domain='internal', raw_score=visitors, raw_meta={page, bounce_rate,
        visit_duration, delta_pct}.

    `delta_pct` compara el periodo más reciente contra el inmediatamente
    anterior de la misma página (si existe), para detectar spikes.

    NO persiste — devuelve la lista. Persistir es responsabilidad del caller
    (y requiere coordinación con Signals Agent; ver módulo docstring).

    Ejemplo:
        >>> sigs = signals_from_plausible(conn, "deep_mind")
        >>> sigs[0].domain
        'internal'
    """
    pages = PERSONA_PAGES.get(persona, [])
    if not pages:
        return []

    signals: list[Signal] = []
    placeholders = ",".join("?" for _ in pages)
    rows = conn.execute(
        f"""SELECT page, visitors, pageviews, bounce_rate, visit_duration,
                   period_start, period_end
              FROM plausible_pageviews
             WHERE page IN ({placeholders})
             ORDER BY page, period_end DESC""",
        tuple(pages),
    ).fetchall()

    # Agrupar por página, conservando orden (más reciente primero).
    by_page: dict[str, list] = {}
    for r in rows:
        by_page.setdefault(r["page"], []).append(r)

    for page, snaps in by_page.items():
        latest = snaps[0]
        visitors = int(latest["visitors"] or 0)
        if visitors < min_visitors:
            continue
        delta_pct = _delta_pct(
            latest["visitors"],
            snaps[1]["visitors"] if len(snaps) > 1 else None,
        )
        spike = f" spike +{delta_pct:.0f}%" if delta_pct and delta_pct > 0 else ""
        signals.append(Signal(
            source=INTERNAL_SOURCE,
            source_type=INTERNAL_SOURCE_TYPE,
            domain=INTERNAL_DOMAIN,
            title=f"Persona {persona} traffic on {page}{spike}",
            url=page,
            summary=f"{visitors} visitors · bounce {latest['bounce_rate']} · "
                    f"avg {latest['visit_duration']}s",
            raw_score=float(visitors),
            raw_meta={
                "persona": persona,
                "page": page,
                "bounce_rate": latest["bounce_rate"],
                "visit_duration": latest["visit_duration"],
                "delta_pct": delta_pct,
                "period_end": latest["period_end"],
            },
        ))
    return signals


def persist_signals_to_market(conn: sqlite3.Connection, signals: list[Signal]) -> int:
    """OPT-IN: persiste señales internal en `market_signals`.

    ⚠️  Requiere que `signals_validation.check_domain_enum` ya acepte
    'internal' (sub-tarea Signals Agent). NO llamar desde la cron hasta
    entonces — rompería el check HARD. Retorna número de inserts nuevos.
    """
    n = 0
    for sig in signals:
        if _persist_signal(conn, sig):
            n += 1
    conn.commit()
    return n


# ── Helpers ───────────────────────────────────────────────────────────


def _to_float(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _delta_pct(current, previous) -> float | None:
    """Variación porcentual current vs previous. None si no hay base."""
    cur = _to_float(current)
    prev = _to_float(previous)
    if cur is None or prev is None or prev == 0:
        return None
    return round(100.0 * (cur - prev) / prev, 1)


def default_period(days: int = 7) -> tuple[str, str]:
    """(period_start, period_end) ISO para los últimos `days` días.

    Determinista respecto al reloj del caller; en tests usar freezegun.
    """
    end = date.today()
    start = end - timedelta(days=days)
    return start.isoformat(), end.isoformat()
