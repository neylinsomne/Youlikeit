"""Transcripción local con tiempos por palabra (faster-whisper / CTranslate2).

Reemplaza a `integrations/local_transcriber.py` (insertaba una columna `lang`
que no existe) y a ex05._whisper_transcribe (transcribía el TRÁILER y lo
guardaba como subtítulo de la película). Acá siempre se transcribe el audio
del proxy, que comparte línea de tiempo con el master.

Backends (ASR_BACKEND=auto|local|groq):
  - local  faster-whisper (CTranslate2, sin torch) en la RTX 5060.
  - groq   API Whisper large-v3-turbo (integrations.ai.asr_api), plan gratis.
  auto = local si hay faster-whisper + CUDA; si no, groq si hay GROQ_API_KEY;
  si no, local en CPU (lento: horas para una película).
"""
from __future__ import annotations

import gc
import logging
import os
from pathlib import Path

from utils.gpu_lock import gpu_slot

log = logging.getLogger(__name__)

DEFAULT_MODEL = "large-v3-turbo"


_DLL_DIRS_DONE = False


def register_nvidia_dlls() -> list[str]:
    """Windows: hace visibles cuBLAS/cuDNN instalados por pip (nvidia-*-cu12).

    CTranslate2 carga `cublas64_12.dll` / `cudnn*64_9.dll` con LoadLibrary; los
    wheels de NVIDIA los dejan en site-packages/nvidia/<lib>/bin, fuera del PATH.
    En Linux (Docker) no hace falta: ver LD_LIBRARY_PATH en el Dockerfile.
    """
    global _DLL_DIRS_DONE
    if os.name != "nt" or _DLL_DIRS_DONE:
        return []
    added: list[str] = []
    try:
        import nvidia  # type: ignore  # paquete namespace de los wheels nvidia-*-cu12
        roots = list(nvidia.__path__)
    except ImportError:
        roots = []
    for root in roots:
        for bin_dir in Path(root).glob("*/bin"):
            os.add_dll_directory(str(bin_dir))
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
            added.append(str(bin_dir))
    _DLL_DIRS_DONE = True
    return added


def load_wav_16k(path: str | Path):
    """wav PCM16 mono 16 kHz → float32 [-1, 1]. Evita PyAV (faster-whisper ≤1.2
    pasa `metadata_errors` a av.open, que las versiones nuevas de PyAV rechazan)."""
    import wave

    import numpy as np
    with wave.open(str(path), "rb") as w:
        if w.getframerate() != 16000 or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError(f"{path}: se espera wav PCM16 mono 16 kHz "
                             f"({w.getframerate()} Hz, {w.getnchannels()} ch, {w.getsampwidth() * 8} bit)")
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return pcm.astype(np.float32) / 32768.0


def _load_model(model_size: str, device: str, compute_type: str | None):
    register_nvidia_dlls()
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "faster-whisper no está instalado. Instala requirements-gpu.txt "
            "(pip install -r requirements-gpu.txt)") from e
    if device in ("auto", "cuda"):
        try:
            return WhisperModel(model_size, device="cuda", compute_type=compute_type or "int8_float16")
        except Exception as e:  # noqa: BLE001 — sin CUDA / sin cuDNN → CPU
            if device == "cuda":
                raise
            log.warning("CUDA no disponible para faster-whisper (%s); usando CPU int8", e)
    return WhisperModel(model_size, device="cpu", compute_type=compute_type or "int8")


def segments_to_dicts(segments, language: str | None) -> list[dict]:
    """Normaliza los segmentos de faster-whisper a dicts en milisegundos."""
    out = []
    for s in segments:
        words = [{"start_ms": int(round(w.start * 1000)), "end_ms": int(round(w.end * 1000)),
                  "word": w.word, "prob": round(float(w.probability), 4)}
                 for w in (getattr(s, "words", None) or [])]
        text = (s.text or "").strip()
        if not text:
            continue
        out.append({
            "start_ms": int(round(s.start * 1000)), "end_ms": int(round(s.end * 1000)),
            "text": text, "lang": language,
            "avg_logprob": round(float(s.avg_logprob), 4),
            "no_speech_prob": round(float(s.no_speech_prob), 4),
            "words": words,
        })
    return out


def local_cuda_available() -> bool:
    try:
        import ctranslate2  # type: ignore
        import faster_whisper  # type: ignore  # noqa: F401
    except ImportError:
        return False
    try:
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:  # noqa: BLE001
        return False


def resolve_backend(backend: str | None = None) -> str:
    b = (backend or os.getenv("ASR_BACKEND", "auto")).strip().lower()
    if b in ("local", "groq"):
        return b
    if b != "auto":
        raise ValueError(f"ASR_BACKEND desconocido: {b!r} (auto|local|groq)")
    if local_cuda_available():
        return "local"
    if os.getenv("GROQ_API_KEY"):
        return "groq"
    log.warning("Sin CUDA para faster-whisper ni GROQ_API_KEY: ASR local en CPU (muy lento)")
    return "local"


def transcribe(audio_path: str | Path, *, backend: str | None = None,
               model_size: str = DEFAULT_MODEL, language: str | None = None,
               device: str = "auto", compute_type: str | None = None, vad: bool = True,
               duration_ms: int | None = None) -> tuple[list[dict], str | None]:
    """Transcribe un wav 16 kHz. Devuelve (segmentos, idioma detectado)."""
    if resolve_backend(backend) == "groq":
        from integrations.ai.asr_api import transcribe_groq
        result, lang = transcribe_groq(audio_path, duration_ms=duration_ms, language=language)
        log.info("ASR (groq): %d segmentos, idioma=%s", len(result), lang)
        return result, lang
    # ASR_DEVICE=cuda hace fallar rápido en vez de caer en silencio a CPU (horas).
    device = device if device != "auto" else os.getenv("ASR_DEVICE", "auto")
    audio = load_wav_16k(audio_path)
    with gpu_slot("asr"):
        model = _load_model(model_size, device, compute_type)
        try:
            segments, info = model.transcribe(
                audio, language=language, word_timestamps=True,
                vad_filter=vad, beam_size=5,
                # Películas: el contexto previo arrastra alucinaciones en silencios/música.
                condition_on_previous_text=False,
            )
            lang = getattr(info, "language", language)
            result = segments_to_dicts(segments, lang)   # consume el generador dentro del lock
        finally:
            del model
            gc.collect()
    log.info("ASR: %d segmentos, idioma=%s", len(result), lang)
    return result, lang
