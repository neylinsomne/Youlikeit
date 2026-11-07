"""Configuración del estudio leída del entorno EN CADA USO (el .env se carga en `ylk studio`)."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DEFAULT_PORT = 8001
DEFAULT_ORIGINS = ("http://127.0.0.1:5180", "http://localhost:5180")


def data_dir() -> Path:
    path = Path(os.getenv("DATA_DIR", "data"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def port() -> int:
    return int(os.getenv("STUDIO_PORT") or DEFAULT_PORT)


def token() -> str:
    return (os.getenv("STUDIO_TOKEN") or "").strip()


def allowed_origins() -> list[str]:
    """CORS: solo el front de Vite. STUDIO_ALLOWED_ORIGINS (coma) lo reemplaza si hace falta."""
    extra = [o.strip().rstrip("/") for o in (os.getenv("STUDIO_ALLOWED_ORIGINS") or "").split(",") if o.strip()]
    return extra or list(DEFAULT_ORIGINS)


def front_url() -> str:
    return (os.getenv("STUDIO_FRONT_URL") or DEFAULT_ORIGINS[0]).rstrip("/") + "/"


def connect() -> sqlite3.Connection:
    """core.db.get_db(DATA_DIR): WAL + busy_timeout + esquema completo (≈5 ms)."""
    from core.db import get_db
    return get_db(data_dir())


@contextmanager
def db():
    """Una conexión por request/hilo (sqlite3 no se comparte entre hilos)."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
