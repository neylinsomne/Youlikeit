"""Preview de un momento: clip corto de 480 px de alto, en caché (media_cache/previews).

Mismo camino que el render (extract_segment por rango + cut_exact), pero a baja
resolución y sin rótulos. Es desechable: se regenera desde la DB + el master.
"""
from __future__ import annotations

import os
import sqlite3
import uuid
from pathlib import Path

from apps.media import storage
from apps.media.fetch import cut_exact, extract_segment
from apps.media.models import media_cache_dir

PREVIEW_HEIGHT = 480


class MomentNotFound(LookupError):
    pass


def preview_dir() -> Path:
    return media_cache_dir("previews")


def preview_path(moment_id: int, start_ms: int, end_ms: int) -> Path:
    # El rango va en el nombre: si el momento cambia de límites, el preview viejo no se reutiliza.
    return preview_dir() / f"moment_{int(moment_id)}_{int(start_ms)}_{int(end_ms)}.mp4"


def moment_preview(conn: sqlite3.Connection, moment_id: int) -> Path:
    row = conn.execute("SELECT m.start_ms, m.end_ms, a.master_uri FROM moments m "
                       "JOIN media_assets a ON a.id = m.asset_id WHERE m.id = ?", (moment_id,)).fetchone()
    if row is None:
        raise MomentNotFound(f"momento {moment_id} no existe")
    start_ms, end_ms, master = int(row[0]), int(row[1]), row[2]
    path = preview_path(moment_id, start_ms, end_ms)
    if path.exists():
        storage.touch(path)
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    mezz = extract_segment(master, start_ms, end_ms)
    tmp = path.with_name(f"{path.stem}.{uuid.uuid4().hex[:8]}.part.mp4")
    try:
        cut_exact(mezz, start_ms, end_ms, tmp, vf=f"scale=-2:{PREVIEW_HEIGHT}")
        os.replace(tmp, path)                       # atómico: dos pedidos a la vez no se pisan
    finally:
        tmp.unlink(missing_ok=True)
    return path
