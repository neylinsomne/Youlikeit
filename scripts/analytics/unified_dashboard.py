"""
unified_dashboard — vista CONJUNTA del embudo (nuestra analítica + Plausible).

Une las 4 capas (demanda externa, demanda web 1ª parte, calidad, distribución)
en un solo reporte. Permite ver:
  - la vista CONJUNTA (default): las 4 capas + rollup por persona,
  - la vista SOLO PLAUSIBLE: únicamente el embudo web de 1ª parte.

Lee de la DB local (solo lectura sobre tablas de otros dominios). Con --live
refresca antes las tablas plausible_* desde la Stats API.

Uso:
  python scripts/analytics/unified_dashboard.py                  # conjunta
  python scripts/analytics/unified_dashboard.py --source plausible
  python scripts/analytics/unified_dashboard.py --json
  python scripts/analytics/unified_dashboard.py --live --period 30d
  python scripts/analytics/unified_dashboard.py --demo           # datos sintéticos

Ver: docs/architecture/ANALYTICS_COVERAGE.md
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
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


def _seed_demo(conn: sqlite3.Connection) -> None:
    """Inserta datos sintéticos en TODAS las capas para demostrar la vista."""
    from apps.signals.market_signals import Signal, _persist_many
    _persist_many(conn, [
        Signal("steam_charts", "gaming_chart", "gaming", "Elden Ring demo", raw_score=42),
        Signal("reddit_r_anime", "reddit_thread", "anime_manga", "Frieren demo", raw_score=4500),
        Signal("variety", "editorial_rss", "movies_tv", "Hannibal demo", raw_score=10),
    ])
    conn.executemany(
        """INSERT INTO persona_briefs (persona, cluster_key, headline, domain, score)
           VALUES (?, ?, ?, ?, ?)""",
        [("deep_mind", "frieren", "Frieren analysis", "anime_manga", 9.1),
         ("deep_mind", "hannibal", "Hannibal essay", "movies_tv", 8.4),
         ("pop_oracle", "elden", "Elden Ring hype", "gaming", 7.8)],
    )
    conn.executemany(
        """INSERT INTO plausible_pageviews
             (page, visitors, pageviews, bounce_rate, visit_duration, period_start, period_end)
           VALUES (?, ?, ?, 40.0, 80.0, '2026-05-25', '2026-06-01')""",
        [("/", 120, 210), ("/dashboard.html", 64, 110), ("/contact.html", 22, 30)],
    )
    conn.executemany(
        """INSERT INTO plausible_events (event_name, page, count, period_start, period_end, raw_props)
           VALUES (?, ?, ?, '2026-05-25', '2026-06-01', ?)""",
        [("cta_click", "/", 38, None),
         ("persona_click", "/persona/deep_mind", 14, '{"persona":"deep_mind"}')],
    )
    conn.executemany(
        """INSERT INTO hook_scores (video_path, persona, overall_score, passed)
           VALUES (?, ?, ?, ?)""",
        [("/v/1.mp4", "deep_mind", 0.72, 1), ("/v/2.mp4", "deep_mind", 0.48, 0),
         ("/v/3.mp4", "pop_oracle", 0.66, 1)],
    )
    conn.executemany(
        """INSERT INTO shorts (id, title) VALUES (?, ?)""",
        [(901, "demo short A"), (902, "demo short B")],
    )
    conn.executemany(
        """INSERT INTO analytics (short_id, platform, views, engagement_rate, retention_avg)
           VALUES (?, ?, ?, ?, ?)""",
        [(901, "youtube", 5400, 0.061, 38.0), (902, "tiktok", 12800, 0.094, 44.0)],
    )
    conn.commit()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--source", choices=["joint", "plausible"], default="joint",
                    help="joint = nuestra + Plausible (default); plausible = solo web")
    ap.add_argument("--live", action="store_true",
                    help="Refresca tablas plausible_* desde la Stats API antes de render")
    ap.add_argument("--period", default="30d", help="Periodo si --live")
    ap.add_argument("--json", action="store_true", help="Salida JSON")
    ap.add_argument("--demo", action="store_true",
                    help="Usa una DB in-memory con datos sintéticos (no toca data/)")
    args = ap.parse_args()

    from apps.analytics.unified_analytics import build, render

    if args.demo:
        from core.db import SCHEMA, _migrate_columns
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        _migrate_columns(conn)
        _seed_demo(conn)
    else:
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

    report = build(conn, source=args.source)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(render(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
