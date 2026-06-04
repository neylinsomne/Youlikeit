"""
briefs_dashboard — inspector CLI del estado del flujo de información.

Da una vista de 3 paneles sin levantar nada (sin Streamlit todavía):
  1. Salud de scrapers — éxito/fallo y latencia por fuente.
  2. Briefs por persona — top N + cuáles ya consumidos.
  3. Queue de unresolved — briefs sin match en CATALOG.
  4. (opcional) Resultado de validación de invariantes.

Uso:
  python scripts/briefs_dashboard.py                       # vista completa
  python scripts/briefs_dashboard.py --persona deep_mind   # solo una persona
  python scripts/briefs_dashboard.py --validate            # corre validación
  python scripts/briefs_dashboard.py --json out.json       # dump estructurado
  python scripts/briefs_dashboard.py --resolve-preview     # muestra qué slug
                                                            # resolvería cada brief
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
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
    level=logging.WARNING,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


def _scraper_health(conn: sqlite3.Connection) -> list[dict]:
    try:
        cur = conn.execute("""
            SELECT scraper_name,
                   SUM(success_count) as ok,
                   SUM(failure_count) as ko,
                   AVG(avg_latency_ms) as latency,
                   MAX(last_success_at) as last_ok,
                   MAX(last_failure_at) as last_fail
            FROM scraper_health
            WHERE checked_at >= datetime('now', '-7 day')
            GROUP BY scraper_name
            ORDER BY ko DESC, scraper_name
        """)
        return [dict(r) for r in cur.fetchall()]
    except sqlite3.OperationalError:
        return []


def _briefs_panel(conn: sqlite3.Connection, persona: str | None,
                   limit: int) -> dict:
    try:
        from apps.signals.signals_distiller import PERSONA_ALIGNMENT
    except ImportError:
        return {}
    panels: dict = {}
    personas = [persona] if persona else list(PERSONA_ALIGNMENT.keys())
    for p in personas:
        # Vivos
        live = conn.execute("""
            SELECT id, headline, domain, score, frequency,
                   suggested_angle, created_at
            FROM persona_briefs
            WHERE persona = ? AND consumed_at IS NULL
            ORDER BY score DESC LIMIT ?
        """, (p, limit)).fetchall()
        # Consumidos recientemente (últimos 14d)
        consumed = conn.execute("""
            SELECT id, headline, score, consumed_at
            FROM persona_briefs
            WHERE persona = ? AND consumed_at IS NOT NULL
              AND consumed_at >= datetime('now', '-14 day')
            ORDER BY consumed_at DESC LIMIT 5
        """, (p,)).fetchall()
        panels[p] = {
            "unconsumed": [dict(r) for r in live],
            "recently_consumed": [dict(r) for r in consumed],
        }
    return panels


def _unresolved_panel(conn: sqlite3.Connection, limit: int) -> list[dict]:
    try:
        from apps.signals.brief_resolver import list_unresolved, ensure_unresolved_schema
        ensure_unresolved_schema(conn)
        return list_unresolved(conn, only_unreviewed=True, limit=limit)
    except Exception:
        return []


def _resolve_preview(conn: sqlite3.Connection, persona: str | None,
                      limit: int) -> list[dict]:
    """Para cada brief unconsumed muestra QUÉ slug resolvería ahora.

    Útil para debug del resolver / decidir aliases nuevos.
    """
    try:
        from apps.signals.signals_distiller import fetch_briefs_for_persona, PERSONA_ALIGNMENT
        from apps.signals.brief_resolver import resolve_brief
        from apps.production.content_rotator import CATALOG
    except ImportError:
        return []
    out = []
    personas = [persona] if persona else list(PERSONA_ALIGNMENT.keys())
    for p in personas:
        briefs = fetch_briefs_for_persona(conn, p, limit=limit, only_unconsumed=True)
        for b in briefs:
            slug, layer = resolve_brief(b, CATALOG, conn)
            out.append({
                "persona": p,
                "headline": b["headline"],
                "score": b["score"],
                "resolved_slug": slug,
                "match_layer": layer,
            })
    return out


def _validate_panel(conn: sqlite3.Connection) -> dict:
    try:
        from apps.signals.signals_validation import run_all_checks
        return run_all_checks(conn).to_dict()
    except Exception as e:
        return {"error": str(e)}


# ── Render ─────────────────────────────────────────────────────────


def _print_scraper_health(rows: list[dict]):
    print(_h("SCRAPER HEALTH (7d)"))
    if not rows:
        print("  (sin datos — la tabla está vacía o el scheduler no ha corrido)")
        return
    print(f"  {'source':30s} {'ok':>5s} {'ko':>5s} {'rate':>6s} {'lat(ms)':>8s}  last_ok")
    print(f"  {'-'*30} {'-'*5} {'-'*5} {'-'*6} {'-'*8}  {'-'*19}")
    for r in rows:
        ok = r.get("ok") or 0
        ko = r.get("ko") or 0
        tot = ok + ko
        rate = (ko / tot * 100) if tot else 0
        lat = r.get("latency") or 0
        mark = "!" if rate > 30 else " "
        last_ok = (r.get("last_ok") or "—")[:19]
        print(f"  {mark}{r['scraper_name'][:29]:29s} {ok:>5} {ko:>5} {rate:>5.0f}% {lat:>8.0f}  {last_ok}")


def _print_briefs(panels: dict):
    print(_h("BRIEFS POR PERSONA"))
    if not panels:
        print("  (sin datos)")
        return
    for persona, data in panels.items():
        live = data.get("unconsumed", [])
        consumed = data.get("recently_consumed", [])
        print(f"\n  [{persona}] {len(live)} vivos · {len(consumed)} consumidos en 14d")
        print(f"  {'#':>2s} {'score':>6s} {'dom':>13s} {'headline':50s} angle")
        print(f"  {'-'*2} {'-'*6} {'-'*13} {'-'*50} {'-'*30}")
        for i, b in enumerate(live[:10], 1):
            angle = (b.get("suggested_angle") or "")[:30]
            domain = (b.get("domain") or "")[:13]
            headline = b["headline"][:50]
            print(f"  {i:>2} {b['score']:>6.2f} {domain:>13s} {headline:50s} {angle}")


def _print_unresolved(rows: list[dict]):
    print(_h("UNRESOLVED BRIEFS (esperando curación humana)"))
    if not rows:
        print("  (vacío — todos los briefs resuelven al CATALOG)")
        return
    print(f"  {'#':>2s} {'score':>6s} {'persona':>10s} {'dom':>12s}  headline")
    print(f"  {'-'*2} {'-'*6} {'-'*10} {'-'*12}  {'-'*50}")
    for i, r in enumerate(rows[:15], 1):
        print(f"  {i:>2} {r['score']:>6.2f} {r['persona']:>10s} {(r['domain'] or '')[:12]:>12s}  {r['headline'][:60]}")
    print("\n  → para añadir al CATALOG: editar content_rotator.CATALOG y brief_resolver.ALIAS_MAP")


def _print_resolve_preview(rows: list[dict]):
    print(_h("RESOLVE PREVIEW (qué slug elegiría el rotator ahora)"))
    if not rows:
        return
    print(f"  {'persona':>10s} {'score':>6s} {'layer':>14s}  {'slug':>22s}  headline")
    print(f"  {'-'*10} {'-'*6} {'-'*14}  {'-'*22}  {'-'*40}")
    for r in rows:
        slug = r["resolved_slug"] or "—"
        layer = r["match_layer"]
        mark = "✓" if r["resolved_slug"] else "✗"
        print(f"  {mark}{r['persona']:>9s} {r['score']:>6.2f} {layer:>14s}  {slug[:22]:>22s}  {r['headline'][:50]}")


def _print_validation(rep: dict):
    print(_h("VALIDATION REPORT"))
    if "error" in rep:
        print(f"  ERROR: {rep['error']}")
        return
    hard_ok = rep.get("passes_hard")
    print(f"  HARD: {'PASS' if hard_ok else 'FAIL'}")
    for c in rep.get("checks", []):
        mark = "✓" if c["passed"] else ("✗" if c["severity"] == "hard" else "!")
        print(f"   {mark} [{c['severity']:4s}] {c['name']}: actual={c['actual']} (expected {c['expected']})")
        if c.get("notes"):
            print(f"        ↳ {c['notes']}")


def _h(title: str) -> str:
    bar = "═" * 70
    return f"\n{bar}\n  {title}\n{bar}"


# ── Main ───────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--persona", default=None, help="Filtra a una sola persona")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--validate", action="store_true", help="Incluye validación")
    ap.add_argument("--resolve-preview", action="store_true",
                    help="Muestra mapeo brief → slug que produciría el resolver")
    ap.add_argument("--json", default=None, help="Volcado estructurado a archivo")
    ap.add_argument("--no-scraper", action="store_true")
    ap.add_argument("--no-briefs", action="store_true")
    ap.add_argument("--no-unresolved", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect("data/shorts_pipeline.db")
    conn.row_factory = sqlite3.Row

    payload: dict = {"generated_at": datetime.now().isoformat()}

    if not args.no_scraper:
        rows = _scraper_health(conn)
        payload["scraper_health"] = rows
        _print_scraper_health(rows)

    if not args.no_briefs:
        panels = _briefs_panel(conn, args.persona, args.limit)
        payload["briefs"] = panels
        _print_briefs(panels)

    if not args.no_unresolved:
        rows = _unresolved_panel(conn, args.limit)
        payload["unresolved"] = rows
        _print_unresolved(rows)

    if args.resolve_preview:
        rows = _resolve_preview(conn, args.persona, args.limit)
        payload["resolve_preview"] = rows
        _print_resolve_preview(rows)

    if args.validate:
        rep = _validate_panel(conn)
        payload["validation"] = rep
        _print_validation(rep)

    if args.json:
        Path(args.json).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8",
        )

    print()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
