"""ETL del dominio media (idempotente por asset, con tiempos por etapa).

    register_candidate → works + media_assets

    prepare_asset  (etapa de RED/CPU)
      probe    ffprobe del master + HEAD Accept-Ranges
      proxy    descarga segmentada en paralelo (≈2.4× más rápida que 1 conexión)
      analyze  UNA pasada de ffmpeg sobre el proxy → wav 16 kHz + cortes (scdet)
               (con shot_backend=pyscenedetect: audio y planos por separado)
    asr_asset      (etapa de GPU o API)
      asr      faster-whisper local | Groq Whisper API → transcript_*

    index_many: pipeline de 2 etapas. Mientras la GPU/API transcribe el asset N,
    la etapa de red ya baja y analiza el N+1 (la red es el cuello de botella).

Cada etapa queda en `media_index_runs` (segundos, estado, detalle) y emite
progreso por WebSocket (utils.websocket_hub.notify, fire-and-forget).
"""
from __future__ import annotations

import logging
import queue
import sqlite3
import threading
import time
import urllib.request
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from pathlib import Path

from apps.media import analysis, schema, shots, transcribe
from apps.media.models import MediaCandidate, media_cache_dir
from utils import ffmpeg as ff
from utils.websocket_hub import notify

log = logging.getLogger(__name__)
SOURCE = "media.index"
STEPS = ("probe", "proxy", "audio", "shots", "asr")


def register_candidate(conn: sqlite3.Connection, cand: MediaCandidate, *,
                       work_title: str | None = None, work_year: int | None = None) -> int:
    """Crea/actualiza la obra y el asset. Devuelve asset_id."""
    kind = "series" if cand.kind == "episode" else "movie"
    work_id = schema.upsert_work(conn, title=work_title or cand.title,
                                 year=work_year if work_year is not None else cand.year, kind=kind)
    return schema.upsert_asset(conn, work_id, cand)


def check_accept_ranges(uri: str, timeout: float = 20) -> bool:
    if not ff.is_remote(uri):
        return True
    req = urllib.request.Request(uri, method="HEAD", headers={"User-Agent": "youlikeit-media/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return "bytes" in (resp.headers.get("Accept-Ranges") or "").lower()


@contextmanager
def _stage(conn: sqlite3.Connection, asset_id: int, step: str, report: dict):
    """Mide la etapa, la registra en media_index_runs y notifica por WebSocket."""
    t0 = time.perf_counter()
    detail: dict = {}
    try:
        yield detail
    except Exception as e:
        schema.log_step(conn, asset_id, step, "error", time.perf_counter() - t0,
                        {"error": f"{type(e).__name__}: {e}"[:500]})
        notify(SOURCE, "error", {"asset_id": asset_id, "step": step, "error": str(e)[:300]})
        raise
    secs = time.perf_counter() - t0
    schema.log_step(conn, asset_id, step, "ok", secs, detail)
    report.setdefault("seconds", {})[step] = round(secs, 2)
    if detail:
        report[step] = detail
    notify(SOURCE, "load" if step == "asr" else "transform",
           {"asset_id": asset_id, "step": step, "seconds": round(secs, 2), **detail})


def prepare_asset(conn: sqlite3.Connection, asset_id: int, *, steps: Iterable[str] = STEPS,
                  force: bool = False, shot_backend: str = "auto", connections: int = 6,
                  work_dir: Path | None = None, report: dict | None = None) -> dict:
    """Etapa de red/CPU: probe → proxy → audio + planos. No toca la GPU."""
    steps = set(steps)
    work_dir = Path(work_dir) if work_dir else media_cache_dir("analysis")
    report = report if report is not None else {"asset_id": asset_id}
    asset = schema.get_asset(conn, asset_id)
    if asset is None:
        raise KeyError(f"asset {asset_id} no existe")
    report["title"] = asset["work_title"]
    notify(SOURCE, "extract", {"asset_id": asset_id, "title": asset["work_title"], "step": "start"})

    if "probe" in steps and (force or not asset["fps"]):
        with _stage(conn, asset_id, "probe", report) as d:
            info = ff.summarize_probe(ff.probe(asset["master_uri"]))
            ranges = check_accept_ranges(asset["master_uri"])
            schema.update_asset(conn, asset_id, duration_ms=info["duration_ms"], width=info["width"],
                                height=info["height"], fps=info["fps"], accept_ranges=int(ranges),
                                **({"size_bytes": info["size_bytes"]} if info["size_bytes"] else {}))
            d.update({**info, "accept_ranges": ranges})
            if not ranges:
                log.warning("El master NO soporta HTTP Range: cada clip bajaría desde el inicio")
        asset = schema.get_asset(conn, asset_id)

    need_audio = "audio" in steps and (force or not _exists(asset["audio_path"]))
    need_shots = "shots" in steps and (force or not asset["shots_at"])
    need_proxy = need_audio or need_shots or ("proxy" in steps and (force or not _exists(asset["proxy_path"])))

    proxy_path = asset["proxy_path"]
    if need_proxy and (force or not _exists(proxy_path)):
        with _stage(conn, asset_id, "proxy", report) as d:
            proxy_path = str(analysis.ensure_local_proxy(
                asset_id, asset["proxy_uri"] or asset["master_uri"], base_dir=work_dir,
                connections=connections))
            schema.update_asset(conn, asset_id, proxy_path=proxy_path)
            d["path"] = proxy_path
    report["proxy_path"] = proxy_path

    if need_audio or need_shots:
        wav = work_dir / str(asset_id) / "audio16k.wav"
        duration_ms = asset["duration_ms"] or ff.summarize_probe(ff.probe(proxy_path))["duration_ms"]
        use_single_pass = shot_backend == "scdet" or (shot_backend == "auto" and not _has_scenedetect())
        with _stage(conn, asset_id, "analyze", report) as d:
            if use_single_pass:
                wav, cuts = analysis.single_pass(proxy_path, wav)
                shot_list, backend = shots.cuts_to_shots(cuts, duration_ms), "scdet"
            else:
                if need_audio:
                    wav = analysis.extract_audio(proxy_path, wav)
                shot_list, backend = shots.detect_shots(proxy_path, duration_ms, backend=shot_backend)
            schema.update_asset(conn, asset_id, audio_path=str(wav))
            if need_shots or use_single_pass:
                d["shots"] = schema.save_shots(conn, asset_id, shot_list, backend)
                d["shot_backend"] = backend
            d["single_pass"] = use_single_pass
    return report


def asr_asset(conn: sqlite3.Connection, asset_id: int, *, force: bool = False,
              backend: str | None = None, model: str = transcribe.DEFAULT_MODEL,
              language: str | None = None, report: dict | None = None) -> dict:
    """Etapa de GPU/API: transcripción con tiempos por palabra."""
    report = report if report is not None else {"asset_id": asset_id}
    asset = schema.get_asset(conn, asset_id)
    if asset["transcribed_at"] and not force:
        return report
    if not _exists(asset["audio_path"]):
        raise FileNotFoundError(f"asset {asset_id}: falta el audio (corre prepare_asset primero)")
    used = transcribe.resolve_backend(backend)
    with _stage(conn, asset_id, "asr", report) as d:
        segments, lang = transcribe.transcribe(asset["audio_path"], backend=used, model_size=model,
                                               language=language, duration_ms=asset["duration_ms"])
        n_seg, n_words = schema.save_transcript(conn, asset_id, segments)
        d.update({"segments": n_seg, "words": n_words, "lang": lang, "backend": used})
    return report


def index_asset(conn: sqlite3.Connection, asset_id: int, *, steps: tuple[str, ...] = STEPS,
                force: bool = False, asr_model: str = transcribe.DEFAULT_MODEL,
                asr_backend: str | None = None, language: str | None = None,
                shot_backend: str = "auto", connections: int = 6,
                work_dir: Path | None = None) -> dict:
    """prepare + asr para un asset (secuencial)."""
    report: dict = {"asset_id": asset_id}
    prepare_asset(conn, asset_id, steps=steps, force=force, shot_backend=shot_backend,
                  connections=connections, work_dir=work_dir, report=report)
    if "asr" in steps:
        asr_asset(conn, asset_id, force=force, backend=asr_backend, model=asr_model,
                  language=language, report=report)
    notify(SOURCE, "complete", report)
    return report


def index_many(conn_factory: Callable[[], sqlite3.Connection], asset_ids: list[int], *,
               force: bool = False, asr_backend: str | None = None,
               asr_model: str = transcribe.DEFAULT_MODEL, language: str | None = None,
               shot_backend: str = "auto", connections: int = 6, prefetch: int = 1,
               work_dir: Path | None = None) -> list[dict]:
    """Pipeline de 2 etapas: [red/CPU] prepare → cola → [GPU/API] asr.

    `prefetch` = cuántos assets puede adelantar la etapa de red mientras la GPU
    trabaja (acota el disco usado por proxies pendientes). Cada hilo usa su
    propia conexión SQLite (conn_factory).
    """
    handoff: queue.Queue = queue.Queue(maxsize=max(1, prefetch))
    reports: dict[int, dict] = {aid: {"asset_id": aid} for aid in asset_ids}
    _DONE = object()

    def producer() -> None:
        conn = conn_factory()
        try:
            for aid in asset_ids:
                try:
                    prepare_asset(conn, aid, force=force, shot_backend=shot_backend,
                                  connections=connections, work_dir=work_dir, report=reports[aid])
                    handoff.put(aid)
                except Exception as e:  # noqa: BLE001 — un asset roto no frena el lote
                    reports[aid]["error"] = f"prepare: {type(e).__name__}: {e}"
                    log.exception("prepare falló para asset %s", aid)
        finally:
            handoff.put(_DONE)
            conn.close()

    t = threading.Thread(target=producer, name="media-prepare", daemon=True)
    t.start()
    conn = conn_factory()
    try:
        while (aid := handoff.get()) is not _DONE:
            try:
                asr_asset(conn, aid, force=force, backend=asr_backend, model=asr_model,
                          language=language, report=reports[aid])
                notify(SOURCE, "complete", reports[aid])
            except Exception as e:  # noqa: BLE001
                reports[aid]["error"] = f"asr: {type(e).__name__}: {e}"
                log.exception("asr falló para asset %s", aid)
    finally:
        t.join()
        conn.close()
    return [reports[a] for a in asset_ids]


def _exists(path: str | None) -> bool:
    return bool(path) and Path(path).exists()


def _has_scenedetect() -> bool:
    try:
        import scenedetect  # type: ignore  # noqa: F401
        return True
    except ImportError:
        return False
