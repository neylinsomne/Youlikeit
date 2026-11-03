"""Lock de GPU entre procesos (RTX 5060, 8 GB): una etapa pesada a la vez.

WhisperX/faster-whisper, el LLM de etiquetado, el VLM y el TTS no caben juntos
en 8 GB. Cada etapa toma el slot, carga su modelo, lo descarga y lo suelta.
Implementación sin dependencias: archivo creado con O_EXCL; se considera
abandonado si su mtime supera `stale_after` (proceso muerto sin limpiar).
"""
from __future__ import annotations

import contextlib
import os
import tempfile
import time
from pathlib import Path

# Global a la máquina (no depende de DATA_DIR): la GPU es una sola.
DEFAULT_LOCK = Path(tempfile.gettempdir()) / "youlikeit-gpu.lock"


@contextlib.contextmanager
def gpu_slot(name: str, *, lock_path: Path = DEFAULT_LOCK, timeout: float = 6 * 3600,
             poll: float = 2.0, stale_after: float = 8 * 3600):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"{os.getpid()} {name} {time.time():.0f}\n".encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - lock_path.stat().st_mtime > stale_after:
                    lock_path.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() > deadline:
                holder = lock_path.read_text(errors="replace").strip() if lock_path.exists() else "?"
                raise TimeoutError(f"GPU ocupada por: {holder}") from None
            time.sleep(poll)
    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)
