"""Copias de análisis: proxy local liviano + audio 16 kHz + cortes de plano.

El proxy (p.ej. el derivado `_512kb.mp4` de IA, ~300-450 MB por película)
tiene la MISMA línea de tiempo que el master, así que todo tiempo detectado
sobre él (palabras, cortes de plano) vale para recortar el master por rango.

Medido sobre "Night of the Living Dead" (96 min, proxy 406 MB):
  - el cuello de botella es la RED: 1 conexión ≈ 1.4 MB/s, 6 conexiones ≈ 3.5 MB/s
    → `download_parallel` (segmentada, reanudable, estilo aria2);
  - decodificar el proxy a 240p tarda ~4 s → `single_pass` saca audio + cortes
    de plano en UNA lectura del archivo (antes eran 3 lecturas).
"""
from __future__ import annotations

import json
import logging
import shutil
import threading
import urllib.request
from pathlib import Path

from apps.media.models import media_cache_dir
from apps.media.shots import parse_scdet
from utils import ffmpeg as ff

log = logging.getLogger(__name__)

_CHUNK = 1024 * 1024
_UA = {"User-Agent": "youlikeit-media/1.0"}


# ── Descarga ────────────────────────────────────────────────────────


def download_resumable(url: str, dest: Path, *, timeout: float = 60) -> Path:
    """Descarga secuencial con reanudación (Range); idempotente si ya está completo."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    if dest.exists():
        return dest
    have = part.stat().st_size if part.exists() else 0
    headers = dict(_UA)
    if have:
        headers["Range"] = f"bytes={have}-"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(part, "ab" if have else "wb") as fh:
        if have and resp.status != 206:      # el servidor ignoró el Range: empezar de cero
            fh.seek(0)
            fh.truncate()
        shutil.copyfileobj(resp, fh, _CHUNK)
    part.replace(dest)
    return dest


def _head(url: str, timeout: float) -> tuple[str, int, bool]:
    """(url_final, tamaño, acepta_rangos) siguiendo redirects (archive.org → dnXXX)."""
    req = urllib.request.Request(url, method="HEAD", headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        size = int(resp.headers.get("Content-Length") or 0)
        ranges = "bytes" in (resp.headers.get("Accept-Ranges") or "").lower()
        return resp.geturl(), size, ranges


def plan_chunks(size: int, chunk_bytes: int) -> list[tuple[int, int]]:
    """[(start, end_inclusive)] que cubren [0, size)."""
    return [(s, min(s + chunk_bytes, size) - 1) for s in range(0, size, chunk_bytes)]


def download_parallel(url: str, dest: Path, *, connections: int = 6,
                      chunk_bytes: int = 8 * 1024 * 1024, timeout: float = 60,
                      retries: int = 3) -> Path:
    """Descarga segmentada con N conexiones y reanudación por trozo.

    Estado en `<dest>.parts.json` (trozos completos). Si el servidor no acepta
    rangos o no informa tamaño, cae a `download_resumable`.
    """
    dest = Path(dest)
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    final_url, size, ranges = _head(url, timeout)
    if not ranges or size <= 0 or connections <= 1:
        return download_resumable(final_url, dest, timeout=timeout)

    part = dest.with_suffix(dest.suffix + ".part")
    state_path = dest.with_suffix(dest.suffix + ".parts.json")
    chunks = plan_chunks(size, chunk_bytes)
    done: set[int] = set()
    if part.exists() and part.stat().st_size == size and state_path.exists():
        done = set(json.loads(state_path.read_text()).get("done", []))
    else:
        with open(part, "wb") as fh:
            fh.truncate(size)                     # prealoca: cada hilo escribe en su offset

    pending = [i for i in range(len(chunks)) if i not in done]
    lock = threading.Lock()
    errors: list[BaseException] = []

    def worker() -> None:
        with open(part, "r+b") as fh:
            while True:
                with lock:
                    if not pending or errors:
                        return
                    idx = pending.pop(0)
                start, end = chunks[idx]
                for attempt in range(retries):
                    try:
                        req = urllib.request.Request(final_url, headers={**_UA, "Range": f"bytes={start}-{end}"})
                        with urllib.request.urlopen(req, timeout=timeout) as resp:
                            if resp.status != 206:
                                raise OSError(f"sin 206 en trozo {idx} (status {resp.status})")
                            data = resp.read()
                        if len(data) != end - start + 1:
                            raise OSError(f"trozo {idx} incompleto: {len(data)} bytes")
                        fh.seek(start)
                        fh.write(data)
                        with lock:
                            done.add(idx)
                            state_path.write_text(json.dumps({"size": size, "done": sorted(done)}))
                        break
                    except OSError as e:
                        if attempt == retries - 1:
                            with lock:
                                errors.append(e)
                            return

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(min(connections, len(pending)))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if errors:
        raise OSError(f"Descarga incompleta ({len(done)}/{len(chunks)} trozos): {errors[0]}")
    part.replace(dest)
    state_path.unlink(missing_ok=True)
    return dest


def ensure_local_proxy(asset_id: int, proxy_uri: str, *, base_dir: Path | None = None,
                       connections: int = 6) -> Path:
    """Devuelve una ruta local al proxy (descarga en paralelo si es remoto)."""
    if not ff.is_remote(proxy_uri):
        p = Path(proxy_uri)
        if not p.exists():
            raise FileNotFoundError(proxy_uri)
        return p
    suffix = Path(proxy_uri.split("?")[0]).suffix or ".mp4"
    dest = Path(base_dir or media_cache_dir("analysis")) / str(asset_id) / f"proxy{suffix}"
    log.info("Descargando proxy de análisis (%d conexiones) → %s", connections, dest)
    return download_parallel(proxy_uri, dest, connections=connections)


# ── Análisis en una pasada ──────────────────────────────────────────


def build_audio_cmd(src: str | Path, out_wav: str | Path) -> list[str]:
    return ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
            "-i", str(src), "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000",
            "-c:a", "pcm_s16le", str(out_wav)]


def extract_audio(src: str | Path, out_wav: str | Path) -> Path:
    out_wav = Path(out_wav)
    if out_wav.exists() and out_wav.stat().st_size > 0:
        return out_wav
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    ff.run(build_audio_cmd(src, out_wav), timeout=3600)
    return out_wav


def build_single_pass_cmd(src: str | Path, out_wav: str | Path, *, scdet_threshold: float = 10.0) -> list[str]:
    """Una lectura del proxy → wav 16 kHz mono + log de cortes (scdet a 320 px)."""
    return ["ffmpeg", "-hide_banner", "-nostdin", "-nostats", "-y", "-i", str(src),
            "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out_wav),
            "-map", "0:v:0", "-an", "-sn", "-vf", f"scale=320:-2,scdet=threshold={scdet_threshold}",
            "-f", "null", "-"]


def single_pass(src: str | Path, out_wav: str | Path, *, scdet_threshold: float = 10.0) -> tuple[Path, list[int]]:
    """Audio para ASR + tiempos de corte (ms, línea de tiempo del proxy) en una pasada."""
    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    start_ms = ff.summarize_probe(ff.probe(src))["start_ms"]
    proc = ff.run(build_single_pass_cmd(src, out_wav, scdet_threshold=scdet_threshold), timeout=4 * 3600)
    return out_wav, parse_scdet(proc.stderr, offset_ms=start_ms)
