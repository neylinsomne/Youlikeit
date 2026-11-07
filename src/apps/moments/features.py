"""Señales interpretables por momento + importancia lineal.

Cada señal se normaliza a 0-1 y se pondera con data/vocab/importance_weights.json.
Se guarda la contribución de cada una (peso × valor) para poder explicar por
qué un momento quedó arriba, y para que analytics ajuste los pesos después.

Audio: envolvente de volumen en dB cada 100 ms del wav de análisis, expresada
en percentiles DE CADA PELÍCULA (cada mezcla es distinta; ver AudioProfile).
"""
from __future__ import annotations

import bisect
import functools
import json
import math
import re
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from apps.moments.vocab import VOCAB_DIR

HOP_MS = 100


@functools.lru_cache(maxsize=1)
def load_weights() -> tuple[dict[str, float], float]:
    cfg = json.loads((VOCAB_DIR / "importance_weights.json").read_text(encoding="utf-8"))
    return cfg["weights"], float(cfg.get("llm_blend", 0.4))


def loudness_envelope(wav_path: str | Path, *, hop_ms: int = HOP_MS) -> np.ndarray:
    """dB RMS por ventana de hop_ms, leyendo el wav por bloques (no carga 180 MB en float)."""
    with wave.open(str(wav_path), "rb") as w:
        sr, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        if width != 2:
            raise ValueError("se espera PCM16")
        hop = sr * hop_ms // 1000
        out = []
        while True:
            raw = w.readframes(hop * 600)                 # ~1 min por lectura
            if not raw:
                break
            x = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
            if ch > 1:
                x = x.reshape(-1, ch).mean(axis=1)
            n = len(x) // hop
            if n:
                blocks = x[: n * hop].reshape(n, hop)
                rms = np.sqrt((blocks ** 2).mean(axis=1)) / 32768.0
                out.append(20 * np.log10(rms + 1e-6))
    return np.concatenate(out) if out else np.zeros(0, dtype=np.float32)


def onset_strength(env: np.ndarray, *, lookback: int = 30) -> np.ndarray:
    """Subida de volumen (dB) respecto de la media de los 3 s anteriores (sustos, golpes)."""
    if env.size == 0:
        return env
    c = np.cumsum(np.concatenate([[0.0], env]))
    idx = np.arange(env.size)
    lo = np.maximum(0, idx - lookback)
    prev_mean = (c[idx] - c[lo]) / np.maximum(1, idx - lo)
    prev_mean[0] = env[0]
    return env - prev_mean


@dataclass
class AudioProfile:
    """Envolvente + estadísticos POR PELÍCULA.

    Medido en cine real (NOTLD, Horror Express): MAD ~ 9 dB por los silencios,
    así que el grito más fuerte apenas llega a z ~ 1.8: un umbral global
    absoluto no sirve. Todo se expresa relativo a la propia película:
    percentil de volumen y subida relativa a su p99.9 de subidas.
    """
    env: np.ndarray
    onset: np.ndarray
    sorted_env: np.ndarray
    onset_ref: float                       # p99.9 de las subidas de esta película (dB)

    @classmethod
    def from_env(cls, env: np.ndarray) -> AudioProfile:
        onset = onset_strength(env)
        ref = float(np.percentile(onset, 99.9)) if onset.size else 1.0
        return cls(env=env, onset=onset, sorted_env=np.sort(env), onset_ref=max(ref, 6.0))

    @classmethod
    def from_wav(cls, wav_path: str | Path) -> AudioProfile:
        return cls.from_env(loudness_envelope(wav_path))

    @classmethod
    def from_npy(cls, path: str | Path) -> AudioProfile:
        return cls.from_env(np.load(path))

    def save(self, path: str | Path) -> Path:
        """Guarda solo la envolvente (~230 KB para 95 min): permite borrar el wav de 180 MB."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.save(path, self.env.astype(np.float32))
        return path

    def rank(self, db: float) -> float:
        """Fracción de la película más silenciosa que `db` (0-1)."""
        if self.sorted_env.size == 0:
            return 0.0
        return float(np.searchsorted(self.sorted_env, db, side="right")) / self.sorted_env.size


def energy_peaks(profile: AudioProfile, *, hop_ms: int = HOP_MS, loud_pct: float = 99.0,
                 onset_pct: float = 99.9, min_margin_db: float = 6.0, top_n: int = 40,
                 min_gap_ms: int = 20_000) -> list[int]:
    """Momentos entre el 1 % más fuerte o el 0.1 % de subidas más bruscas DE ESTA película.

    Además exige un margen absoluto (≥ min_margin_db sobre la mediana, o una
    subida ≥ min_margin_db): en una mezcla plana el "1 % más fuerte" existe
    igual y sería ruido. En cine real sobra (p99 ≈ mediana + 11 dB).
    Prioridad: subidas bruscas primero (sustos/golpes), luego volumen.
    Supresión de no-máximos: al menos min_gap_ms entre picos.
    """
    env, onset = profile.env, profile.onset
    if env.size == 0:
        return []
    loud_thr = max(float(np.percentile(env, loud_pct)), float(np.median(env)) + min_margin_db)
    onset_thr = max(float(np.percentile(onset, onset_pct)), min_margin_db)
    idx = np.flatnonzero((env >= loud_thr) | (onset >= onset_thr))
    prio = np.maximum(onset[idx] / max(onset_thr, 1e-6), (env[idx] - loud_thr) / 6.0 + 1.0)
    gap = min_gap_ms // hop_ms
    picked: list[int] = []
    for i in idx[np.argsort(-prio)]:
        if len(picked) >= top_n:
            break
        if all(abs(int(i) - q) >= gap for q in picked):
            picked.append(int(i))
    return sorted(q * hop_ms for q in picked)


def _clip01(x: float) -> float:
    return 0.0 if math.isnan(x) else max(0.0, min(1.0, x))


def window_signals(start_ms: int, end_ms: int, *, audio: AudioProfile | None,
                   shot_starts: list[int], text: str, words: int, position: float,
                   quote_score: float = 0.0, plot_score: float = 0.0, cue_hits: int = 0,
                   hop_ms: int = HOP_MS) -> dict[str, float]:
    dur_s = max(0.5, (end_ms - start_ms) / 1000)
    a, b = start_ms // hop_ms, max(start_ms // hop_ms + 1, end_ms // hop_ms)
    loud = onset_v = 0.0
    if audio is not None and audio.env.size:
        seg = audio.env[a:b]
        if seg.size:
            # Percentil del p90 de la ventana dentro de la película; solo cuenta la mitad alta.
            loud = _clip01((audio.rank(float(np.percentile(seg, 90))) - 0.5) / 0.5)
        oseg = audio.onset[a:b]
        if oseg.size:
            onset_v = _clip01(float(oseg.max()) / audio.onset_ref)       # p99.9 de la película -> 1
    cuts = bisect.bisect_left(shot_starts, end_ms) - bisect.bisect_right(shot_starts, start_ms)
    exclam = len(re.findall(r"[!¡]", text))
    return {
        "loudness": round(loud, 4),
        "sudden_onset": round(onset_v, 4),
        "shot_tempo": round(_clip01((cuts / dur_s) / 0.8), 4),           # 0.8 cortes/s = acción
        "speech_intensity": round(_clip01(0.6 * min(1, (words / dur_s) / 4) + 0.4 * min(1, exclam / 2)), 4),
        "quote_anchor": round(_clip01(quote_score), 4),
        "plot_anchor": round(_clip01(plot_score), 4),
        "climax_position": round(math.exp(-(((position - 0.85) / 0.12) ** 2)), 4),
        "trope_cues": round(_clip01(cue_hits / 3), 4),
    }


def importance(signals: dict[str, float], weights: dict[str, float] | None = None) -> tuple[float, dict[str, float]]:
    """Suma ponderada normalizada por la suma de pesos → (score 0-1, contribuciones)."""
    weights = weights or load_weights()[0]
    total_w = sum(weights.values()) or 1.0
    contrib = {k: round(weights.get(k, 0) * v / total_w, 4) for k, v in signals.items()}
    return round(sum(contrib.values()), 4), contrib
