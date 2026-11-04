"""Lock de GPU entre procesos (RTX 5060, 8 GB): una etapa pesada a la vez.

WhisperX/faster-whisper, el LLM de etiquetado, el VLM y el TTS no caben juntos
en 8 GB. Cada etapa toma el slot, carga su modelo, lo descarga y lo suelta.
Implementación sin dependencias: archivo creado con O_EXCL que guarda el PID.
Se considera abandonado si ese PID ya no existe (proceso matado sin limpiar,
p.ej. Ctrl+C a mitad de una transcripción) o, como red de seguridad, si su
mtime supera `stale_after`.
"""
from __future__ import annotations

import contextlib
import os
import tempfile
import time
from pathlib import Path

# Global a la máquina (no depende de DATA_DIR): la GPU es una sola.
DEFAULT_LOCK = Path(tempfile.gettempdir()) / "youlikeit-gpu.lock"


def pid_alive(pid: int) -> bool:
    """¿Existe el proceso? Sin efectos secundarios (en Windows os.kill MATA)."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5             # ACCESS_DENIED → existe
        try:
            code = wintypes.DWORD()
            kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return code.value == 259                         # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def lock_holder(lock_path: Path) -> tuple[int, str]:
    """(pid, nombre de etapa) del dueño del lock; (0, '?') si no se puede leer."""
    try:
        pid, name, *_ = lock_path.read_text(errors="replace").split()
        return int(pid), name
    except (OSError, ValueError):
        return 0, "?"


def is_stale(lock_path: Path, *, stale_after: float) -> bool:
    pid, _ = lock_holder(lock_path)
    if pid and not pid_alive(pid):
        return True
    try:
        return time.time() - lock_path.stat().st_mtime > stale_after
    except FileNotFoundError:
        return False


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
            if is_stale(lock_path, stale_after=stale_after):
                lock_path.unlink(missing_ok=True)
                continue
            if time.monotonic() > deadline:
                pid, holder = lock_holder(lock_path)
                raise TimeoutError(f"GPU ocupada por: {holder} (pid {pid})") from None
            time.sleep(poll)
    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)
