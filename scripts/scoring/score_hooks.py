"""
score_hooks — batch CLI para puntuar los primeros segundos de videos ya producidos.

Útil para:
  - Calibrar MIN_HOOK_SCORE antes de activar el gate bloqueante.
  - Comparar A/B de hooks (CPS fijo vs beat-sync, accent vs no accent).
  - Benchmark contra videos extraídos por AutoClip u otra fuente externa.
  - Auditoría retroactiva de toda la carpeta outputs/produce.

Uso:
  python scripts/score_hooks.py                              # todo outputs/produce
  python scripts/score_hooks.py --series berserk             # solo una serie
  python scripts/score_hooks.py --persona deep_mind          # solo una persona
  python scripts/score_hooks.py --vtype narration            # solo un tipo
  python scripts/score_hooks.py --use-llm                    # añade LLM score
  python scripts/score_hooks.py --json out.json              # export JSON
  python scripts/score_hooks.py --min-score 0.60             # umbral custom
  python scripts/score_hooks.py --pass-only                  # imprime solo passes
  python scripts/score_hooks.py --rescore                    # re-puntuar aunque ya exista

Convención de paths esperada:
  outputs/produce/{slug}/{vtype}/FINAL_{VTYPE}.mp4
  outputs/produce/{slug}/scripts.json

El script carga `scripts.json` para recuperar el hook_text y accent_word
(usa script_generator.detect_hook_accent_word).

Notas MLOps:
  - --rescore inserta una nueva fila en hook_scores; no sobrescribe.
  - Modo --benchmark CSV-friendly para pegar a Sheets o pandas.
  - TODO: añadir cluster por persona × vtype con percentiles 25/50/75.
"""
from __future__ import annotations

import argparse
import csv
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
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("score_hooks")


def _load_settings():
    try:
        from core.config import Settings
        return Settings()
    except Exception as e:
        log.warning("Settings no disponible: %s", e)
        return None


def _discover_videos(produce_root: Path, series_filter: str | None,
                      vtype_filter: str | None) -> list[tuple[str, str, Path, Path]]:
    """Encuentra (slug, vtype, video_path, scripts_json) bajo outputs/produce."""
    items = []
    if not produce_root.exists():
        log.warning("no existe %s", produce_root)
        return items
    for slug_dir in produce_root.iterdir():
        if not slug_dir.is_dir():
            continue
        if series_filter and series_filter.lower() not in slug_dir.name.lower():
            continue
        scripts_json = slug_dir / "scripts.json"
        for vtype_dir in slug_dir.iterdir():
            if not vtype_dir.is_dir():
                continue
            vtype = vtype_dir.name
            if vtype_filter and vtype != vtype_filter:
                continue
            final = vtype_dir / f"FINAL_{vtype.upper()}.mp4"
            if final.exists():
                items.append((slug_dir.name, vtype, final, scripts_json))
    return items


def _extract_hook_metadata(scripts_json: Path, vtype: str) -> tuple[str, str | None]:
    """Devuelve (hook_text, accent_word) del scripts.json de la serie."""
    if not scripts_json.exists():
        return "", None
    try:
        data = json.loads(scripts_json.read_text(encoding="utf-8"))
        segs = data.get(vtype) or []
        if not segs:
            return "", None
        hook_text = segs[0].get("text", "") if isinstance(segs[0], dict) else ""
        from apps.production.script_generator import detect_hook_accent_word
        accent = detect_hook_accent_word(hook_text, vtype) if hook_text else None
        return hook_text, accent
    except Exception as e:
        log.warning("read scripts.json failed: %s", e)
        return "", None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--produce-root", default="outputs/produce",
                    help="Raíz donde están los videos producidos")
    ap.add_argument("--series", default=None,
                    help="Filtro substring sobre el slug de serie")
    ap.add_argument("--persona", default=None,
                    help="Filtro de persona — heurística por slug; opcional")
    ap.add_argument("--vtype", default=None, choices=["narration", "personality", "test"])
    ap.add_argument("--use-llm", action="store_true",
                    help="Activa LLM score (suma campo llm_score)")
    ap.add_argument("--min-score", type=float, default=None,
                    help="Override MIN_HOOK_SCORE")
    ap.add_argument("--pass-only", action="store_true",
                    help="Imprime solo videos que pasan el umbral")
    ap.add_argument("--rescore", action="store_true",
                    help="Re-puntuar aunque ya exista un score previo")
    ap.add_argument("--json", default=None,
                    help="Ruta para volcar resultados como JSON")
    ap.add_argument("--csv", default=None,
                    help="Ruta para volcar resultados como CSV (benchmark)")
    args = ap.parse_args()

    from apps.scoring.hook_scorer import (
        score_hook, persist_hook_score, fetch_score_for_video,
        ensure_schema, MIN_HOOK_SCORE,
    )

    min_score = args.min_score if args.min_score is not None else MIN_HOOK_SCORE
    conn = sqlite3.connect("data/shorts_pipeline.db")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)

    items = _discover_videos(
        Path(args.produce_root),
        series_filter=args.series,
        vtype_filter=args.vtype,
    )
    log.info("Encontrados %d videos para scorear", len(items))

    settings = _load_settings() if args.use_llm else None
    results = []

    for slug, vtype, video_path, scripts_json in items:
        # Skip si ya existe score y no --rescore
        if not args.rescore:
            existing = fetch_score_for_video(conn, video_path)
            if existing:
                results.append({
                    "slug": slug, "vtype": vtype,
                    "video_path": str(video_path),
                    "overall": existing["overall_score"],
                    "passed": bool(existing["passed"]),
                    "scored_at": existing["scored_at"],
                    "from_cache": True,
                })
                continue

        hook_text, accent_word = _extract_hook_metadata(scripts_json, vtype)
        score = score_hook(
            video_path=video_path,
            vtype=vtype,
            hook_text=hook_text,
            accent_word=accent_word,
            edl=None,
            first_sub_text=hook_text,
            use_llm=args.use_llm,
            settings=settings,
        )
        persist_hook_score(
            conn, video_path, score,
            persona=args.persona, vtype=vtype, series_slug=slug,
            min_score=min_score,
        )
        results.append({
            "slug": slug, "vtype": vtype,
            "video_path": str(video_path),
            "audio_energy": score.audio_energy_score,
            "cps": score.cps_score,
            "accent": score.accent_word_score,
            "llm": score.llm_score,
            "overall": score.overall,
            "passed": score.passes(min_score),
            "raw_rms_peak": score.raw_rms_peak,
            "raw_cps_observed": score.raw_cps_observed,
            "raw_cps_target": score.raw_cps_target,
            "from_cache": False,
        })

    # Filtrado pasa-solo
    if args.pass_only:
        results = [r for r in results if r.get("passed")]

    # Salidas
    _print_summary(results, min_score)
    if args.json:
        Path(args.json).write_text(
            json.dumps({"min_score": min_score, "results": results,
                        "generated_at": datetime.now().isoformat()},
                       indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        log.info("JSON → %s", args.json)
    if args.csv:
        _write_csv(args.csv, results)
        log.info("CSV → %s", args.csv)

    conn.close()
    return 0


def _print_summary(results: list[dict], min_score: float):
    if not results:
        print("(sin resultados)")
        return
    print()
    print(f"══════════════════════════════════════════════════════════════════")
    print(f"  HOOK SCORES · min_score = {min_score:.2f}")
    print(f"══════════════════════════════════════════════════════════════════")
    print(f"  {'slug':24s} {'vtype':12s} {'audio':>6s} {'cps':>5s} {'accent':>7s} {'llm':>5s} {'overall':>8s}  status")
    print(f"  {'-'*24} {'-'*12} {'-'*6} {'-'*5} {'-'*7} {'-'*5} {'-'*8}  ------")
    passes = 0
    fails = 0
    for r in results:
        ovr = r.get("overall", 0.0) or 0.0
        passed = r.get("passed", False)
        if passed:
            passes += 1
        else:
            fails += 1
        audio = r.get("audio_energy", "—")
        cps = r.get("cps", "—")
        accent = r.get("accent", "—")
        llm = r.get("llm")
        audio_s = f"{audio:.2f}" if isinstance(audio, (int, float)) else str(audio)
        cps_s = f"{cps:.2f}" if isinstance(cps, (int, float)) else str(cps)
        accent_s = f"{accent:.2f}" if isinstance(accent, (int, float)) else str(accent)
        llm_s = f"{llm:.2f}" if isinstance(llm, (int, float)) else "—"
        mark = "PASS" if passed else "FAIL"
        slug = r.get("slug", "")[:24]
        vtype = r.get("vtype", "")[:12]
        print(f"  {slug:24s} {vtype:12s} {audio_s:>6s} {cps_s:>5s} {accent_s:>7s} {llm_s:>5s} {ovr:>8.2f}  {mark}")
    print(f"  {'-'*24} {'-'*12} {'-'*6} {'-'*5} {'-'*7} {'-'*5} {'-'*8}  ------")
    total = passes + fails
    if total:
        print(f"  TOTAL: {total}   PASS: {passes} ({100*passes/total:.0f}%)   FAIL: {fails} ({100*fails/total:.0f}%)")
    print()


def _write_csv(path: str, results: list[dict]):
    if not results:
        return
    fieldnames = ["slug", "vtype", "video_path",
                  "audio_energy", "cps", "accent", "llm", "overall", "passed",
                  "raw_rms_peak", "raw_cps_observed", "raw_cps_target",
                  "from_cache"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in results:
            w.writerow(r)


if __name__ == "__main__":
    sys.exit(main())
