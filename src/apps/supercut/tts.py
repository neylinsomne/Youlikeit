"""Voz de la narración (texto → audio + tiempos por palabra).

Backends (TTS_BACKEND):
  - edge   edge-tts: online y gratis, voces neuronales es-MX / es-CO / en-US,
           con WordBoundary (tiempos por palabra para subtítulos). Default.
  - local  Qwen3-TTS en la GPU. NO implementado a propósito: correr modelos
           locales o bajar pesos requiere el permiso explícito del dueño.

    synthesize("Hola", lang="es", out_path=Path("n.mp3"))
      → (Path("n.mp3"), [{"word": "Hola", "start_ms": 50, "end_ms": 420}])
"""
from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path
from typing import Protocol, runtime_checkable

VOICES = {
    "es": "es-MX-DaliaNeural",
    "es-mx": "es-MX-DaliaNeural",
    "es-co": "es-CO-SalomeNeural",
    "en": "en-US-AriaNeural",
}
DEFAULT_TIMEOUT_S = 90


class TTSError(RuntimeError):
    """El backend de voz no devolvió audio."""


@runtime_checkable
class TTSBackend(Protocol):
    name: str

    def synthesize(self, text: str, *, lang: str, out_path: Path,
                   voice: str | None = None) -> tuple[Path, list[dict]]:
        """Escribe el audio en out_path y devuelve (ruta, [{word, start_ms, end_ms}])."""
        ...


def default_voice(lang: str) -> str:
    """Voz por idioma; se puede fijar con TTS_VOICE (todas) o TTS_VOICE_ES / TTS_VOICE_EN."""
    lang = (lang or "es").lower()
    base = lang.split("-")[0]
    return (os.getenv(f"TTS_VOICE_{base.upper()}") or os.getenv("TTS_VOICE")
            or VOICES.get(lang) or VOICES.get(base) or VOICES["en"])


def _run_coro(factory, timeout: float):
    """Corre una corrutina en un hilo propio (sirve aunque el llamador tenga un loop activo).

    No se usa Communicate.stream_sync: si la red falla, su hilo muere sin avisar
    y el generador se queda esperando para siempre.
    """
    box: dict = {}

    def target() -> None:
        try:
            box["value"] = asyncio.run(factory())
        except BaseException as e:  # noqa: BLE001 — se re-levanta en el hilo llamador
            box["error"] = e

    t = threading.Thread(target=target, name="tts", daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TTSError(f"TTS sin respuesta en {timeout:.0f} s")
    if "error" in box:
        raise TTSError(f"{type(box['error']).__name__}: {box['error']}") from box["error"]
    return box["value"]


class EdgeTTSBackend:
    name = "edge"

    def __init__(self, timeout: float = DEFAULT_TIMEOUT_S):
        self.timeout = timeout

    def synthesize(self, text: str, *, lang: str, out_path: Path,
                   voice: str | None = None) -> tuple[Path, list[dict]]:
        import edge_tts

        text = (text or "").strip()
        if not text:
            raise ValueError("texto vacío")
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        comm = edge_tts.Communicate(text, voice or default_voice(lang), boundary="WordBoundary")

        async def collect() -> tuple[bytes, list[dict]]:
            audio, words = bytearray(), []
            async for chunk in comm.stream():
                if chunk.get("type") == "audio":
                    audio += chunk.get("data") or b""
                elif chunk.get("type") == "WordBoundary":
                    start = int(chunk["offset"]) // 10_000              # unidades de 100 ns → ms
                    words.append({"word": chunk.get("text", ""), "start_ms": start,
                                  "end_ms": start + int(chunk.get("duration", 0)) // 10_000})
            return bytes(audio), words

        audio, words = _run_coro(collect, self.timeout)
        if not audio:
            raise TTSError("edge-tts no devolvió audio")
        out_path.write_bytes(audio)
        return out_path, words


class LocalTTSBackend:
    """Interfaz para Qwen3-TTS local. Deliberadamente sin implementar."""
    name = "local"

    def synthesize(self, text: str, *, lang: str, out_path: Path,
                   voice: str | None = None) -> tuple[Path, list[dict]]:
        raise NotImplementedError(
            "TTS local (Qwen3-TTS) no está habilitado: usar la GPU o bajar pesos requiere permiso "
            "explícito del dueño. Usa TTS_BACKEND=edge.")


_BACKENDS = {"edge": EdgeTTSBackend, "local": LocalTTSBackend}


def get_backend(name: str | None = None) -> TTSBackend:
    name = (name or os.getenv("TTS_BACKEND") or "edge").strip().lower()
    if name not in _BACKENDS:
        raise ValueError(f"TTS_BACKEND desconocido: {name!r} (usa {', '.join(_BACKENDS)})")
    return _BACKENDS[name]()


def synthesize(text: str, *, lang: str, out_path: str | Path, voice: str | None = None,
               backend: str | None = None) -> tuple[Path, list[dict]]:
    """Texto → (audio, tiempos por palabra en ms) con el backend configurado."""
    return get_backend(backend).synthesize(text, lang=lang, out_path=Path(out_path), voice=voice)
