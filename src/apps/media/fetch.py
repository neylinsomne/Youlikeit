"""Extracción de regiones: baja SOLO el segmento pedido de un master.

Dos pasos, una sola recodificación en todo el pipeline:

1. `extract_segment` (stream copy, sin recodificar):
     ffmpeg -ss <inicio-pad> -t <dur+2pad> -i <master> -c copy -copyts -f matroska
   ffmpeg salta por el índice del contenedor (moov / Cues) pidiendo por HTTP
   Range solo los bytes del tramo. Como `-c copy` arranca en el keyframe
   anterior, se guardan los timestamps ORIGINALES (-copyts + MKV) y se mide el
   inicio real → `Mezzanine.start_ms`. Resultado en caché por hash(uri, rango).

2. `cut_exact` (recodifica): corta al frame usando offset relativo al
   start_time del mezzanine. Verificado contra un frame de referencia del
   master (PSNR = inf). Esto reemplaza el doble desfase de ex11._cut_segment.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from apps.media import storage
from apps.media.models import Mezzanine, media_cache_dir
from apps.media.range_proxy import CountingRangeProxy
from utils import ffmpeg as ff

log = logging.getLogger(__name__)

DEFAULT_PAD_MS = 1500


def cache_key(uri: str, start_ms: int, end_ms: int, pad_ms: int) -> str:
    raw = f"{uri}|{int(start_ms)}|{int(end_ms)}|{int(pad_ms)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def build_extract_cmd(uri: str, pre_ms: int, dur_ms: int, out_path: str | Path) -> list[str]:
    """Comando de extracción por rango (stream copy, timestamps originales)."""
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y"]
    if ff.is_remote(uri):
        cmd += list(ff.HTTP_INPUT_FLAGS)
    cmd += [
        "-ss", ff.ms_to_ts(pre_ms), "-t", ff.ms_to_ts(dur_ms),   # -t de ENTRADA (con -copyts
        "-i", str(uri),                                          # el -t de salida no corta)
        "-map", "0:v:0", "-map", "0:a?", "-dn", "-sn",           # todas las pistas de audio
        "-c", "copy", "-copyts", "-f", "matroska", str(out_path),
    ]
    return cmd


def measure_bounds(path: str | Path) -> tuple[int, int]:
    """(start_ms, end_ms) reales del mezzanine, en la línea de tiempo del master.

    start = format.start_time (base de `-ss` relativo, ver cut_exact).
    end   = último pts de video + 1 frame.
    """
    info = ff.probe(path)
    start_ms = int(round(float(info.get("format", {}).get("start_time") or 0) * 1000))
    out = ff.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                  "-show_entries", "packet=pts_time", "-of", "csv=p=0", str(path)]).stdout
    pts = [float(x) for x in out.split() if x.strip() and x.strip() != "N/A"]
    if not pts:
        raise ff.FFmpegError(f"Mezzanine sin video: {path}")
    fps = ff.summarize_probe(info)["fps"] or 24.0
    end_ms = int(round((max(pts) + 1.0 / fps) * 1000))
    return start_ms, end_ms


def extract_segment(uri: str, start_ms: int, end_ms: int, *,
                    cache_dir: str | Path | None = None, pad_ms: int = DEFAULT_PAD_MS,
                    measure: bool = False, timeout: float = 600) -> Mezzanine:
    """Baja [start_ms, end_ms] (+ padding) del master y devuelve el Mezzanine."""
    if end_ms <= start_ms:
        raise ValueError(f"Rango inválido: {start_ms}..{end_ms}")
    cache_dir = Path(cache_dir) if cache_dir else media_cache_dir("segments")
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = cache_key(uri, start_ms, end_ms, pad_ms)
    out_path = cache_dir / f"{key}.mkv"
    meta_path = cache_dir / f"{key}.json"

    if out_path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        storage.touch(out_path)                  # LRU: usado recién
        return Mezzanine(**{**meta, "cached": True})

    pre_ms = max(0, start_ms - pad_ms)
    dur_ms = (end_ms - pre_ms) + pad_ms
    bytes_transferred = None

    for _attempt in range(2):
        if measure and ff.is_remote(uri):
            with CountingRangeProxy(uri) as proxy:
                ff.run(build_extract_cmd(proxy.url, pre_ms, dur_ms, out_path), timeout=timeout)
            bytes_transferred = proxy.upstream_bytes
            log.info("fetch %s..%s ms: %d bytes en %d pedidos", start_ms, end_ms,
                     bytes_transferred, len(proxy.requests))
        else:
            ff.run(build_extract_cmd(uri, pre_ms, dur_ms, out_path), timeout=timeout)
        real_start, real_end = measure_bounds(out_path)
        if real_start <= start_ms and real_end >= end_ms - 50:
            break
        # El keyframe quedó adentro del rango pedido (GOP largo): doble padding.
        log.warning("Mezzanine no cubre el rango (%s..%s vs %s..%s), reintento con más padding",
                    real_start, real_end, start_ms, end_ms)
        pre_ms = max(0, start_ms - pad_ms * 4)
        dur_ms = (end_ms - pre_ms) + pad_ms * 2
    else:
        raise ff.FFmpegError(
            f"No se pudo cubrir {start_ms}..{end_ms} ms (obtenido {real_start}..{real_end})")

    mezz = Mezzanine(path=str(out_path), start_ms=real_start, end_ms=real_end,
                     requested_start_ms=int(start_ms), requested_end_ms=int(end_ms),
                     bytes_transferred=bytes_transferred)
    meta = {k: v for k, v in mezz.__dict__.items() if k != "cached"}
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    storage.prune_segments(cache_dir=cache_dir)  # tope MEDIA_CACHE_MAX_GB (borra lo menos usado)
    return mezz


def build_cut_cmd(mezz: Mezzanine, start_ms: int, end_ms: int, out_path: str | Path,
                  *, vf: str | None = None, audio: bool = True) -> list[str]:
    """Corte exacto al frame desde el mezzanine (una sola recodificación)."""
    if start_ms < mezz.start_ms or end_ms > mezz.end_ms:
        raise ValueError(f"{start_ms}..{end_ms} fuera del mezzanine {mezz.start_ms}..{mezz.end_ms}")
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
           "-ss", ff.ms_to_ts(start_ms - mezz.start_ms), "-i", mezz.path,
           "-t", ff.ms_to_ts(end_ms - start_ms), "-map", "0:v:0"]
    if audio:
        cmd += ["-map", "0:a:0?", "-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-an"]
    if vf:
        cmd += ["-vf", vf]
    cmd += ff.video_encoder_args() + ["-movflags", "+faststart", str(out_path)]
    return cmd


def cut_exact(mezz: Mezzanine, start_ms: int, end_ms: int, out_path: str | Path, **kw) -> Path:
    ff.run(build_cut_cmd(mezz, start_ms, end_ms, out_path, **kw), timeout=600)
    return Path(out_path)
