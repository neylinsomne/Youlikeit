"""Bóveda de cuentas conectadas: SQLite + cifrado en reposo de los tokens.

Los tokens OAuth de TikTok se cifran con Fernet (AES-128-CBC + HMAC-SHA256)
usando TOKEN_ENC_KEY (variable de entorno del servidor, nunca en el código).
Del perfil solo se guardan open_id y display_name; el avatar no se almacena.
Desconectar borra la fila (y la app revoca el token en TikTok).
"""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

SCHEMA = """
CREATE TABLE IF NOT EXISTS tiktok_accounts (
    open_id TEXT PRIMARY KEY,
    display_name TEXT,
    access_token_enc BLOB NOT NULL,
    refresh_token_enc BLOB,
    scope TEXT,
    expires_at INTEGER,
    refresh_expires_at INTEGER,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS publishes (
    publish_id TEXT PRIMARY KEY,
    open_id TEXT NOT NULL,
    lesson_id TEXT NOT NULL,
    status TEXT,
    created_at INTEGER NOT NULL
);
"""


def _fernet() -> Fernet:
    key = os.getenv("TOKEN_ENC_KEY", "")
    if not key:
        raise RuntimeError("TOKEN_ENC_KEY no configurada: no se guardan tokens sin cifrar")
    return Fernet(key.encode())


def db_path() -> Path:
    path = Path(os.getenv("DATA_DIR", "/data")) / "web.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def save_account(open_id: str, display_name: str | None, token: dict) -> None:
    f = _fernet()
    now = int(time.time())
    with connect() as conn:
        conn.execute(
            """INSERT INTO tiktok_accounts VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(open_id) DO UPDATE SET display_name = excluded.display_name,
                 access_token_enc = excluded.access_token_enc, refresh_token_enc = excluded.refresh_token_enc,
                 scope = excluded.scope, expires_at = excluded.expires_at,
                 refresh_expires_at = excluded.refresh_expires_at, updated_at = excluded.updated_at""",
            (open_id, display_name, f.encrypt(token["access_token"].encode()),
             f.encrypt(token["refresh_token"].encode()) if token.get("refresh_token") else None,
             token.get("scope"), now + int(token.get("expires_in", 0)),
             now + int(token.get("refresh_expires_in", 0)), now))


def get_account(open_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM tiktok_accounts WHERE open_id = ?", (open_id,)).fetchone()
    if row is None:
        return None
    f = _fernet()
    try:
        access = f.decrypt(row["access_token_enc"]).decode()
        refresh = f.decrypt(row["refresh_token_enc"]).decode() if row["refresh_token_enc"] else None
    except InvalidToken:
        return None                                   # clave rotada: hay que reconectar
    return {"open_id": row["open_id"], "display_name": row["display_name"], "scope": row["scope"],
            "access_token": access, "refresh_token": refresh, "expires_at": row["expires_at"]}


def delete_account(open_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM tiktok_accounts WHERE open_id = ?", (open_id,))
        conn.execute("DELETE FROM publishes WHERE open_id = ?", (open_id,))


def valid_access_token(open_id: str, refresher) -> str | None:
    """Token de acceso vigente; si venció (o vence en < 5 min) lo renueva con `refresher`."""
    acc = get_account(open_id)
    if acc is None:
        return None
    if acc["expires_at"] and acc["expires_at"] - 300 > int(time.time()):
        return acc["access_token"]
    if not acc["refresh_token"]:
        return None
    token = refresher(acc["refresh_token"])
    save_account(open_id, acc["display_name"], token)
    return token["access_token"]


def record_publish(publish_id: str, open_id: str, lesson_id: str, status: str = "PROCESSING_UPLOAD") -> None:
    with connect() as conn:
        conn.execute("INSERT OR REPLACE INTO publishes VALUES (?, ?, ?, ?, ?)",
                     (publish_id, open_id, lesson_id, status, int(time.time())))


def get_publish(publish_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM publishes WHERE publish_id = ?", (publish_id,)).fetchone()
    return dict(row) if row else None


def update_publish_status(publish_id: str, status: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE publishes SET status = ? WHERE publish_id = ?", (status, publish_id))
