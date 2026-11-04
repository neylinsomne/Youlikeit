"""Archivos: GET /api/files/{kind}/{name} con allowlist estricta.

Solo dos carpetas: media_cache/previews (kind=preview) y outputs/lessons (kind=lesson),
solo .mp4, nombre simple. El path resuelto DEBE quedar dentro de la carpeta (resolve +
relative_to): cualquier otra cosa (.env, tokens/, la DB, '..') responde 404.
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from apps.studio.auth import require_token
from apps.supercut import lessons, preview

router = APIRouter(prefix="/api", tags=["files"], dependencies=[Depends(require_token)])
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}\.mp4$")


def _bases() -> dict[str, Path]:
    return {"preview": preview.preview_dir(), "lesson": lessons.output_dir()}


def resolve_file(kind: str, name: str) -> Path | None:
    base = _bases().get(kind)
    if base is None or not _NAME.fullmatch(name) or ".." in name:
        return None
    try:
        root = base.resolve()
        path = (root / name).resolve()
        path.relative_to(root)
    except (OSError, ValueError):
        return None
    return path if path.is_file() else None


@router.get("/files/{kind}/{name}")
def get_file(kind: str, name: str) -> FileResponse:
    path = resolve_file(kind, name)
    if path is None:
        raise HTTPException(404, "No existe")
    return FileResponse(path, media_type="video/mp4", headers={"Cache-Control": "no-cache"})
