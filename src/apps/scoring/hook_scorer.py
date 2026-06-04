"""
Hook Scorer — Quality gate post-render para los primeros segundos del video.

Inspirado en el patrón de AutoClip (zhouxiaoka/autoclip): ellos puntúan
candidatos de highlight ANTES de cortar; nosotros puntuamos el hook DESPUÉS
de generar. Mismo loop conceptual: extraer features → scorear → bloquear si
no pasa umbral → log para A/B.

Componentes del score (todos en [0, 1]):
  1. audio_energy_score: pico RMS en [0, 0.5s] (sorprende al oído)
  2. cps_score: cuts efectivos en [0, 1.5s] vs hook_cps_for_video_type
  3. accent_word_score: presencia del accent word en el primer subtítulo
  4. llm_score (opcional): puntuación 1-10 del LLM sobre el frame inicial
                           y el texto del hook → normalizado a [0, 1]

Overall = media ponderada. Default weights priorizan audio_energy + CPS.

API pública:
    from apps.scoring.hook_scorer import score_hook, HookScore, MIN_HOOK_SCORE

    score = score_hook(
        video_path="outputs/.../FINAL_NARRATION.mp4",
        vtype="narration",
        hook_text="¿Qué pasaría si Berserk fuera realidad?",
        accent_word="Berserk",
        edl=director_edl,         # opcional, mejora CPS measurement
        use_llm=False,
    )
    if score.overall < MIN_HOOK_SCORE:
        log.warning("Hook reprobado: %s", score)

Persistencia: usa `persist_hook_score(conn, video_path, score)` para
guardar en tabla `hook_scores`.

Mejoras futuras:
  - [ ] Reemplazar pico RMS por loudness LUFS (más alineado con percepción).
  - [ ] Detectar "spike de novedad" (delta espectral) en lugar de solo RMS.
  - [ ] Embedding del thumbnail con CLIP para benchmark cross-video.
  - [ ] Calibrar MIN_HOOK_SCORE desde retention real (cuando tengamos N≥30 videos).
  - [ ] LLM scoring con prompt few-shot calibrado con outcomes (bandit).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sqlite3
import struct
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.config import Settings

log = logging.getLogger(__name__)


# ── Configuración ────────────────────────────────────────────────────


MIN_HOOK_SCORE: float = 0.55
"""Umbral por defecto para considerar un hook 'publicable'.

Calibración inicial conservadora. Recalibrar cuando tengamos retention real
en al menos 30 videos por persona × vtype.
"""


SCORE_WEIGHTS: dict[str, float] = {
    "audio_energy": 0.30,
    "cps":          0.30,
    "accent_word":  0.20,
    "llm":          0.20,    # se redistribuye si llm_score is None
}


# ── Modelo de score ──────────────────────────────────────────────────


@dataclass
class HookScore:
    """Resultado del scoring. Todos los sub-scores en [0, 1]."""
    audio_energy_score: float = 0.0
    cps_score: float = 0.0
    accent_word_score: float = 0.0
    llm_score: float | None = None
    overall: float = 0.0
    # Métricas crudas para debug / dashboard
    raw_rms_peak: float = 0.0
    raw_cps_observed: float = 0.0
    raw_cps_target: float = 0.0
    raw_first_sub_text: str = ""
    raw_llm_reasoning: str = ""
    notes: list[str] = field(default_factory=list)

    def passes(self, min_score: float = MIN_HOOK_SCORE) -> bool:
        return self.overall >= min_score

    def to_dict(self) -> dict:
        return asdict(self)


# ── Extracción de features ───────────────────────────────────────────


def _ffprobe_duration(video_path: str) -> float:
    """Duración total en segundos. 0 si falla."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True, timeout=20,
        )
        return float(r.stdout.strip() or 0)
    except Exception as e:
        log.warning("ffprobe duration failed: %s", e)
        return 0.0


def _extract_rms_peak_first_window(video_path: str, window_s: float = 0.5) -> float:
    """Lee la primera ventana de audio y devuelve pico RMS normalizado [0,1].

    Pipeline: ffmpeg → PCM s16le mono 16kHz → RMS por chunk de 100ms → max.
    No requiere librosa.

    TODO(mlops): cambiar a LUFS (loudness perceptual) usando ffmpeg
    `loudnorm` filter o pyloudnorm cuando justifique la dep extra.
    """
    if not shutil.which("ffmpeg"):
        log.warning("ffmpeg no encontrado — audio_energy_score = 0")
        return 0.0

    try:
        # Extrae primera ventana como PCM raw, sin escribir archivo intermedio.
        proc = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", "0", "-t", str(window_s),
             "-i", video_path,
             "-ac", "1", "-ar", "16000",
             "-f", "s16le", "-"],
            capture_output=True, timeout=30,
        )
        raw = proc.stdout
        if not raw:
            return 0.0

        n_samples = len(raw) // 2
        if n_samples == 0:
            return 0.0
        samples = struct.unpack(f"<{n_samples}h", raw)

        # RMS por chunk de 100ms (1600 samples a 16kHz)
        chunk = 1600
        peak_rms = 0.0
        for i in range(0, n_samples, chunk):
            block = samples[i:i + chunk]
            if not block:
                continue
            sq_sum = sum(s * s for s in block)
            rms = (sq_sum / len(block)) ** 0.5
            # Normalizar contra max int16 (32768)
            rms_norm = rms / 32768.0
            if rms_norm > peak_rms:
                peak_rms = rms_norm
        return min(1.0, peak_rms)
    except Exception as e:
        log.warning("RMS extraction failed: %s", e)
        return 0.0


def _count_cuts_in_window(edl: list, window_s: float = 1.5) -> int:
    """Cuenta cuántas decisiones de edición ocurren dentro de la ventana.

    Si no hay EDL (vista externa, solo video) cae a fallback con detección
    de cortes por ffmpeg select. Por ahora solo soportamos vista interna.
    """
    if not edl:
        return 0
    n = 0
    cum = 0.0
    for d in edl:
        # d puede ser EditDecision (con .duration_s) o dict
        dur = getattr(d, "duration_s", None)
        if dur is None and isinstance(d, dict):
            dur = d.get("duration_s")
        if dur is None:
            continue
        if cum >= window_s:
            break
        n += 1
        cum += float(dur)
    return n


def _detect_cuts_via_ffmpeg(video_path: str, window_s: float = 1.5,
                             threshold: float = 0.3) -> int:
    """Fallback cuando no hay EDL: detecta scene cuts dentro de la ventana.

    Usa filtro `select='gt(scene,T)'`. Threshold 0.3 = cambios visuales
    moderados (zoom no cuenta, hard cut sí).

    NOTE: es aproximado — ken burns suave puede no contar. Mejor usar EDL
    cuando esté disponible.
    """
    if not shutil.which("ffmpeg"):
        return 0
    try:
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-t", str(window_s), "-i", video_path,
             "-vf", f"select='gt(scene,{threshold})',showinfo",
             "-an", "-f", "null", "-"],
            capture_output=True, text=True, timeout=30,
        )
        # showinfo emite una línea por frame seleccionado en stderr
        return r.stderr.count("pts_time:")
    except Exception as e:
        log.warning("ffmpeg cut detection failed: %s", e)
        return 0


# ── LLM scoring (opcional) ──────────────────────────────────────────


_LLM_PROMPT = """Tarea: puntuar de 1 a 10 qué tan enganchador es el inicio
de un short de video de 3 segundos. Devolver SOLO un número entero seguido
de una frase de razón (máx 15 palabras).

Persona/voz: {vtype}
Texto del hook: "{hook_text}"
Palabra accent (resalte visual): {accent_word}
Audio RMS peak primer 0.5s: {audio_energy:.3f}
Cuts observados en 1.5s: {cps_observed:.1f} (target: {cps_target:.1f})

Formato de respuesta: "SCORE: <1-10>. RAZÓN: <frase>"
"""


def _llm_score_hook(llm, vtype: str, hook_text: str, accent_word: str | None,
                     audio_energy: float, cps_observed: float,
                     cps_target: float) -> tuple[float | None, str]:
    """Devuelve (score_normalizado_0_1, reasoning) o (None, '') si falla."""
    if llm is None:
        return None, ""
    try:
        prompt = _LLM_PROMPT.format(
            vtype=vtype, hook_text=hook_text[:200],
            accent_word=accent_word or "(ninguno)",
            audio_energy=audio_energy,
            cps_observed=cps_observed, cps_target=cps_target,
        )
        out = llm.generate(prompt, task_type="classification",
                           max_tokens=60, temperature=0.2)
        if not out:
            return None, ""
        m = re.search(r"SCORE\s*:\s*(\d+)", out, re.IGNORECASE)
        if not m:
            return None, out[:200]
        raw = int(m.group(1))
        raw = max(1, min(10, raw))
        normalized = (raw - 1) / 9.0
        reason_m = re.search(r"RAZ[ÓO]N\s*:\s*(.+)", out, re.IGNORECASE)
        reason = (reason_m.group(1).strip() if reason_m else out[:200]).replace("\n", " ")[:240]
        return normalized, reason
    except Exception as e:
        log.warning("LLM hook scoring failed: %s", e)
        return None, ""


# ── Scoring principal ───────────────────────────────────────────────


def score_hook(
    video_path: str | Path,
    vtype: str,
    hook_text: str,
    accent_word: str | None = None,
    edl: list | None = None,
    first_sub_text: str | None = None,
    use_llm: bool = False,
    settings=None,
) -> HookScore:
    """Calcula el score completo del hook de un video renderizado.

    Args:
        video_path: ruta al MP4 final.
        vtype: 'narration' | 'personality' | 'test' — define target CPS.
        hook_text: texto narrado en el primer segmento.
        accent_word: palabra resaltada (puede venir de detect_hook_accent_word).
        edl: lista de EditDecision; si no, se detectan cuts vía ffmpeg.
        first_sub_text: texto del primer subtítulo (para validar accent).
        use_llm: True para añadir LLM scoring (opcional).
        settings: Settings (necesario solo si use_llm=True).
    """
    video_path = str(video_path)
    score = HookScore(raw_first_sub_text=first_sub_text or "")

    if not os.path.exists(video_path):
        score.notes.append("video_path not found")
        return score

    # 1. Audio energy
    rms = _extract_rms_peak_first_window(video_path, window_s=0.5)
    score.raw_rms_peak = rms
    # Mapeo: RMS 0.15 → 1.0 (un edge-tts con normalización razonable está acá);
    # RMS 0.03 → 0.2 (susurro). Curva lineal saturada.
    score.audio_energy_score = max(0.0, min(1.0, (rms - 0.02) / 0.13))

    # 2. CPS observado vs target
    from apps.production.script_generator import hook_cps_for_video_type
    target_cps = hook_cps_for_video_type(vtype)
    window = 1.5
    n_cuts = _count_cuts_in_window(edl, window) if edl else _detect_cuts_via_ffmpeg(video_path, window)
    observed_cps = n_cuts / window if window > 0 else 0.0
    score.raw_cps_observed = observed_cps
    score.raw_cps_target = target_cps
    # Score = 1 - |delta| / target, saturado en [0, 1]
    if target_cps > 0:
        delta = abs(observed_cps - target_cps) / target_cps
        score.cps_score = max(0.0, 1.0 - delta)
    else:
        score.cps_score = 1.0 if observed_cps <= 1.0 else 0.5

    # 3. Accent word
    if accent_word:
        # Buscar en first_sub_text si tenemos, si no en hook_text.
        haystack = (first_sub_text or hook_text or "").lower()
        if re.search(r"\b" + re.escape(accent_word.lower()) + r"\b", haystack):
            score.accent_word_score = 1.0
        else:
            score.accent_word_score = 0.3   # parcial: hay accent definido pero no aparece
            score.notes.append("accent_word not found in first sub")
    else:
        score.accent_word_score = 0.5   # neutro: no se especificó accent
        score.notes.append("no accent_word provided")

    # 4. LLM (opcional)
    llm = None
    if use_llm:
        try:
            from integrations.llm_provider import LLMProvider
            llm = LLMProvider(settings, conn=None) if settings else None
        except Exception as e:
            log.warning("LLM provider no disponible: %s", e)
        llm_norm, reason = _llm_score_hook(
            llm, vtype, hook_text or "", accent_word,
            rms, observed_cps, target_cps,
        )
        score.llm_score = llm_norm
        score.raw_llm_reasoning = reason

    # Overall: media ponderada, redistribuyendo si llm_score es None
    weights = dict(SCORE_WEIGHTS)
    components = {
        "audio_energy": score.audio_energy_score,
        "cps": score.cps_score,
        "accent_word": score.accent_word_score,
        "llm": score.llm_score,
    }
    if score.llm_score is None:
        weights.pop("llm")
        # Redistribuir 0.20 entre los 3 restantes proporcional
        total = sum(weights.values())
        weights = {k: v / total for k, v in weights.items()}
        components.pop("llm")
    score.overall = sum(weights[k] * components[k] for k in weights)
    return score


# ── Persistencia ─────────────────────────────────────────────────────


SCHEMA_HOOK_SCORES = """
CREATE TABLE IF NOT EXISTS hook_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_path TEXT NOT NULL,
    persona TEXT,
    vtype TEXT,
    series_slug TEXT,
    audio_energy_score REAL,
    cps_score REAL,
    accent_word_score REAL,
    llm_score REAL,
    overall_score REAL,
    raw_rms_peak REAL,
    raw_cps_observed REAL,
    raw_cps_target REAL,
    raw_first_sub_text TEXT,
    raw_llm_reasoning TEXT,
    passed INTEGER,           -- 1/0: pasó MIN_HOOK_SCORE
    notes TEXT,               -- JSON array de notas
    scored_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_hook_scores_path ON hook_scores(video_path);
CREATE INDEX IF NOT EXISTS idx_hook_scores_passed ON hook_scores(passed, scored_at DESC);
"""


def ensure_schema(conn: sqlite3.Connection):
    """Crea la tabla hook_scores si no existe. Idempotente."""
    conn.executescript(SCHEMA_HOOK_SCORES)
    conn.commit()


def persist_hook_score(
    conn: sqlite3.Connection,
    video_path: str | Path,
    score: HookScore,
    persona: str | None = None,
    vtype: str | None = None,
    series_slug: str | None = None,
    min_score: float = MIN_HOOK_SCORE,
) -> int:
    """Persiste un HookScore. Retorna id insertado."""
    ensure_schema(conn)
    cur = conn.execute(
        """INSERT INTO hook_scores
             (video_path, persona, vtype, series_slug,
              audio_energy_score, cps_score, accent_word_score, llm_score,
              overall_score, raw_rms_peak, raw_cps_observed, raw_cps_target,
              raw_first_sub_text, raw_llm_reasoning, passed, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            str(video_path), persona, vtype, series_slug,
            score.audio_energy_score, score.cps_score, score.accent_word_score,
            score.llm_score, score.overall,
            score.raw_rms_peak, score.raw_cps_observed, score.raw_cps_target,
            score.raw_first_sub_text[:500] if score.raw_first_sub_text else None,
            score.raw_llm_reasoning[:500] if score.raw_llm_reasoning else None,
            1 if score.passes(min_score) else 0,
            json.dumps(score.notes),
        ),
    )
    conn.commit()
    return cur.lastrowid


def fetch_score_for_video(conn: sqlite3.Connection, video_path: str | Path) -> dict | None:
    """Recupera el último score de un video. None si no hay."""
    cur = conn.execute(
        """SELECT * FROM hook_scores WHERE video_path = ?
           ORDER BY scored_at DESC LIMIT 1""",
        (str(video_path),),
    )
    row = cur.fetchone()
    return dict(row) if row else None


# ── Helper de alto nivel para integrar al pipeline ──────────────────


def score_and_gate(
    conn: sqlite3.Connection,
    video_path: str | Path,
    vtype: str,
    hook_text: str,
    accent_word: str | None = None,
    edl: list | None = None,
    first_sub_text: str | None = None,
    persona: str | None = None,
    series_slug: str | None = None,
    use_llm: bool = False,
    settings=None,
    min_score: float = MIN_HOOK_SCORE,
    block_on_fail: bool = False,
) -> HookScore:
    """Scorea, persiste y opcionalmente bloquea con excepción si reprueba.

    En modo `block_on_fail=False` (default), solo loguea WARNING — útil para
    fase de calibración. Activar `block_on_fail=True` cuando MIN_HOOK_SCORE
    esté calibrado contra retention real.
    """
    score = score_hook(
        video_path=video_path, vtype=vtype, hook_text=hook_text,
        accent_word=accent_word, edl=edl, first_sub_text=first_sub_text,
        use_llm=use_llm, settings=settings,
    )
    persist_hook_score(
        conn, video_path, score,
        persona=persona, vtype=vtype, series_slug=series_slug,
        min_score=min_score,
    )

    if score.passes(min_score):
        log.info(
            "[hook_scorer] %s → PASS (%.2f) audio=%.2f cps=%.2f accent=%.2f llm=%s",
            Path(str(video_path)).name, score.overall,
            score.audio_energy_score, score.cps_score, score.accent_word_score,
            f"{score.llm_score:.2f}" if score.llm_score is not None else "skip",
        )
    else:
        msg = (
            f"[hook_scorer] {Path(str(video_path)).name} → FAIL "
            f"({score.overall:.2f} < {min_score:.2f}) "
            f"audio={score.audio_energy_score:.2f} cps={score.cps_score:.2f} "
            f"accent={score.accent_word_score:.2f}"
        )
        if block_on_fail:
            log.error(msg)
            raise RuntimeError(f"Hook score below threshold: {score.overall:.2f}")
        else:
            log.warning(msg)

    return score
