"""Candidatos de momento: bloques de diálogo ajustados a cortes de plano.

Reglas (clásicas, explicables):
  1. Segmentos de transcripción separados por < GAP_MS se funden en un bloque.
  2. Cada bloque se extiende hasta los bordes de sus planos SI eso agrega poco
     (≤ SNAP_SLACK_MS); si no, se corta en el borde de la palabra (+ margen).
     Nunca se corta a mitad de palabra ni a mitad de plano cuando se puede evitar.
  3. Duración final entre MIN_MS y MAX_MS: los cortos crecen por planos
     vecinos; los largos se parten en finales de frase.
  4. Picos de energía SIN diálogo (gritos, golpes, música que sube) también
     generan candidatos: muchos momentos de terror o acción no tienen texto.
"""
from __future__ import annotations

import bisect
import re

GAP_MS = 1200
SNAP_SLACK_MS = 1500
WORD_PAD_MS = 250
MIN_MS = 4000
MAX_MS = 15000
_SENTENCE_END = re.compile(r"[.!?…]['\"]?$")


def _shot_at(shot_starts: list[int], shots: list[tuple[int, int]], t: int) -> int:
    i = bisect.bisect_right(shot_starts, t) - 1
    return max(0, min(i, len(shots) - 1))


def dialogue_blocks(segments: list[dict], *, gap_ms: int = GAP_MS) -> list[dict]:
    blocks: list[dict] = []
    for seg in sorted(segments, key=lambda s: s["start_ms"]):
        if blocks and seg["start_ms"] - blocks[-1]["end_ms"] < gap_ms:
            b = blocks[-1]
            b["end_ms"] = max(b["end_ms"], seg["end_ms"])
            b["segments"].append(seg)
        else:
            blocks.append({"start_ms": seg["start_ms"], "end_ms": seg["end_ms"], "segments": [seg]})
    return blocks


def _split_long(block: dict, max_ms: int) -> list[dict]:
    """Parte un bloque largo en finales de frase (segmentos que terminan en . ! ?)."""
    if block["end_ms"] - block["start_ms"] <= max_ms:
        return [block]
    parts, cur = [], None
    for seg in block["segments"]:
        if cur is None:
            cur = {"start_ms": seg["start_ms"], "end_ms": seg["end_ms"], "segments": [seg]}
        elif seg["end_ms"] - cur["start_ms"] > max_ms:
            parts.append(cur)
            cur = {"start_ms": seg["start_ms"], "end_ms": seg["end_ms"], "segments": [seg]}
        else:
            cur["end_ms"] = seg["end_ms"]
            cur["segments"].append(seg)
            if _SENTENCE_END.search(seg["text"].strip()) and cur["end_ms"] - cur["start_ms"] >= max_ms * 0.6:
                parts.append(cur)
                cur = None
    if cur:
        parts.append(cur)
    return parts


def snap_window(start_ms: int, end_ms: int, shots: list[tuple[int, int]], duration_ms: int, *,
                min_ms: int = MIN_MS, max_ms: int = MAX_MS) -> tuple[int, int, int, int]:
    """Ajusta [start, end] a planos. Devuelve (start, end, shot_in, shot_out)."""
    if not shots:
        s, e = max(0, start_ms - WORD_PAD_MS), min(duration_ms, end_ms + WORD_PAD_MS)
        return s, e, -1, -1
    starts = [a for a, _ in shots]
    i, j = _shot_at(starts, shots, start_ms), _shot_at(starts, shots, max(start_ms, end_ms - 1))
    s = shots[i][0] if start_ms - shots[i][0] <= SNAP_SLACK_MS else max(0, start_ms - WORD_PAD_MS)
    e = shots[j][1] if shots[j][1] - end_ms <= SNAP_SLACK_MS else min(duration_ms, end_ms + WORD_PAD_MS)
    # Crecer por planos vecinos hasta el mínimo (alterna adelante/atrás).
    forward = True
    while e - s < min_ms and (i > 0 or j < len(shots) - 1):
        if (forward and j < len(shots) - 1) or i == 0:
            j += 1
            e = shots[j][1]
        else:
            i -= 1
            s = shots[i][0]
        forward = not forward
    if e - s < min_ms:                       # obra muy corta / sin planos suficientes
        e = min(duration_ms, s + min_ms)
    if e - s > max_ms:                       # un plano enorme: recortar alrededor del diálogo
        center = (start_ms + end_ms) // 2
        s = max(0, min(start_ms, center - max_ms // 2))
        e = min(duration_ms, s + max_ms)
    return int(s), int(e), i, j


def candidate_windows(segments: list[dict], shots: list[tuple[int, int]], duration_ms: int, *,
                      energy_peaks_ms: list[int] | None = None) -> list[dict]:
    """Ventanas candidatas (dicts con start/end/shot_in/shot_out/text/position/kind)."""
    out: list[dict] = []
    for block in dialogue_blocks(segments):
        for part in _split_long(block, MAX_MS):
            s, e, si, so = snap_window(part["start_ms"], part["end_ms"], shots, duration_ms)
            text = " ".join(seg["text"].strip() for seg in part["segments"])
            out.append({"start_ms": s, "end_ms": e, "shot_in": si, "shot_out": so, "text": text,
                        "kind": "dialogue"})
    spoken = [(c["start_ms"], c["end_ms"]) for c in out]
    for peak in energy_peaks_ms or []:
        if any(a <= peak <= b for a, b in spoken):
            continue
        s, e, si, so = snap_window(peak - 1500, peak + 1500, shots, duration_ms)
        out.append({"start_ms": s, "end_ms": e, "shot_in": si, "shot_out": so, "text": "",
                    "kind": "energy_peak"})
    out = dedupe(out)
    for c in out:
        c["position"] = round(((c["start_ms"] + c["end_ms"]) / 2) / max(1, duration_ms), 4)
    return out


def iou(a: tuple[int, int], b: tuple[int, int]) -> float:
    inter = max(0, min(a[1], b[1]) - max(a[0], b[0]))
    union = max(a[1], b[1]) - min(a[0], b[0])
    return inter / union if union else 0.0


def dedupe(cands: list[dict], *, threshold: float = 0.6) -> list[dict]:
    """Quita ventanas que se solapan > threshold (se queda la de más texto)."""
    kept: list[dict] = []
    for c in sorted(cands, key=lambda c: (-len(c["text"]), c["start_ms"])):
        if all(iou((c["start_ms"], c["end_ms"]), (k["start_ms"], k["end_ms"])) <= threshold for k in kept):
            kept.append(c)
    return sorted(kept, key=lambda c: c["start_ms"])
