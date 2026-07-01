"""
verify_signals_flow — Smoke E2E reproducible del flujo de información.

Diferente a `pytest`:
  - Se ejecuta contra la DB REAL (`data/shorts_pipeline.db`), no in-memory.
  - Es seguro: usa un namespace de fuente `verify_` para no contaminar prod.
  - Imprime un reporte tipo checklist en consola con ✓ / ✗ por etapa.
  - Útil cuando "quiero ver que esto funciona AHORA" sin levantar pytest.

Uso:
  python scripts/verify_signals_flow.py
  python scripts/verify_signals_flow.py --cleanup        # borra el namespace verify_ al final
  python scripts/verify_signals_flow.py --json out.json  # reporte estructurado

Sale con exit code 0 si todo verde, 1 si alguna etapa hard-falla.

Etapas:
  1. Inserción de señales sintéticas (namespace verify_)
  2. Distill produce briefs
  3. Resolver maps briefs a slugs reales del CATALOG
  4. Sweep encola los unresolved
  5. Rotator hace pick aprovechando los briefs nuevos
  6. Validación de invariantes (signals_validation)
  7. Limpieza de namespace verify_ (si --cleanup)
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
sys.path.insert(0, str(ROOT / "src"))   # estructura src/apps|core|utils
os.chdir(str(ROOT))

# Smoke sobre DB de prueba (10 señales sintéticas): los invariantes HARD de
# signals_validation asumen volumen de producción (>=80 señales/24h). En este
# contexto de prueba bajamos los umbrales de volumen vía env (se leen al
# importar signals_validation, por eso se setean ANTES de cualquier import).
os.environ.setdefault("MIN_SIGNALS_24H", "1")
os.environ.setdefault("MIN_SIGNALS_7D", "1")

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

# Smoke offline: el flujo es sintético; el stage del rotator llama a
# trending_anime (red real). Bloqueamos red + silenciamos el WARNING spam
# para que el smoke sea determinista y no dependa de AniList/Jikan.
def _go_offline():
    import requests
    def _b(*a, **k):
        raise RuntimeError("HTTP real bloqueado (verify_signals_flow es smoke offline)")
    for obj, attr in ((requests, "get"), (requests, "post"),
                      (requests.Session, "get"), (requests.Session, "post")):
        try:
            setattr(obj, attr, _b)
        except Exception:
            pass
    logging.disable(logging.WARNING)

_go_offline()


# ── Señales sintéticas (mismas semánticas que tests/conftest.sample_signals,
#    pero con prefijo verify_ para aislar del corpus real) ──────────


def _verify_signals():
    from apps.signals.market_signals import Signal
    return [
        Signal("verify_ann",          "editorial_rss",    "anime_manga",
               "[verify] Frieren wins anime of the year at MAL"),
        Signal("verify_reddit_anime", "reddit_thread",    "anime_manga",
               "[verify] Frieren beats own record at MAL",
               raw_score=4500),
        Signal("verify_animefem",     "editorial_rss",    "anime_manga",
               "[verify] Sousou no Frieren feminist reading"),
        Signal("verify_steam",        "gaming_chart",     "gaming",
               "[verify] Elden Ring", raw_score=42, raw_meta={"rank": 8}),
        Signal("verify_oc",           "gaming_review",    "gaming",
               "[verify] Elden Ring still the GOTY 3 years later"),
        Signal("verify_reddit_games", "reddit_thread",    "gaming",
               "[verify] Elden Ring DLC retrospective", raw_score=5800),
        Signal("verify_variety",      "editorial_rss",    "movies_tv",
               "[verify] Mads Mikkelsen on Hannibal Lecter legacy"),
        Signal("verify_truefilm",     "reddit_thread",    "movies_tv",
               "[verify] Hannibal's silent dinner scene as visual poetry",
               raw_score=2100),
        Signal("verify_variety_latam","editorial_rss",    "latam",
               "[verify] Yo soy Betty la fea reboot announced"),
        Signal("verify_ann_dandadan", "editorial_rss",    "anime_manga",
               "[verify] Dandadan adapted by Science Saru"),
    ]


# ── Stage runners ──────────────────────────────────────────────────


class Stage:
    """Wrapper para registrar resultados con check-marks."""
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


def _print_line(s: Stage):
    mark = "✓" if s.passed else "✗"
    print(f"  [{mark}] {s.name:55s} {s.detail}")
    if s.error:
        print(f"        ↳ ERROR: {s.error}")


def run() -> tuple[list[Stage], dict]:
    stages: list[Stage] = []
    summary: dict = {"started_at": datetime.now().isoformat()}

    conn = sqlite3.connect("data/shorts_pipeline.db")
    conn.row_factory = sqlite3.Row

    # ─ Stage 1: inserción ─────────────────────────────────────────
    s1 = Stage("Inserción de señales sintéticas (namespace verify_)")
    try:
        from apps.signals.market_signals import _persist_many
        n = _persist_many(conn, _verify_signals())
        s1.mark(n > 0, f"insertadas={n}")
    except Exception as e:
        s1.mark(False, error=str(e)[:200])
    stages.append(s1)
    if not s1.passed:
        return stages, summary

    # ─ Stage 2: distill ──────────────────────────────────────────
    s2 = Stage("Distill produce briefs por persona")
    try:
        from apps.signals.signals_distiller import distill, fetch_briefs_for_persona
        n_briefs = distill(conn, settings=None, use_llm=False,
                            window_days=30, top_per_persona=10)
        per_p = {p: len(fetch_briefs_for_persona(conn, p, limit=20))
                  for p in ["deep_mind", "pop_oracle", "latam"]}
        s2.mark(all(v >= 1 for v in per_p.values()),
                f"insertados={n_briefs} · live por persona={per_p}")
    except Exception as e:
        s2.mark(False, error=str(e)[:200])
    stages.append(s2)

    # ─ Stage 3: resolver mapea briefs ────────────────────────────
    s3 = Stage("Resolver mapea briefs a CATALOG (alias / fuzzy)")
    try:
        from apps.signals.signals_distiller import fetch_briefs_for_persona
        from apps.signals.brief_resolver import resolve_brief
        from apps.production.content_rotator import CATALOG
        resolved_count = 0
        unresolved_count = 0
        for p in ["deep_mind", "pop_oracle", "latam"]:
            for b in fetch_briefs_for_persona(conn, p, limit=10, only_unconsumed=True):
                slug, layer = resolve_brief(b, CATALOG, conn)
                if slug:
                    resolved_count += 1
                else:
                    unresolved_count += 1
        s3.mark(resolved_count > 0,
                f"resolved={resolved_count} · unresolved={unresolved_count}")
    except Exception as e:
        s3.mark(False, error=str(e)[:200])
    stages.append(s3)

    # ─ Stage 4: sweep encola unresolved ──────────────────────────
    s4 = Stage("Sweep encola briefs sin match")
    try:
        from apps.signals.brief_resolver import sweep_unresolved, list_unresolved
        from apps.production.content_rotator import CATALOG
        sweep_unresolved(conn, CATALOG)
        unresolved = list_unresolved(conn)
        # Esperamos encontrar 'Dandadan' (no está en CATALOG)
        headlines = [r["headline"].lower() for r in unresolved]
        found_dandadan = any("dandadan" in h for h in headlines)
        s4.mark(found_dandadan,
                f"queue size={len(unresolved)} · dandadan_in_queue={found_dandadan}")
    except Exception as e:
        s4.mark(False, error=str(e)[:200])
    stages.append(s4)

    # ─ Stage 5: rotator hace pick brief-aware ────────────────────
    s5 = Stage("Rotator hace pick aprovechando briefs vivos")
    try:
        from apps.production.content_rotator import ContentRotator, init_rotation_db
        r = ContentRotator.__new__(ContentRotator)
        r.conn = conn
        init_rotation_db(r.conn)

        picks = {p: r.pick_next(p, consume_briefs=False)
                  for p in ["deep_mind", "pop_oracle", "latam"]}
        success_picks = sum(1 for v in picks.values() if v)
        diversity = len({p["slug"] for p in picks.values() if p})
        s5.mark(success_picks == 3 and diversity >= 2,
                f"picks_ok={success_picks}/3 · slugs_distintos={diversity}")
    except Exception as e:
        s5.mark(False, error=str(e)[:200])
    stages.append(s5)

    # ─ Stage 6: validación de invariantes ───────────────────────
    s6 = Stage("Invariantes de Data Verification")
    try:
        from apps.signals.signals_validation import run_all_checks
        rep = run_all_checks(conn)
        hard_fail = rep.hard_failures()
        soft_fail = rep.soft_failures()
        s6.mark(len(hard_fail) == 0,
                f"hard_fails={len(hard_fail)} · soft_fails={len(soft_fail)}",
                error=("; ".join(f"{c.name}={c.actual}" for c in hard_fail)
                       if hard_fail else None))
    except Exception as e:
        s6.mark(False, error=str(e)[:200])
    stages.append(s6)

    summary["finished_at"] = datetime.now().isoformat()
    summary["stages"] = [s.to_dict() for s in stages]
    summary["hard_pass"] = all(s.passed for s in stages)
    conn.close()
    return stages, summary


# ── Cleanup ─────────────────────────────────────────────────────


def cleanup_namespace(verbose: bool = True) -> int:
    """Borra todo lo que insertamos (signals + briefs + unresolved del namespace verify_)."""
    conn = sqlite3.connect("data/shorts_pipeline.db")
    deleted = 0
    # 1. unresolved que vienen de briefs verify_
    n1 = conn.execute(
        """DELETE FROM unresolved_briefs_queue
           WHERE brief_id IN (
               SELECT id FROM persona_briefs
               WHERE EXISTS (
                   SELECT 1 FROM market_signals ms
                   WHERE ms.source LIKE 'verify_%'
                     AND ms.id IN (SELECT value FROM json_each(persona_briefs.sources_json))
               )
           )"""
    ).rowcount
    # 2. briefs cuyos signals son verify_
    n2 = conn.execute(
        """DELETE FROM persona_briefs
           WHERE EXISTS (
               SELECT 1 FROM market_signals ms
               WHERE ms.source LIKE 'verify_%'
                 AND ms.id IN (SELECT value FROM json_each(persona_briefs.sources_json))
           )"""
    ).rowcount
    # 3. signals verify_
    n3 = conn.execute("DELETE FROM market_signals WHERE source LIKE 'verify_%'").rowcount
    conn.commit()
    conn.close()
    deleted = n1 + n2 + n3
    if verbose:
        print(f"  cleanup: borradas {n3} signals + {n2} briefs + {n1} unresolved")
    return deleted


# ── Main ────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--cleanup", action="store_true",
                    help="Borra el namespace verify_ al final")
    ap.add_argument("--cleanup-only", action="store_true",
                    help="Solo limpia, no corre la verificación")
    ap.add_argument("--json", default=None, help="Volcado estructurado")
    args = ap.parse_args()

    if args.cleanup_only:
        cleanup_namespace()
        return 0

    print()
    print("═" * 72)
    print("  VERIFY SIGNALS FLOW · checklist E2E sobre DB real")
    print("═" * 72)

    stages, summary = run()
    for s in stages:
        _print_line(s)

    n_pass = sum(1 for s in stages if s.passed)
    n_total = len(stages)
    print()
    print(f"  Resultado: {n_pass}/{n_total} stages OK   "
          f"({'✓ FLOW VERDE' if n_pass == n_total else '✗ HAY ROTOS'})")
    print("═" * 72)

    if args.json:
        Path(args.json).write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8",
        )

    if args.cleanup:
        print()
        cleanup_namespace()

    return 0 if n_pass == n_total else 1


if __name__ == "__main__":
    sys.exit(main())
