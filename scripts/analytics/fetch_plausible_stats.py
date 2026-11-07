"""
fetch_plausible_stats — CLI para leer la Stats API de Plausible y (opcional)
persistir a las tablas `plausible_pageviews` / `plausible_events`.

Hace, en orden:
  1. Healthcheck del Plausible self-hosted.
  2. aggregate  → métricas globales del periodo.
  3. breakdown event:page → top páginas (persiste si --persist).
  4. breakdown event:goal → custom events (persiste si --persist).

Uso típico:
  python scripts/analytics/fetch_plausible_stats.py --period 7d
  python scripts/analytics/fetch_plausible_stats.py --period 30d --json
  python scripts/analytics/fetch_plausible_stats.py --period 7d --persist
  python scripts/analytics/fetch_plausible_stats.py --report-only      # solo lee DB local

Env requeridas (salvo --report-only):
  PLAUSIBLE_BASE_URL  (default https://analytics.vara-alta.lat)
  PLAUSIBLE_API_KEY   (del panel: Site Settings → API Keys)
  PLAUSIBLE_SITE_ID   (default youlikeit.vara-alta.lat)

Exit codes:
  0  OK
  2  falta config (PLAUSIBLE_API_KEY) o healthcheck rojo
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent.parent
os.chdir(str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("fetch_plausible_stats")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--period", default="7d",
                    help="Periodo Plausible: day|7d|30d|month|6mo|12mo (default 7d)")
    ap.add_argument("--metrics", nargs="*",
                    default=["visitors", "pageviews", "bounce_rate", "visit_duration"],
                    help="Métricas para aggregate")
    ap.add_argument("--persist", action="store_true",
                    help="Escribe pageviews + events a las tablas plausible_*")
    ap.add_argument("--json", action="store_true",
                    help="Salida JSON (para CI/dashboards)")
    ap.add_argument("--report-only", action="store_true",
                    help="No llama a la API; solo resume lo que ya hay en la DB local")
    ap.add_argument("--no-cache", action="store_true",
                    help="Ignora la cache de 1h y fuerza fetch")
    args = ap.parse_args()

    from core.db import get_db
    conn = get_db(Path("data"))

    report: dict = {"started_at": datetime.now().isoformat(), "period": args.period}

    if args.report_only:
        report["local"] = _local_summary(conn)
        _emit(report, args.json)
        return 0

    from apps.analytics import plausible_client as pc
    from apps.analytics.internal_signals import persist_pageviews, persist_events, default_period

    # 1. Health
    if not pc.health_check():
        log.error("Plausible healthcheck rojo en %s", pc._base_url())
        report["health"] = False
        _emit(report, args.json)
        return 2
    report["health"] = True

    cache_conn = None if args.no_cache else conn

    try:
        # 2. aggregate
        agg = pc.fetch_aggregate(period=args.period, metrics=args.metrics, conn=cache_conn)
        report["aggregate"] = (agg or {}).get("results", {})

        # 3. breakdown páginas
        pages = pc.fetch_breakdown(property="event:page", period=args.period,
                                   metrics=["visitors", "pageviews", "bounce_rate",
                                            "visit_duration"], conn=cache_conn)
        page_rows = (pages or {}).get("results", [])
        report["top_pages"] = page_rows[:10]

        # 4. breakdown custom events
        goals = pc.fetch_breakdown(property="event:goal", period=args.period,
                                   metrics=["visitors", "events"], conn=cache_conn)
        goal_rows = (goals or {}).get("results", [])
        report["custom_events"] = goal_rows
    except pc.PlausibleConfigError as e:
        log.error("Config error: %s", e)
        report["error"] = str(e)
        _emit(report, args.json)
        return 2

    if args.persist:
        ps, pe = default_period(_period_days(args.period))
        n_pv = persist_pageviews(conn, page_rows, ps, pe)
        n_ev = persist_events(conn, goal_rows, ps, pe)
        report["persisted"] = {"pageviews": n_pv, "events": n_ev,
                               "period_start": ps, "period_end": pe}
        log.info("Persistidas %d pageviews + %d events", n_pv, n_ev)

    report["finished_at"] = datetime.now().isoformat()
    _emit(report, args.json)
    return 0


def _period_days(period: str) -> int:
    return {"day": 1, "7d": 7, "30d": 30, "month": 30,
            "6mo": 180, "12mo": 365}.get(period, 7)


def _local_summary(conn) -> dict:
    def _count(tbl):
        try:
            return conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        except Exception:
            return 0
    return {
        "plausible_pageviews": _count("plausible_pageviews"),
        "plausible_events": _count("plausible_events"),
        "plausible_cache": _count("plausible_cache"),
    }


def _emit(report: dict, as_json: bool):
    if as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return
    print()
    print("══════════════════════════════════════════════════════")
    print(f"  PLAUSIBLE STATS · {report.get('period')}")
    print("══════════════════════════════════════════════════════")
    if "aggregate" in report:
        for metric, obj in report["aggregate"].items():
            val = obj.get("value") if isinstance(obj, dict) else obj
            print(f"  {metric:18s} {val}")
    if report.get("top_pages"):
        print("\n  Top páginas:")
        for r in report["top_pages"]:
            print(f"    {str(r.get('visitors','')):>6}  {r.get('page','')}")
    if report.get("custom_events"):
        print("\n  Custom events:")
        for r in report["custom_events"]:
            print(f"    {str(r.get('events', r.get('visitors',''))):>6}  {r.get('goal','')}")
    if "persisted" in report:
        p = report["persisted"]
        print(f"\n  Persistido: {p['pageviews']} pageviews · {p['events']} events")
    if "local" in report:
        print("  DB local:")
        for k, v in report["local"].items():
            print(f"    {k:24s} {v}")
    print("══════════════════════════════════════════════════════")


if __name__ == "__main__":
    sys.exit(main())
