"""ASR por API: Groq Whisper (OpenAI-compatible) con timestamps por palabra.

Sirve cuando la GPU local no está lista (o está ocupada con otra etapa).
Límite del plan gratis: 25 MB por archivo → el wav se parte en tramos de
10 min codificados a MP3 48 kbps mono (~3.6 MB) con 2 s de solape. Al unir,
cada segmento pertenece al tramo donde EMPIEZA antes del punto medio del
solape, así no se duplica texto.
"""
from __future__ import annotations

import logging
import os
import tempfile
import time
from pathlib import Path

import requests

from utils import ffmpeg as ff

log = logging.getLogger(__name__)

GROQ_ASR_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
DEFAULT_MODEL = "whisper-large-v3-turbo"
CHUNK_MS = 600_000
OVERLAP_MS = 2_000

_LANG = {"english": "en", "spanish": "es", "italian": "it", "french": "fr", "portuguese": "pt",
         "german": "de", "japanese": "ja", "korean": "ko", "chinese": "zh", "russian": "ru"}


def normalize_lang(lang: str | None) -> str | None:
    if not lang:
        return None
    lang = lang.strip().lower()
    return _LANG.get(lang, lang[:2] if len(lang) > 2 else lang)


def plan_audio_chunks(duration_ms: int, *, chunk_ms: int = CHUNK_MS,
                      overlap_ms: int = OVERLAP_MS) -> list[tuple[int, int]]:
    """Tramos [(start, end)] con solape; el último termina en duration_ms."""
    if duration_ms <= chunk_ms:
        return [(0, duration_ms)]
    out, start = [], 0
    while start < duration_ms:
        end = min(start + chunk_ms, duration_ms)
        out.append((start, end))
        if end >= duration_ms:
            break
        start = end - overlap_ms
    return out


def merge_chunks(results: list[tuple[int, int, dict]], *, overlap_ms: int = OVERLAP_MS) -> list[dict]:
    """Une respuestas verbose_json de cada tramo en segmentos absolutos (ms).

    results: [(chunk_start_ms, chunk_end_ms, respuesta_json)] en orden.
    """
    segments: list[dict] = []
    n = len(results)
    for k, (cs, ce, data) in enumerate(results):
        lo = cs + overlap_ms // 2 if k > 0 else cs
        hi = ce - overlap_ms // 2 if k < n - 1 else ce + 1
        words = [(cs + int(round(w["start"] * 1000)), cs + int(round(w["end"] * 1000)), w["word"])
                 for w in data.get("words") or []]
        lang = normalize_lang(data.get("language"))
        for seg in data.get("segments") or []:
            s_ms = cs + int(round(seg["start"] * 1000))
            e_ms = cs + int(round(seg["end"] * 1000))
            if not (lo <= s_ms < hi) or not (seg.get("text") or "").strip():
                continue
            seg_words = [{"start_ms": ws, "end_ms": we, "word": w, "prob": None}
                         for ws, we, w in words if s_ms <= ws < e_ms]
            segments.append({
                "start_ms": s_ms, "end_ms": e_ms, "text": seg["text"].strip(), "lang": lang,
                "avg_logprob": seg.get("avg_logprob"), "no_speech_prob": seg.get("no_speech_prob"),
                "words": seg_words,
            })
    segments.sort(key=lambda s: s["start_ms"])
    return segments


def _encode_chunk(wav: Path, start_ms: int, end_ms: int, out: Path) -> Path:
    ff.run(["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
            "-ss", ff.ms_to_ts(start_ms), "-t", ff.ms_to_ts(end_ms - start_ms), "-i", str(wav),
            "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "48k", str(out)], timeout=600)
    return out


def _post_chunk(path: Path, *, api_key: str, model: str, language: str | None,
                max_retries: int = 5, timeout: float = 300) -> dict:
    data = [("model", model), ("response_format", "verbose_json"),
            ("timestamp_granularities[]", "word"), ("timestamp_granularities[]", "segment"),
            ("temperature", "0")]
    if language:
        data.append(("language", language))
    session = requests.Session()
    for attempt in range(max_retries):
        with open(path, "rb") as fh:
            resp = session.post(GROQ_ASR_URL, headers={"Authorization": f"Bearer {api_key}"},
                                data=data, files={"file": (path.name, fh, "audio/mpeg")}, timeout=timeout)
        if resp.status_code == 429 and attempt < max_retries - 1:
            wait = float(resp.headers.get("Retry-After") or 20 * (attempt + 1))
            log.warning("Groq ASR 429 (límite de audio/hora); esperando %.0fs", wait)
            time.sleep(min(wait, 600))
            continue
        if resp.status_code >= 400:
            raise RuntimeError(f"Groq ASR {resp.status_code}: {resp.text[:200]}")
        return resp.json()
    raise RuntimeError("Groq ASR: reintentos agotados")


def transcribe_groq(wav: str | Path, *, duration_ms: int | None = None, language: str | None = None,
                    model: str | None = None, api_key: str | None = None) -> tuple[list[dict], str | None]:
    api_key = api_key or os.getenv("GROQ_API_KEY", "")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY no configurada (https://console.groq.com/keys, plan gratis)")
    model = model or os.getenv("GROQ_ASR_MODEL", DEFAULT_MODEL)
    wav = Path(wav)
    duration_ms = duration_ms or ff.summarize_probe(ff.probe(wav))["duration_ms"]
    plan = plan_audio_chunks(duration_ms)
    results = []
    with tempfile.TemporaryDirectory(prefix="ylk_asr_") as tmp:
        for i, (cs, ce) in enumerate(plan):
            mp3 = _encode_chunk(wav, cs, ce, Path(tmp) / f"chunk_{i:03d}.mp3")
            log.info("Groq ASR tramo %d/%d (%s–%s s)", i + 1, len(plan), cs // 1000, ce // 1000)
            results.append((cs, ce, _post_chunk(mp3, api_key=api_key, model=model, language=language)))
    segments = merge_chunks(results)
    lang = segments[0]["lang"] if segments else normalize_lang(language)
    return segments, lang
