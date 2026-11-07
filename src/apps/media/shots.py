"""Detección de cortes de plano sobre el proxy de análisis.

Backends (clásicos e interpretables, sin redes neuronales):
  - "pyscenedetect": AdaptiveDetector (BSD-3); requiere scenedetect + opencv.
  - "scdet": filtro `scdet` de ffmpeg (diferencia de luminancia entre frames,
    umbral explícito). Sin dependencias de Python; es el fallback.
Los momentos se ajustan después a estos bordes para no cortar a mitad de plano.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from utils import ffmpeg as ff

log = logging.getLogger(__name__)

_SCDET_RE = re.compile(r"lavfi\.scd\.score:\s*([\d.]+),\s*lavfi\.scd\.time:\s*([\d.]+)")
MIN_SHOT_MS = 400   # flashes/cortes espurios más cortos se funden con el plano anterior


def cuts_to_shots(cuts_ms: list[int], duration_ms: int, *, min_shot_ms: int = MIN_SHOT_MS) -> list[tuple[int, int]]:
    """Lista de tiempos de corte → lista de planos [(start, end)] contiguos."""
    bounds = [0]
    for c in sorted(set(int(c) for c in cuts_ms)):
        if 0 < c < duration_ms and c - bounds[-1] >= min_shot_ms:
            bounds.append(c)
    if duration_ms - bounds[-1] < min_shot_ms and len(bounds) > 1:
        bounds.pop()                     # último plano demasiado corto: se funde
    bounds.append(duration_ms)
    return list(zip(bounds[:-1], bounds[1:], strict=True))


def parse_scdet(stderr: str, offset_ms: int = 0, min_score: float = 0.0) -> list[int]:
    return [int(round(float(t) * 1000)) + offset_ms
            for score, t in _SCDET_RE.findall(stderr) if float(score) >= min_score]


def detect_scdet(video: str | Path, *, threshold: float = 10.0) -> list[int]:
    """Cortes con ffmpeg scdet (a 320 px de ancho: rápido y suficiente)."""
    info = ff.summarize_probe(ff.probe(video))
    proc = ff.run(["ffmpeg", "-hide_banner", "-nostdin", "-i", str(video), "-an", "-sn",
                   "-vf", f"scale=320:-2,scdet=threshold={threshold}", "-f", "null", "-"],
                  timeout=4 * 3600)
    # scdet reporta tiempos desde 0; se suma el start_time del archivo.
    return parse_scdet(proc.stderr, offset_ms=info["start_ms"])


def detect_pyscenedetect(video: str | Path) -> list[int]:
    from scenedetect import AdaptiveDetector, detect  # type: ignore
    scenes = detect(str(video), AdaptiveDetector(), show_progress=False)
    return [int(round(start.get_seconds() * 1000)) for start, _end in scenes[1:]]


def detect_shots(video: str | Path, duration_ms: int, *, backend: str = "auto") -> tuple[list[tuple[int, int]], str]:
    """Devuelve (planos, backend_usado)."""
    if backend in ("auto", "pyscenedetect"):
        try:
            return cuts_to_shots(detect_pyscenedetect(video), duration_ms), "pyscenedetect"
        except ImportError:
            if backend == "pyscenedetect":
                raise
            log.info("scenedetect no instalado; usando ffmpeg scdet")
    return cuts_to_shots(detect_scdet(video), duration_ms), "scdet"
