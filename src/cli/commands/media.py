"""`ylk media …` — dominio Media (Extract: fuentes, índice, regiones).

Runner delgado: parsea args y delega en apps.media.*.

    ylk media ingest "Night of the Living Dead" --year 1968   # buscar + registrar + indexar
    ylk media search "Night of the Living Dead" --year 1968
    ylk media add archive_org Night.Of.The.Living.Dead_1080p
    ylk media scan                       # biblioteca local (MOVIES_DIR)
    ylk media assets
    ylk media index 1 --asr-backend groq # probe + proxy + audio/planos + ASR
    ylk media index-many --pending       # lote en pipeline (red ∥ GPU/API)
    ylk media runs                       # segundos por etapa (optimización)
    ylk media fetch 1 1800000 1810000 --measure --exact out.mp4
    ylk media storage                    # cuánto ocupa cada capa
    ylk media gc                         # tope de segmentos + limpiar análisis ya usado
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import typer

app = typer.Typer(no_args_is_help=True, add_completion=False,
                  help="Fuentes de video, índice de obras y extracción de regiones")


def _db() -> sqlite3.Connection:
    from core.config import load_settings
    from core.db import get_db
    return get_db(load_settings().data_dir)


def _print(obj) -> None:
    typer.echo(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


@app.command()
def search(title: str, year: int = typer.Option(None, help="Año aproximado (±1)"),
           provider: list[str] = typer.Option(["local", "archive_org"], help="archive_org | local"),
           all_rights: bool = typer.Option(False, "--all-rights", help="Incluir derechos unknown/restricted"),
           limit: int = 5):
    """Busca candidatos para una obra en los proveedores."""
    from apps.media.sources import search_all
    cands = search_all(title, year, providers=provider, only_usable=not all_rights, limit=limit)
    _print([{"provider": c.provider, "id": c.external_id, "title": c.title, "year": c.year,
             "rights": c.rights, "height": c.height, "duration_min": round(c.duration_ms / 60000, 1),
             "master": c.extra.get("master_file") or c.master_uri,
             "proxy": c.extra.get("proxy_file")} for c in cands])


@app.command()
def add(provider: str, external_id: str,
        title: str = typer.Option(None, help="Título canónico de la obra (default: el del proveedor)"),
        year: int = typer.Option(None),
        allow_unknown_rights: bool = typer.Option(False, help="Registrar aunque los derechos no sean usables")):
    """Registra un ítem concreto (IA identifier o ruta relativa en MOVIES_DIR)."""
    from apps.media.indexer import register_candidate
    from apps.media.sources import get_provider
    prov = get_provider(provider)
    if provider in ("archive_org", "ia"):
        cand = prov.get_item(external_id)
    else:
        cand = next((c for c in prov.scan() if c.external_id == external_id), None)
    if cand is None:
        raise typer.BadParameter(f"No encontrado: {external_id}")
    if not cand.usable and not allow_unknown_rights:
        typer.echo(f"Derechos '{cand.rights}' ({cand.license_url or 'sin licencia'}): no usable. "
                   "Usa --allow-unknown-rights solo si verificaste los derechos.", err=True)
        raise typer.Exit(2)
    asset_id = register_candidate(_db(), cand, work_title=title, work_year=year)
    _print({"asset_id": asset_id, "title": cand.title, "rights": cand.rights,
            "master": cand.master_uri, "proxy": cand.proxy_uri})


@app.command()
def scan(root: Path = typer.Option(None, help="Default: MOVIES_DIR")):
    """Indexa la biblioteca local (no descarga nada; derechos = owned)."""
    from apps.media.indexer import register_candidate
    from apps.media.local_library import LocalLibraryProvider
    conn = _db()
    cands = LocalLibraryProvider(root).scan()
    ids = [register_candidate(conn, c) for c in cands]
    _print({"registered": len(ids), "root": str(root or LocalLibraryProvider().root)})


@app.command()
def assets():
    """Lista assets registrados y su estado de indexado."""
    conn = _db()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT a.id, w.title, w.year, a.season, a.episode, a.provider, a.rights,
                  a.height, a.duration_ms, a.accept_ranges,
                  a.transcribed_at IS NOT NULL AS asr, a.shots_at IS NOT NULL AS shots
           FROM media_assets a JOIN works w ON w.id = a.work_id ORDER BY a.id""").fetchall()
    _print([dict(r) for r in rows])


_ASR_HELP = "auto|local|groq (default: ASR_BACKEND del .env)"


@app.command()
def index(asset_id: int,
          step: list[str] = typer.Option(None, help="probe|proxy|audio|shots|asr (default: todos)"),
          force: bool = False,
          asr_backend: str = typer.Option(None, help=_ASR_HELP),
          model: str = typer.Option("large-v3-turbo", help="Modelo faster-whisper (backend local)"),
          language: str = typer.Option(None, help="Forzar idioma (es, en, it…)"),
          shot_backend: str = typer.Option("auto", help="auto|pyscenedetect|scdet"),
          connections: int = typer.Option(6, help="Conexiones paralelas para bajar el proxy")):
    """Indexa un asset: probe, proxy, audio + planos (1 pasada), transcripción por palabra."""
    from apps.media.indexer import STEPS, index_asset
    steps = tuple(step) if step else STEPS
    _print(index_asset(_db(), asset_id, steps=steps, force=force, asr_model=model,
                       asr_backend=asr_backend, language=language, shot_backend=shot_backend,
                       connections=connections))


@app.command("index-many")
def index_many(asset_ids: list[int] = typer.Argument(None),
               pending: bool = typer.Option(False, help="Todos los assets sin transcripción o sin planos"),
               asr_backend: str = typer.Option(None, help=_ASR_HELP),
               language: str = typer.Option(None),
               connections: int = typer.Option(6),
               force: bool = False):
    """Indexa varios assets en pipeline: la red baja el siguiente mientras la GPU/API transcribe."""
    from apps.media.indexer import index_many as run_many
    conn = _db()
    ids = list(asset_ids or [])
    if pending:
        ids += [r[0] for r in conn.execute(
            "SELECT id FROM media_assets WHERE (transcribed_at IS NULL OR shots_at IS NULL) "
            "AND rights IN ('public_domain', 'open_license', 'owned') ORDER BY id")]
    ids = list(dict.fromkeys(ids))
    if not ids:
        raise typer.BadParameter("Sin assets: pasa ids o --pending")
    _print(run_many(_db, ids, force=force, asr_backend=asr_backend, language=language,
                    connections=connections))


@app.command()
def ingest(title: str, year: int = typer.Option(None),
           provider: list[str] = typer.Option(["local", "archive_org"]),
           index_now: bool = typer.Option(True, "--index/--no-index", help="Indexar al registrar"),
           asr_backend: str = typer.Option(None, help=_ASR_HELP)):
    """Busca la mejor copia con derechos usables, la registra y la indexa (un comando)."""
    from apps.media.indexer import index_asset, register_candidate
    from apps.media.sources import search_all
    cands = [c for c in search_all(title, year, providers=provider, limit=5)
             if not c.extra.get("partial")]
    if not cands:
        typer.echo(f"Sin copias con derechos usables para {title!r} ({year or 's/a'}). "
                   "Prueba `ylk media search --all-rights` para ver qué hay.", err=True)
        raise typer.Exit(1)
    best = cands[0]
    conn = _db()
    asset_id = register_candidate(conn, best, work_title=title, work_year=year)
    out = {"asset_id": asset_id, "provider": best.provider, "id": best.external_id,
           "rights": best.rights, "master": best.extra.get("master_file") or best.master_uri}
    if index_now:
        out["index"] = index_asset(conn, asset_id, asr_backend=asr_backend)
    _print(out)


@app.command()
def runs(asset_id: int = typer.Option(None), last: int = 30):
    """Tiempos por etapa del ETL (media_index_runs) + promedio por etapa."""
    conn = _db()
    conn.row_factory = sqlite3.Row
    where, params = ("WHERE asset_id = ?", (asset_id,)) if asset_id else ("", ())
    rows = conn.execute(f"SELECT asset_id, step, status, seconds, finished_at FROM media_index_runs "
                        f"{where} ORDER BY id DESC LIMIT ?", (*params, last)).fetchall()
    avg = conn.execute("SELECT step, COUNT(*) n, ROUND(AVG(seconds), 2) avg_s, ROUND(MAX(seconds), 2) max_s "
                       "FROM media_index_runs WHERE status = 'ok' GROUP BY step").fetchall()
    _print({"by_step": [dict(r) for r in avg], "recent": [dict(r) for r in rows]})


@app.command()
def fetch(asset_id: int, start_ms: int, end_ms: int,
          measure: bool = typer.Option(False, help="Medir bytes bajados (proxy local)"),
          exact: Path = typer.Option(None, help="Además, cortar exacto al frame a este .mp4")):
    """Baja SOLO la región [start_ms, end_ms] del master (stream copy + caché)."""
    from apps.media import fetch as mf
    from apps.media.schema import get_asset
    asset = get_asset(_db(), asset_id)
    if asset is None:
        raise typer.BadParameter(f"asset {asset_id} no existe")
    mezz = mf.extract_segment(asset["master_uri"], start_ms, end_ms, measure=measure)
    out = {**mezz.__dict__, "offset_ms": mezz.offset_ms}
    if mezz.bytes_transferred and asset["size_bytes"]:
        out["fraction_of_file"] = round(mezz.bytes_transferred / asset["size_bytes"], 5)
    if exact:
        out["exact_clip"] = str(mf.cut_exact(mezz, start_ms, end_ms, exact))
    _print(out)


@app.command()
def storage():
    """Uso de almacenamiento por capa (crudo, segmentos, análisis, trabajo, DB)."""
    from apps.media import storage as st
    _print(st.usage(_db()))


@app.command()
def gc(max_gb: float = typer.Option(None, help="Tope de la caché de segmentos (default MEDIA_CACHE_MAX_GB)"),
       analysis: bool = typer.Option(True, "--analysis/--no-analysis",
                                     help="Borrar proxy+wav de assets ya transcritos y con momentos"),
       force: bool = typer.Option(False, help="Limpiar análisis aunque falte transcripción/detección")):
    """Libera espacio: segmentos menos usados por encima del tope + análisis ya aprovechado."""
    from apps.media import storage as st
    conn = _db()
    out = {"segments": st.prune_segments(None if max_gb is None else int(max_gb * 1024 ** 3))}
    if analysis:
        ids = [r[0] for r in conn.execute("SELECT id FROM media_assets WHERE audio_path IS NOT NULL "
                                          "OR proxy_path IS NOT NULL")]
        out["analysis"] = [st.cleanup_analysis(conn, i, force=force) for i in ids]
    _print(out)
