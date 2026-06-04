"""
refresh_market_signals — CLI runner para la capa de inteligencia de consumo.

Hace 3 cosas en orden:
  1. Ingesta cruda (`market_signals.refresh_all_sources`)
  2. Mantenimiento (`market_signals.prune_old_signals`)
  3. Destilación a briefs por persona (`signals_distiller.distill`)

Uso típico:
  python scripts/refresh_market_signals.py                       # full pipeline
  python scripts/refresh_market_signals.py --domains gaming      # solo gaming
  python scripts/refresh_market_signals.py --sources steam_charts opencritic
  python scripts/refresh_market_signals.py --no-llm              # skip suggested_angle
  python scripts/refresh_market_signals.py --no-distill          # solo ingesta
  python scripts/refresh_market_signals.py --report-only         # solo lectura

Ejecución programada (sugerencia):
  - GitHub Actions cron cada 4h para refresh + distill (sin LLM).
  - Job manual diario con --no-distill para barrido amplio.
  - Job nocturno con LLM activado para regenerar briefs con angle.

Notas MLOps:
  - Salida JSON estructurada (--json) para alimentar dashboards externos.
  - Exit code != 0 si total_new == 0 y --fail-on-empty (catch silent breakage).
  - El runner NO levanta el LLM por sí mismo; usa LLMProvider con jerarquía
    interna (airllm → groq → gemini → fallback heurístico).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Setup PYTHONPATH para imports relativos
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.chdir(str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("refresh_market_signals")


def _load_settings():
    """Carga Settings si existe el módulo; si no, retorna None.

    El distiller funciona sin Settings (use_llm=False).
    """
    try:
        from core.config import Settings
        return Settings()
    except Exception as e:
        log.warning("Settings no disponible: %s (continuando sin LLM)", e)
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--domains", nargs="*", default=None,
                        help="Filtra por dominio (gaming, anime_manga, movies_tv, music, latam)")
    parser.add_argument("--sources", nargs="*", default=None,
                        help="Filtra por nombre exacto de fuente (ver SOURCES en market_signals.py)")
    parser.add_argument("--no-distill", action="store_true",
                        help="Solo refresca señales crudas; no genera briefs")
    parser.add_argument("--no-llm", action="store_true",
                        help="Destilar sin LLM (suggested_angle quedará vacío)")
    parser.add_argument("--retention-days", type=int, default=30,
                        help="Borra señales más viejas que N días (default 30)")
    parser.add_argument("--window-days", type=int, default=7,
                        help="Ventana de señales que consume el distiller (default 7)")
    parser.add_argument("--top-per-persona", type=int, default=12,
                        help="Cuántos briefs por persona persistir (default 12)")
    parser.add_argument("--report-only", action="store_true",
                        help="Solo imprime el estado actual (briefs por persona); no ingiere")
    parser.add_argument("--json", action="store_true",
                        help="Salida JSON al final (para CI/dashboards)")
    parser.add_argument("--fail-on-empty", action="store_true",
                        help="Exit code != 0 si no se ingirió ninguna señal nueva")
    args = parser.parse_args()

    from core.db import get_db
    conn = get_db(Path("data"))

    report = {
        "started_at": datetime.now().isoformat(),
        "args": vars(args),
    }

    if args.report_only:
        from apps.signals.signals_distiller import fetch_briefs_for_persona, PERSONA_ALIGNMENT
        summary = {}
        for persona in PERSONA_ALIGNMENT:
            briefs = fetch_briefs_for_persona(conn, persona, limit=10)
            summary[persona] = [
                {"score": b["score"], "headline": b["headline"], "angle": b["suggested_angle"]}
                for b in briefs
            ]
        report["briefs"] = summary
        _emit(report, args.json)
        return 0

    # 1. Ingesta cruda
    log.info("════ FASE 1: ingesta de señales ════")
    from apps.signals.market_signals import refresh_all_sources, prune_old_signals
    ingest_report = refresh_all_sources(
        conn,
        domains=args.domains,
        sources=args.sources,
    )
    report["ingest"] = ingest_report
    log.info("Total señales nuevas: %d", ingest_report["total_new"])

    # 2. Mantenimiento
    log.info("════ FASE 2: prune ════")
    pruned = prune_old_signals(conn, retention_days=args.retention_days)
    report["pruned"] = pruned

    # 3. Distill
    if not args.no_distill:
        log.info("════ FASE 3: destilación ════")
        from apps.signals.signals_distiller import distill
        settings = _load_settings()
        use_llm = not args.no_llm and settings is not None
        n_briefs = distill(
            conn,
            settings=settings,
            window_days=args.window_days,
            top_per_persona=args.top_per_persona,
            use_llm=use_llm,
        )
        report["briefs_inserted"] = n_briefs
        report["llm_used"] = use_llm
        log.info("Briefs insertados: %d (LLM=%s)", n_briefs, use_llm)
    else:
        report["briefs_inserted"] = 0
        log.info("--no-distill: skip fase 3")

    report["finished_at"] = datetime.now().isoformat()
    _emit(report, args.json)

    if args.fail_on_empty and ingest_report["total_new"] == 0:
        log.error("--fail-on-empty: 0 señales nuevas → exit 1")
        return 1
    return 0


def _emit(report: dict, as_json: bool):
    if as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print()
        print("══════════════════════════════════════════════════════")
        print("  REFRESH MARKET SIGNALS · resumen")
        print("══════════════════════════════════════════════════════")
        if "ingest" in report:
            print(f"  Total nuevas: {report['ingest']['total_new']}")
            for src, n in report["ingest"]["sources"].items():
                mark = "+" if n > 0 else " "
                print(f"    {mark} {src:30s} {n:>5}")
        if "briefs_inserted" in report:
            print(f"  Briefs insertados: {report['briefs_inserted']}")
        if "briefs" in report:
            for p, briefs in report["briefs"].items():
                print(f"\n  [{p}] top:")
                for b in briefs[:5]:
                    print(f"    {b['score']:6.2f}  {b['headline'][:80]}")
                    if b.get("angle"):
                        print(f"           ↳ {b['angle']}")
        print("══════════════════════════════════════════════════════")


if __name__ == "__main__":
    sys.exit(main())
