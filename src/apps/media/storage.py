"""Ciclo de vida del almacenamiento (qué se guarda, cuánto y por cuánto tiempo).

    CRUDO      MOVIES_DIR / proveedor     películas completas     permanente, SOLO LECTURA
    DB         shorts_pipeline.db         índice, momentos,       permanente (+ respaldo)
                                          recetas (EDL), IDs
    SEGMENTOS  media_cache/segments       clips por rango         caché LRU con tope (MEDIA_CACHE_MAX_GB)
    ANÁLISIS   media_cache/analysis/<id>  proxy + wav 16 kHz      se borran tras transcribir+detectar;
                                                                   queda loudness.npy (~200 KB)
    TRABAJO    media_cache/work/<job>     render del Short        se borra al terminar bien;
                                                                   se conserva si falla (depurar)

Lo valioso es la RECETA (qué momentos, en qué orden, con qué guion), no el MP4:
con DB + crudo cualquier Short se regenera. Por eso todo lo de media_cache es
desechable. Regla de seguridad: solo se borra dentro de media_cache, nunca el
crudo (aunque el "proxy" de un archivo local sea el propio crudo).
"""
from __future__ import annotations

import contextlib
import logging
import os
import shutil
import sqlite3
import uuid
from pathlib import Path

from apps.media.models import media_cache_dir

log = logging.getLogger(__name__)

DEFAULT_SEGMENTS_MAX_GB = 5.0


def segments_cap_bytes() -> int:
    return int(float(os.getenv("MEDIA_CACHE_MAX_GB", DEFAULT_SEGMENTS_MAX_GB)) * 1024 ** 3)


def keep_analysis_files() -> bool:
    return os.getenv("KEEP_ANALYSIS_FILES", "false").strip().lower() in {"1", "true", "yes", "on"}


def dir_size(path: Path) -> tuple[int, int]:
    """(bytes, archivos) bajo path."""
    total = count = 0
    if path.exists():
        for p in path.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
                count += 1
    return total, count


def _inside_cache(path: Path) -> bool:
    try:
        path.resolve().relative_to(media_cache_dir().resolve())
        return True
    except ValueError:
        return False


# ── segmentos: caché LRU ────────────────────────────────────────────


def touch(path: str | Path) -> None:
    """Marca un segmento como usado (LRU por mtime)."""
    with contextlib.suppress(OSError):
        os.utime(path, None)


def prune_segments(max_bytes: int | None = None, *, cache_dir: Path | None = None) -> dict:
    """Borra los segmentos menos usados hasta quedar bajo el tope."""
    cache_dir = Path(cache_dir) if cache_dir else media_cache_dir("segments")
    max_bytes = segments_cap_bytes() if max_bytes is None else max_bytes
    clips = sorted(cache_dir.glob("*.mkv"), key=lambda p: p.stat().st_mtime) if cache_dir.exists() else []
    total = sum(p.stat().st_size for p in clips)
    removed = freed = 0
    for clip in clips:
        if total <= max_bytes:
            break
        size = clip.stat().st_size
        clip.unlink(missing_ok=True)
        clip.with_suffix(".json").unlink(missing_ok=True)
        total -= size
        freed += size
        removed += 1
    if removed:
        log.info("Caché de segmentos: %d borrados, %.1f MB liberados", removed, freed / 1e6)
    return {"removed": removed, "freed_bytes": freed, "remaining_bytes": total}


# ── análisis: limpiar tras usar ─────────────────────────────────────


def envelope_path(asset_id: int) -> Path:
    return media_cache_dir("analysis", str(asset_id), "loudness.npy")


def cleanup_analysis(conn: sqlite3.Connection, asset_id: int, *, force: bool = False) -> dict:
    """Borra proxy + wav de un asset ya transcrito y con momentos detectados.

    Antes guarda la envolvente de volumen (lo único del wav que se sigue usando).
    Solo borra archivos dentro de media_cache: un proxy que es el crudo local
    no se toca.
    """
    row = conn.execute("SELECT proxy_path, audio_path, transcribed_at, shots_at FROM media_assets "
                       "WHERE id = ?", (asset_id,)).fetchone()
    if row is None:
        raise KeyError(f"asset {asset_id} no existe")
    proxy_path, audio_path, transcribed, shots = row
    detected = conn.execute("SELECT 1 FROM moments WHERE asset_id = ? LIMIT 1", (asset_id,)).fetchone() \
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'moments'").fetchone() else None
    if not force and not (transcribed and shots and detected):
        return {"asset_id": asset_id, "skipped": "falta transcripción, planos o detección de momentos"}

    if audio_path and Path(audio_path).exists() and not envelope_path(asset_id).exists():
        from apps.moments.features import AudioProfile        # import tardío: media no depende de moments
        AudioProfile.from_wav(audio_path).save(envelope_path(asset_id))

    freed, cleared = 0, {}
    for col, path in (("audio_path", audio_path), ("proxy_path", proxy_path)):
        if not path:
            continue
        p = Path(path)
        if p.exists() and _inside_cache(p):
            freed += p.stat().st_size
            p.unlink()
            cleared[col] = None
    if cleared:
        conn.execute(f"UPDATE media_assets SET {', '.join(f'{c} = NULL' for c in cleared)} WHERE id = ?",
                     (asset_id,))
        conn.commit()
    return {"asset_id": asset_id, "freed_bytes": freed, "cleared": sorted(cleared),
            "envelope": str(envelope_path(asset_id)) if envelope_path(asset_id).exists() else None}


# ── trabajo: carpeta efímera por render ─────────────────────────────


@contextlib.contextmanager
def work_dir(job: str | None = None, *, keep_on_error: bool = True):
    """Carpeta temporal en disco para un render. Se borra si todo sale bien.

    En disco y no en RAM a propósito: `-movflags +faststart` necesita un archivo
    con seek, y la subida debe poder reintentarse sin renderizar de nuevo.
    """
    path = media_cache_dir("work", job or uuid.uuid4().hex[:12])
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    except BaseException:
        if not keep_on_error:
            shutil.rmtree(path, ignore_errors=True)
        else:
            log.warning("Render fallido: se conserva %s para depurar", path)
        raise
    shutil.rmtree(path, ignore_errors=True)


# ── reporte ─────────────────────────────────────────────────────────


def usage(conn: sqlite3.Connection) -> dict:
    raw = conn.execute("SELECT COUNT(*), COALESCE(SUM(size_bytes), 0) FROM media_assets "
                       "WHERE provider = 'local'").fetchone()
    remote = conn.execute("SELECT COUNT(*), COALESCE(SUM(size_bytes), 0) FROM media_assets "
                          "WHERE provider != 'local'").fetchone()
    out = {"raw_local": {"assets": raw[0], "gb": round(raw[1] / 1024 ** 3, 2)},
           "raw_remote_not_downloaded": {"assets": remote[0], "gb": round(remote[1] / 1024 ** 3, 2)}}
    for name in ("segments", "analysis", "work"):
        size, files = dir_size(media_cache_dir(name))
        out[name] = {"files": files, "gb": round(size / 1024 ** 3, 3)}
    out["segments"]["cap_gb"] = round(segments_cap_bytes() / 1024 ** 3, 2)
    db = Path(os.getenv("DATA_DIR", "data")) / "shorts_pipeline.db"
    out["db_mb"] = round(db.stat().st_size / 1e6, 2) if db.exists() else 0
    return out
