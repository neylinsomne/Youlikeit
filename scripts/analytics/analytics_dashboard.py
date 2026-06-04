"""
analytics_dashboard — vista CLI del tráfico del sitio (4 paneles).

Lee de las tablas locales `plausible_pageviews` / `plausible_events`
(pobladas por `fetch_plausible_stats.py --persist`) y, opcionalmente, refresca
en vivo desde la Stats API con --live.

Paneles:
  1. Top pages           — páginas por visitantes
  2. Custom events       — goals (persona_click, cta_click, ...)
  3. Traffic timeline    — sparkline de visitantes por periodo
  4. Conversion funnel   — pageviews → cta_click → (proxy de conversión)

Uso:
  python scripts/analytics/analytics_dashboard.py
  python scripts/analytics/analytics_dashboard.py --live --period 30d
  python scripts/analytics/analytics_dashboard.py --json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.chdir(str(ROOT))

logging.basicConfig(level=logging.WARNING)

_SPARK = "▁▂▃▄▅▆▇█"


def sparkline(values: list[float]) -> str:
    """Mini gráfico de texto. Estable y sin dependencias."""
    nums = [float(v or 0) for v in values]
    if not nums:
        return ""
    lo, hi = min(nums), max(nums)
    span = (hi - lo) or 1.0
    return "".join(_SPARK[min(len(_SPARK) - 1, int((v - lo) / span * (len(_SPARK) - 1)))]
                   for v in nums)


# ── Paneles (toman conn, devuelven dict) ─────────────────────────────


def panel_top_pages(conn, limit: int = 10) -> list[dict]:
    rows = conn.execute(
        """SELECT page, MAX(visitors) AS visitors, MAX(pageviews) AS pageviews
             FROM plausible_pageviews
            GROUP BY page
            ORDER BY visitors DESC
            LIMIT ?""", (limit,),
    ).fetchall()
    return [{"page": r["page"], "visitors": r["visitors"], "pageviews": r["pageviews"]}
            for r in rows]


def panel_custom_events(conn, limit: int = 10) -> list[dict]:
    rows = conn.execute(
        """SELECT event_name, SUM(count) AS total
             FROM plausible_events
            GROUP BY event_name
            ORDER BY total DESC
            LIMIT ?""", (limit,),
    ).fetchall()
    return [{"event_name": r["event_name"], "total": r["total"]} for r in rows]


def panel_timeline(conn) -> list[dict]:
    rows = conn.execute(
        """SELECT period_end, SUM(visitors) AS visitors
             FROM plausible_pageviews
            GROUP BY period_end
            ORDER BY period_end ASC""",
    ).fetchall()
    return [{"period_end": r["period_end"], "visitors": r["visitors"]} for r in rows]


def panel_funnel(conn) -> dict:
    pv = conn.execute("SELECT COALESCE(SUM(pageviews),0) FROM plausible_pageviews").fetchone()[0]
    cta = conn.execute(
        "SELECT COALESCE(SUM(count),0) FROM plausible_events WHERE event_name = 'cta_click'"
    ).fetchone()[0]
    persona = conn.execute(
        "SELECT COALESCE(SUM(count),0) FROM plausible_events WHERE event_name = 'persona_click'"
    ).fetchone()[0]
    rate = round(100.0 * cta / pv, 2) if pv else 0.0
    return {"pageviews": pv, "cta_click": cta, "persona_click": persona,
            "cta_rate_pct": rate}


def build(conn) -> dict:
    return {
        "top_pages": panel_top_pages(conn),
        "custom_events": panel_custom_events(conn),
        "timeline": panel_timeline(conn),
        "funnel": panel_funnel(conn),
    }


# ── Render ───────────────────────────────────────────────────────────


def render(data: dict) -> str:
    out = []
    out.append("═" * 60)
    out.append("  YOULIKEIT · ANALYTICS DASHBOARD")
    out.append("═" * 60)

    out.append("\n  [1] Top pages")
    for r in data["top_pages"] or []:
        out.append(f"      {str(r['visitors']):>6}  {r['page']}")
    if not data["top_pages"]:
        out.append("      (sin datos — corre fetch_plausible_stats.py --persist)")

    out.append("\n  [2] Custom events")
    for r in data["custom_events"] or []:
        out.append(f"      {str(r['total']):>6}  {r['event_name']}")
    if not data["custom_events"]:
        out.append("      (sin eventos)")

    out.append("\n  [3] Traffic timeline")
    tl = data["timeline"] or []
    if tl:
        spark = sparkline([r["visitors"] for r in tl])
        out.append(f"      {spark}  ({tl[0]['period_end']} → {tl[-1]['period_end']})")
    else:
        out.append("      (sin serie)")

    out.append("\n  [4] Conversion funnel")
    f = data["funnel"]
    out.append(f"      pageviews     {f['pageviews']}")
    out.append(f"      cta_click     {f['cta_click']}  ({f['cta_rate_pct']}% de pageviews)")
    out.append(f"      persona_click {f['persona_click']}")
    out.append("═" * 60)
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--live", action="store_true",
                    help="Refresca desde la Stats API antes de renderizar (--persist implícito)")
    ap.add_argument("--period", default="30d", help="Periodo si --live (default 30d)")
    ap.add_argument("--json", action="store_true", help="Salida JSON")
    args = ap.parse_args()

    from core.db import get_db
    conn = get_db(Path("data"))

    if args.live:
        from apps.analytics import plausible_client as pc
        from apps.analytics.internal_signals import persist_pageviews, persist_events, default_period
        if pc.health_check():
            pages = pc.fetch_breakdown(property="event:page", period=args.period,
                                       metrics=["visitors", "pageviews", "bounce_rate",
                                                "visit_duration"], conn=conn)
            goals = pc.fetch_breakdown(property="event:goal", period=args.period,
                                       metrics=["visitors", "events"], conn=conn)
            ps, pe = default_period(30)
            persist_pageviews(conn, (pages or {}).get("results", []), ps, pe)
            persist_events(conn, (goals or {}).get("results", []), ps, pe)

    data = build(conn)
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(render(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
