"""Helpers de ffmpeg/ffprobe compartidos por los dominios media y supercut.

Diferencia clave con el código legacy (ex11): todo `subprocess` revisa el
código de retorno y levanta `FFmpegError` con la cola de stderr, en vez de
seguir en silencio con un archivo vacío o parcial.
"""
from __future__ import annotations

import functools
import json
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

# Flags de reconexión para entradas HTTP(S): IA/Jellyfin cortan conexiones largas.
HTTP_INPUT_FLAGS: tuple[str, ...] = (
    "-reconnect", "1",
    "-reconnect_on_network_error", "1",
    "-reconnect_delay_max", "10",
)


class FFmpegError(RuntimeError):
    """ffmpeg/ffprobe terminó con código != 0 o produjo una salida inválida."""


def is_remote(uri: str | Path) -> bool:
    return str(uri).lower().startswith(("http://", "https://"))


def require_binaries() -> None:
    missing = [b for b in ("ffmpeg", "ffprobe") if shutil.which(b) is None]
    if missing:
        raise FFmpegError(f"No se encontró en el PATH: {', '.join(missing)}")


def run(args: Sequence[str], *, timeout: float | None = None) -> subprocess.CompletedProcess:
    """Corre un comando (ffmpeg/ffprobe) y levanta FFmpegError si falla."""
    try:
        proc = subprocess.run(
            list(args), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise FFmpegError(f"Timeout ({timeout}s): {' '.join(map(str, args[:6]))} …") from e
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-12:])
        raise FFmpegError(f"{args[0]} exit={proc.returncode}: {tail}")
    return proc


def probe(uri: str | Path, *, timeout: float = 60) -> dict:
    """ffprobe -show_format -show_streams en JSON."""
    args = ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams"]
    if is_remote(uri):
        args += list(HTTP_INPUT_FLAGS)
    args.append(str(uri))
    return json.loads(run(args, timeout=timeout).stdout or "{}")


def summarize_probe(info: dict) -> dict:
    """Extrae duración, fps y resolución del primer stream de video."""
    fmt = info.get("format", {}) or {}
    video = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {}) or {}
    has_audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
    return {
        "duration_ms": int(float(fmt.get("duration") or 0) * 1000),
        "start_ms": int(float(fmt.get("start_time") or 0) * 1000),
        "size_bytes": int(fmt.get("size") or 0),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "fps": parse_rate(video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1"),
        "vcodec": video.get("codec_name"),
        "has_audio": has_audio,
    }


def parse_rate(rate: str) -> float:
    """'24000/1001' -> 23.976; tolera '0/0' y valores vacíos."""
    try:
        num, _, den = str(rate).partition("/")
        den_f = float(den or 1)
        return round(float(num) / den_f, 3) if den_f else 0.0
    except ValueError:
        return 0.0


def ms_to_ts(ms: int | float) -> str:
    """Milisegundos -> segundos con 3 decimales (formato que ffmpeg acepta)."""
    return f"{max(0.0, float(ms)) / 1000.0:.3f}"


@functools.lru_cache(maxsize=1)
def has_nvenc() -> bool:
    """¿Hay h264_nvenc? (portado de ex11._has_nvenc, cacheado)."""
    if shutil.which("ffmpeg") is None:
        return False
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "h264_nvenc" in out


def video_encoder_args(*, bitrate: str = "8M", cq: int = 21) -> list[str]:
    """Args de encoder: NVENC si existe (RTX 5060), si no libx264 (ex11._get_video_encoder)."""
    if has_nvenc():
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(cq),
                "-b:v", bitrate, "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", str(cq), "-pix_fmt", "yuv420p"]
