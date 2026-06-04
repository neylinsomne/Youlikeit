"""
Unified Analytics — vista conjunta del embudo de contenido.

Une en un solo reporte las 4 capas de medición del proyecto:

    1. DEMANDA externa     ← market_signals / persona_briefs   (qué se habla afuera)
    2. DEMANDA 1ª parte    ← plausible_pageviews / events       (qué mira mi gente) ★NUEVO
    3. CALIDAD             ← hook_scores                        (¿pasa el gate?)
    4. DISTRIBUCIÓN        ← analytics (YT/TT)                  (¿cómo le fue?)

El valor está en la capa 2 (web de 1ª parte vía Plausible): antes el embudo
empezaba en "calidad/distribución" y la demanda solo venía de fuentes externas.
Plausible añade telemetría propia del top-of-funnel. Ver docs/architecture/
ANALYTICS_COVERAGE.md.

Diseño:
  - Funciones puras `*(conn) -> dict/list`, testeables con DB sintética.
  - SOLO LECTURA sobre tablas de otros dominios (analytics, hook_scores,
    market_signals, persona_briefs). No escribe nada.
  - Tolerante a tablas vacías o ausentes (DB parcial) — degrada a ceros.

API:
    from apps.analytics.unified_analytics import build, render

    report = build(conn, source="joint")      # nuestra + Plausible
    report = build(conn, source="plausible")  # solo embudo web
    print(render(report))
"""

from __future__ import annotations

import json
import logging
import sqlite3

from apps.analytics.internal_signals import PERSONA_PAGES

log = logging.getLogger(__name__)

PERSONAS = ("deep_mind", "pop_oracle", "latam")


# ── Helper: query defensiva ───────────────────────────────────────────


def _q1(conn: sqlite3.Connection, sql: str, params: tuple = (), default=0):
    """SELECT de un solo valor, tolerante a tabla ausente."""
    try:
        row = conn.execute(sql, params).fetchone()
    except sqlite3.OperationalError:
        return default
    if not row:
        return default
    val = row[0]
    return val if val is not None else default


def _qall(conn: sqlite3.Connection, sql: str, params: tuple = ()):
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []


# ── Capa 2: demanda de 1ª parte (Plausible) ──────────────────────────


def web_funnel(conn: sqlite3.Connection) -> dict:
    """Embudo web propio: visitantes → pageviews → CTAs → persona_click."""
    visitors = _q1(conn, "SELECT COALESCE(SUM(visitors),0) FROM plausible_pageviews")
    pageviews = _q1(conn, "SELECT COALESCE(SUM(pageviews),0) FROM plausible_pageviews")
    cta = _q1(conn, "SELECT COALESCE(SUM(count),0) FROM plausible_events WHERE event_name='cta_click'")
    persona_clicks = _q1(conn, "SELECT COALESCE(SUM(count),0) FROM plausible_events WHERE event_name='persona_click'")
    top_pages = [
        {"page": r["page"], "visitors": r["visitors"]}
        for r in _qall(conn,
            """SELECT page, MAX(visitors) AS visitors
                 FROM plausible_pageviews GROUP BY page
                ORDER BY visitors DESC LIMIT 5""")
    ]
    return {
        "visitors": visitors,
        "pageviews": pageviews,
        "cta_click": cta,
        "persona_click": persona_clicks,
        "cta_rate_pct": round(100.0 * cta / pageviews, 2) if pageviews else 0.0,
        "top_pages": top_pages,
    }


# ── Capa 1: demanda externa (signals) ─────────────────────────────────


def external_demand(conn: sqlite3.Connection) -> dict:
    """Señales de mercado + backlog de briefs por persona."""
    signals_24h = _q1(conn,
        "SELECT COUNT(*) FROM market_signals WHERE fetched_at >= datetime('now','-1 day')")
    signals_7d = _q1(conn,
        "SELECT COUNT(*) FROM market_signals WHERE fetched_at >= datetime('now','-7 day')")
    by_domain = {
        r["domain"]: r["n"] for r in _qall(conn,
            """SELECT domain, COUNT(*) AS n FROM market_signals
                WHERE fetched_at >= datetime('now','-7 day')
                GROUP BY domain ORDER BY n DESC""")
    }
    briefs_unconsumed = {
        r["persona"]: r["n"] for r in _qall(conn,
            """SELECT persona, COUNT(*) AS n FROM persona_briefs
                WHERE consumed_at IS NULL GROUP BY persona""")
    }
    return {
        "signals_24h": signals_24h,
        "signals_7d": signals_7d,
        "signals_by_domain": by_domain,
        "briefs_unconsumed": briefs_unconsumed,
    }


# ── Capa 3: calidad (hook_scores) ─────────────────────────────────────


def content_quality(conn: sqlite3.Connection) -> dict:
    """Pass-rate y score medio de hooks, global y por persona."""
    total = _q1(conn, "SELECT COUNT(*) FROM hook_scores")
    passed = _q1(conn, "SELECT COALESCE(SUM(passed),0) FROM hook_scores")
    avg = _q1(conn, "SELECT COALESCE(AVG(overall_score),0) FROM hook_scores", default=0.0)
    by_persona = {
        r["persona"]: {
            "n": r["n"],
            "pass_rate_pct": round(100.0 * (r["passed"] or 0) / r["n"], 1) if r["n"] else 0.0,
            "avg_score": round(r["avg"] or 0.0, 3),
        }
        for r in _qall(conn,
            """SELECT persona, COUNT(*) AS n, SUM(passed) AS passed, AVG(overall_score) AS avg
                 FROM hook_scores WHERE persona IS NOT NULL
                GROUP BY persona""")
    }
    return {
        "scored": total,
        "pass_rate_pct": round(100.0 * passed / total, 1) if total else 0.0,
        "avg_score": round(avg, 3),
        "by_persona": by_persona,
    }


# ── Capa 4: distribución (analytics YT/TT) ────────────────────────────


def platform_performance(conn: sqlite3.Connection) -> dict:
    """Resultado en plataforma por canal + top shorts."""
    by_platform = {
        r["platform"]: {
            "videos": r["n"],
            "views": r["views"],
            "avg_engagement_rate": round(r["eng"] or 0.0, 4),
            "avg_retention_avg": round(r["ret"] or 0.0, 2),
        }
        for r in _qall(conn,
            """SELECT platform, COUNT(*) AS n, COALESCE(SUM(views),0) AS views,
                      AVG(engagement_rate) AS eng, AVG(retention_avg) AS ret
                 FROM analytics GROUP BY platform""")
    }
    top = [
        {"short_id": r["short_id"], "platform": r["platform"],
         "views": r["views"], "engagement_rate": round(r["engagement_rate"] or 0.0, 4)}
        for r in _qall(conn,
            """SELECT short_id, platform, views, engagement_rate
                 FROM analytics ORDER BY views DESC LIMIT 5""")
    ]
    return {"by_platform": by_platform, "top_shorts": top}


# ── Rollup por persona (cruce de capas) ───────────────────────────────


def persona_rollup(conn: sqlite3.Connection) -> list[dict]:
    """Por persona: interés web (1ª parte) + backlog briefs + calidad hook.

    Cruza las señales accionables para decidir DÓNDE producir a continuación:
    persona con demanda propia + briefs listos + hooks que pasan.
    """
    quality = content_quality(conn)["by_persona"]
    briefs = external_demand(conn)["briefs_unconsumed"]

    rows = []
    for persona in PERSONAS:
        pages = PERSONA_PAGES.get(persona, [])
        web_visitors = 0
        if pages:
            ph = ",".join("?" for _ in pages)
            web_visitors = _q1(conn,
                f"""SELECT COALESCE(SUM(visitors),0) FROM (
                        SELECT page, MAX(visitors) AS visitors
                          FROM plausible_pageviews WHERE page IN ({ph})
                         GROUP BY page)""", tuple(pages))
        persona_clicks = _q1(conn,
            """SELECT COALESCE(SUM(count),0) FROM plausible_events
                WHERE event_name='persona_click'
                  AND COALESCE(json_extract(raw_props,'$.persona'), page) = ?""",
            (persona,))
        q = quality.get(persona, {})
        rows.append({
            "persona": persona,
            "web_visitors": web_visitors,
            "persona_clicks": persona_clicks,
            "briefs_unconsumed": briefs.get(persona, 0),
            "hook_pass_rate_pct": q.get("pass_rate_pct", 0.0),
            "hook_avg_score": q.get("avg_score", 0.0),
        })
    return rows


# ── Ensamblado ────────────────────────────────────────────────────────


def build(conn: sqlite3.Connection, source: str = "joint") -> dict:
    """Construye el reporte.

    source='plausible' → solo embudo web de 1ª parte.
    source='joint'     → las 4 capas + rollup por persona (default).
    """
    web = web_funnel(conn)
    if source == "plausible":
        return {"source": "plausible", "web_funnel": web}

    return {
        "source": "joint",
        "external_demand": external_demand(conn),
        "web_funnel": web,
        "content_quality": content_quality(conn),
        "platform_performance": platform_performance(conn),
        "persona_rollup": persona_rollup(conn),
    }


# ── Render ────────────────────────────────────────────────────────────


def render(report: dict) -> str:
    out = ["═" * 64,
           "  YOULIKEIT · ANALÍTICA "
           + ("CONJUNTA (nuestra + Plausible)" if report["source"] == "joint"
              else "WEB (solo Plausible)"),
           "═" * 64]

    if report["source"] == "joint":
        ed = report["external_demand"]
        out.append("\n  [1] DEMANDA EXTERNA (signals → briefs)")
        out.append(f"      señales 24h: {ed['signals_24h']}   7d: {ed['signals_7d']}")
        if ed["signals_by_domain"]:
            dom = "  ".join(f"{k}:{v}" for k, v in ed["signals_by_domain"].items())
            out.append(f"      por dominio: {dom}")
        if ed["briefs_unconsumed"]:
            br = "  ".join(f"{k}:{v}" for k, v in ed["briefs_unconsumed"].items())
            out.append(f"      briefs sin consumir: {br}")

    w = report["web_funnel"]
    out.append("\n  [2] DEMANDA 1ª PARTE — WEB (Plausible) ★")
    out.append(f"      visitantes: {w['visitors']}   pageviews: {w['pageviews']}")
    out.append(f"      cta_click: {w['cta_click']} ({w['cta_rate_pct']}%)   "
               f"persona_click: {w['persona_click']}")
    for p in w["top_pages"]:
        out.append(f"        {str(p['visitors']):>6}  {p['page']}")
    if not w["top_pages"]:
        out.append("        (sin datos — corre fetch_plausible_stats.py --persist)")

    if report["source"] == "joint":
        q = report["content_quality"]
        out.append("\n  [3] CALIDAD (hook_scores)")
        out.append(f"      scored: {q['scored']}   pass-rate: {q['pass_rate_pct']}%   "
                   f"avg: {q['avg_score']}")

        pp = report["platform_performance"]
        out.append("\n  [4] DISTRIBUCIÓN (analytics YT/TT)")
        for plat, m in pp["by_platform"].items():
            out.append(f"      {plat:8s} videos:{m['videos']} views:{m['views']} "
                       f"eng:{m['avg_engagement_rate']} ret:{m['avg_retention_avg']}")
        if not pp["by_platform"]:
            out.append("      (sin datos de plataforma)")

        out.append("\n  ── ROLLUP POR PERSONA (dónde producir) ──")
        out.append("      persona      web  clicks  briefs  hook%   hookAvg")
        for r in report["persona_rollup"]:
            out.append(f"      {r['persona']:11s} {str(r['web_visitors']):>4} "
                       f"{str(r['persona_clicks']):>6}  {str(r['briefs_unconsumed']):>5}  "
                       f"{str(r['hook_pass_rate_pct']):>5}  {r['hook_avg_score']}")

    out.append("═" * 64)
    return "\n".join(out)
