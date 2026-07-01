"""
verify_full_flow — Smoke E2E CONJUNTO de TODO el pipeline con datos mockeados.

Conecta los 5 dominios de punta a punta, sin red, sin GPU, sin ficheros de
video, sin LLM. Cada fase deja un check ✓/✗ tipo checklist:

    1. SIGNALS      mock Signals  → market_signals
    2. DISTILL      market_signals → persona_briefs           (sin LLM)
    3. RESOLVE      briefs → CATALOG slug (+ sweep unresolved)
    4. ROTATOR      pick_next por persona → content_produced
    5. SCORING      hook mock → hook_scores (gate)
    6. ANALYTICS    pageviews/events mock → plausible_*
    7. UNIFIED      vista conjunta de las 4 capas (build/render)

Corre contra una DB in-memory (no toca data/). Reproduce el mismo esquema que
`core.db.get_db` (SCHEMA + migraciones + init_* de dominio).

Uso:
  python scripts/testing/verify_full_flow.py
  python scripts/testing/verify_full_flow.py --json out.json
  python scripts/testing/verify_full_flow.py --show-report   # imprime la vista conjunta

Exit 0 si todas las fases verdes; 1 si alguna hard-falla.
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


# ── Guard de red: este flujo es 100% mock. Sin esto, el rotator llama a
#    trending_anime.get_trending_titles() → requests.get real (timeout 15s
#    × 43 slugs) y parece colgado. Lo bloqueamos como hace tests/conftest. ─
def _disable_network() -> None:
    import requests

    def _blocked(*a, **k):
        raise RuntimeError("HTTP real bloqueado (verify_full_flow es mock/offline)")

    for obj, attr in ((requests, "get"), (requests, "post"),
                      (requests.Session, "get"), (requests.Session, "post"),
                      (requests.Session, "request")):
        try:
            setattr(obj, attr, _blocked)
        except Exception:
            pass
    # Silencia el WARNING spam de módulos que reintentan red (trending_anime).
    logging.disable(logging.WARNING)


# ── Checklist ────────────────────────────────────────────────────────


class Stage:
    def __init__(self, name: str):
        self.name = name
        self.passed = False
        self.detail = ""
        self.error: str | None = None

    def mark(self, ok: bool, detail: str = "", error: str | None = None):
        self.passed = ok
        self.detail = detail
        self.error = error

    def to_dict(self) -> dict:
        return {"name": self.name, "passed": self.passed,
                "detail": self.detail, "error": self.error}


def _line(s: Stage) -> str:
    mark = "OK " if s.passed else "XX "
    out = f"  [{mark}] {s.name:44s} {s.detail}"
    if s.error:
        out += f"\n        -> ERROR: {s.error}"
    return out


# ── DB in-memory con el mismo esquema que get_db ─────────────────────


def _fresh_db() -> sqlite3.Connection:
    from core.db import SCHEMA, _migrate_columns, _ensure_domain_schemas
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate_columns(conn)
    _ensure_domain_schemas(conn)
    return conn


# ── Datos mock: señales que resuelven a slugs reales del CATALOG ─────


def _mock_signals():
    from apps.signals.market_signals import Signal
    return [
        # Anime — deep_mind (Berserk/Frieren/Vinland)
        Signal("mock_ann",       "editorial_rss", "anime_manga", "Berserk 1997 retrospective is peak tragedy", raw_score=9),
        Signal("mock_reddit_an", "reddit_thread", "anime_manga", "Berserk Golden Age arc analysis", raw_score=5200),
        Signal("mock_af",        "editorial_rss", "anime_manga", "Frieren wins anime of the year", raw_score=8),
        Signal("mock_reddit_fr", "reddit_thread", "anime_manga", "Frieren beats own record at MAL", raw_score=4300),
        Signal("mock_vinland",   "editorial_rss", "anime_manga", "Vinland Saga season 3 confirmed", raw_score=10),
        # Gaming — pop_oracle (Elden Ring / Helldivers)
        Signal("mock_steam",     "gaming_chart",  "gaming",      "Elden Ring", raw_score=42, raw_meta={"rank": 3}),
        Signal("mock_oc",        "gaming_review", "gaming",      "Elden Ring still GOTY 3 years later", raw_score=18),
        Signal("mock_reddit_gm", "reddit_thread", "gaming",      "Elden Ring DLC retrospective", raw_score=5800),
        # Movies/TV — deep_mind (Hannibal)
        Signal("mock_variety",   "editorial_rss", "movies_tv",   "Mads Mikkelsen on Hannibal Lecter legacy", raw_score=10),
        Signal("mock_truefilm",  "reddit_thread", "movies_tv",   "Hannibal silent dinner scene as visual poetry", raw_score=2100),
        # LatAm — latam (Betty la fea)
        Signal("mock_latam1",    "editorial_rss", "latam",       "Yo soy Betty la fea reboot announced", raw_score=10),
        Signal("mock_latam2",    "editorial_rss", "latam",       "Betty la fea 25 anniversary special", raw_score=9),
        # Sin match en CATALOG → debe ir a unresolved
        Signal("mock_unres",     "reddit_thread", "anime_manga", "Dandadan is the show of the decade", raw_score=4200),
    ]


# ── El flujo ─────────────────────────────────────────────────────────


PERSONAS = ["deep_mind", "pop_oracle", "latam"]


def run(show_report: bool = False) -> tuple[list[Stage], dict]:
    stages: list[Stage] = []
    summary: dict = {}
    conn = _fresh_db()

    # 1. SIGNALS
    s = Stage("1. SIGNALS  mock -> market_signals")
    try:
        from apps.signals.market_signals import _persist_many
        n = _persist_many(conn, _mock_signals())
        s.mark(n > 0, f"insertadas={n}")
    except Exception as e:
        s.mark(False, error=str(e)[:180])
    stages.append(s)
    if not s.passed:
        return stages, summary

    # 2. DISTILL
    s = Stage("2. DISTILL  market_signals -> persona_briefs")
    try:
        from apps.signals.signals_distiller import distill, fetch_briefs_for_persona
        n_briefs = distill(conn, settings=None, use_llm=False, window_days=30, top_per_persona=10)
        per_p = {p: len(fetch_briefs_for_persona(conn, p, limit=20)) for p in PERSONAS}
        s.mark(sum(per_p.values()) > 0, f"briefs={n_briefs} por_persona={per_p}")
    except Exception as e:
        s.mark(False, error=str(e)[:180])
    stages.append(s)

    # 3. RESOLVE
    s = Stage("3. RESOLVE  briefs -> CATALOG slug")
    try:
        from apps.signals.signals_distiller import fetch_briefs_for_persona
        from apps.signals.brief_resolver import resolve_brief, sweep_unresolved, list_unresolved
        from apps.production.content_rotator import CATALOG
        resolved = unresolved = 0
        for p in PERSONAS:
            for b in fetch_briefs_for_persona(conn, p, limit=10, only_unconsumed=True):
                slug, _layer = resolve_brief(b, CATALOG, conn)
                if slug:
                    resolved += 1
                else:
                    unresolved += 1
        sweep_unresolved(conn, CATALOG)
        q = list_unresolved(conn)
        s.mark(resolved > 0, f"resueltos={resolved} sin_resolver={unresolved} cola={len(q)}")
    except Exception as e:
        s.mark(False, error=str(e)[:180])
    stages.append(s)

    # 4. ROTATOR
    s = Stage("4. ROTATOR  pick_next -> content_produced")
    picks: dict[str, dict] = {}
    try:
        from apps.production.content_rotator import ContentRotator, init_rotation_db, log_produced
        r = ContentRotator.__new__(ContentRotator)
        r.conn = conn
        init_rotation_db(conn)
        for p in PERSONAS:
            pick = r.pick_next(p, consume_briefs=True)
            if pick:
                picks[p] = pick
                log_produced(conn, p, pick["slug"], pick["title"], "narration",
                             output_path=f"outputs/mock/{p}_{pick['slug']}.mp4")
        n_prod = conn.execute("SELECT COUNT(*) FROM content_produced").fetchone()[0]
        diversity = len({pk["slug"] for pk in picks.values()})
        s.mark(len(picks) == len(PERSONAS),
               f"picks={len(picks)}/{len(PERSONAS)} slugs_distintos={diversity} produced={n_prod}")
    except Exception as e:
        s.mark(False, error=str(e)[:180])
    stages.append(s)

    # 5. SCORING
    s = Stage("5. SCORING  hook mock -> hook_scores")
    try:
        from apps.scoring.hook_scorer import HookScore, persist_hook_score, ensure_schema
        ensure_schema(conn)
        scored = 0
        for p, pick in picks.items():
            hs = HookScore(
                audio_energy_score=0.72, cps_score=0.80, accent_word_score=0.90,
                llm_score=None, overall=0.78,
                raw_rms_peak=0.15, raw_cps_observed=1.5, raw_cps_target=1.3,
                raw_first_sub_text=f"What if {pick['title']} was real?",
                notes=["mock score verify_full_flow"],
            )
            persist_hook_score(conn, f"outputs/mock/{p}_{pick['slug']}.mp4", hs,
                               persona=p, vtype="narration", series_slug=pick["slug"])
            scored += 1
        passed = conn.execute("SELECT COALESCE(SUM(passed),0) FROM hook_scores").fetchone()[0]
        s.mark(scored > 0, f"scored={scored} passed={passed}")
    except Exception as e:
        s.mark(False, error=str(e)[:180])
    stages.append(s)

    # 6. ANALYTICS (web 1a parte + resultado de plataforma)
    s = Stage("6. ANALYTICS  web (plausible) + plataforma (YT/TT)")
    try:
        from apps.analytics.internal_signals import persist_pageviews, persist_events
        n_pv = persist_pageviews(conn, [
            {"page": "/", "visitors": 120, "pageviews": 210, "bounce_rate": 40.0, "visit_duration": 80.0},
            {"page": "/dashboard.html", "visitors": 64, "pageviews": 110, "bounce_rate": 52.0, "visit_duration": 70.0},
            {"page": "/contact.html", "visitors": 22, "pageviews": 30, "bounce_rate": 61.0, "visit_duration": 40.0},
        ], "2026-05-25", "2026-06-01")
        n_ev = persist_events(conn, [
            {"goal": "cta_click", "visitors": 30, "events": 38},
            {"goal": "persona_click", "visitors": 12, "events": 14},
        ], "2026-05-25", "2026-06-01")
        # Resultado de plataforma: un short mock por pick, con métricas YT/TT.
        # Cierra la capa [4] del embudo (lo que ya producimos y cómo le fue).
        n_plat = 0
        platforms = ["youtube", "tiktok"]
        for i, (p, pick) in enumerate(picks.items()):
            cur = conn.execute(
                "INSERT INTO shorts (title, series_name, status) VALUES (?, ?, 'uploaded')",
                (f"{pick['title']} — {p}", pick["slug"]),
            )
            short_id = cur.lastrowid
            conn.execute(
                """INSERT INTO analytics (short_id, platform, views, likes, comments,
                       shares, retention_avg, engagement_rate)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (short_id, platforms[i % 2], 5000 + i * 3200, 300 + i * 120,
                 40 + i * 10, 20 + i * 8, 38.0 + i * 3, 0.06 + i * 0.01),
            )
            n_plat += 1
        conn.commit()
        s.mark(n_pv > 0 and n_ev > 0 and n_plat > 0,
               f"pageviews={n_pv} events={n_ev} plataforma={n_plat}")
    except Exception as e:
        s.mark(False, error=str(e)[:180])
    stages.append(s)

    # 7. UNIFIED
    s = Stage("7. UNIFIED  vista conjunta (4 capas)")
    try:
        from apps.analytics.unified_analytics import build, render
        report = build(conn, source="joint")
        summary["unified"] = report
        ok = (report["web_funnel"]["visitors"] > 0
              and report["content_quality"]["scored"] > 0
              and bool(report["persona_rollup"]))
        s.mark(ok, f"capas=4 personas_rollup={len(report['persona_rollup'])}")
        if show_report:
            summary["_rendered"] = render(report)
    except Exception as e:
        s.mark(False, error=str(e)[:180])
    stages.append(s)

    summary["stages"] = [st.to_dict() for st in stages]
    summary["hard_pass"] = all(st.passed for st in stages)
    conn.close()
    return stages, summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--json", default=None, help="Vuelca el summary a un archivo JSON")
    ap.add_argument("--show-report", action="store_true", help="Imprime la vista conjunta al final")
    args = ap.parse_args()

    _disable_network()

    print()
    print("=" * 72)
    print("  VERIFY FULL FLOW · E2E conjunto (mock, offline)")
    print("=" * 72)

    stages, summary = run(show_report=args.show_report)
    for st in stages:
        print(_line(st))

    n_ok = sum(1 for st in stages if st.passed)
    print()
    print(f"  Resultado: {n_ok}/{len(stages)} fases OK   "
          f"({'FLUJO VERDE' if n_ok == len(stages) else 'HAY ROTOS'})")
    print("=" * 72)

    if args.show_report and summary.get("_rendered"):
        print()
        print(summary["_rendered"])

    if args.json:
        payload = {k: v for k, v in summary.items() if k != "_rendered"}
        Path(args.json).write_text(json.dumps(payload, indent=2, ensure_ascii=False,
                                              default=str), encoding="utf-8")

    return 0 if summary.get("hard_pass") else 1


if __name__ == "__main__":
    sys.exit(main())
