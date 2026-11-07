"""Publicar una lección aprobada en TikTok (borrador) o YouTube.

    approved ──publish──► publication pending → sent | published | failed
                           lección → published si alguna plataforma salió bien

TikTok queda `sent` (borrador en el inbox: el creador termina en la app, con la
música que elija allí). YouTube queda `published` (subido al canal; privado y
con publishAt si se pidió).
"""
from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from pathlib import Path

from apps.publish import tiktok_bridge, youtube
from apps.supercut import lessons

log = logging.getLogger(__name__)

TIKTOK_STATUS = {"FAILED": "failed", "PUBLISH_COMPLETE": "published"}   # el resto (inbox/procesando) → sent


class NotApproved(lessons.InvalidState):
    """La lección no está aprobada (o no tiene video): la API responde 409."""


class PublishError(RuntimeError):
    """La plataforma falló (la publicación queda `failed`): la API responde 502."""


def require_publishable(conn: sqlite3.Connection, lesson_id: int) -> Path:
    try:
        lessons.assert_publishable(conn, lesson_id)
    except lessons.InvalidState as e:
        raise NotApproved(str(e)) from e
    path = lessons.video_path(lesson_id)
    if not path.exists():
        raise NotApproved("La lección no tiene video renderizado")
    return path


def youtube_metadata(lesson: dict) -> dict:
    script = lesson.get("script") or {}
    works = [f"- {it['work_title']} ({it['work_year']})" if it.get("work_year") else f"- {it['work_title']}"
             for it in lesson.get("items", [])]
    es = (lesson.get("lang") or "es").startswith("es")
    head = "Escenas" if es else "Scenes"
    rights = ("Material de dominio público o con licencia abierta." if es
              else "Public-domain or openly licensed footage.")
    tags = (["empatía", "cine", "emociones", "educación emocional"] if es
            else ["empathy", "film", "emotions", "emotional literacy"])
    parts = [script.get("hook") or "", f"{head}:\n" + "\n".join(works), rights, "#empatía #cine" if es else "#empathy #film"]
    return {"title": lesson["title"], "description": "\n\n".join(p for p in parts if p.strip()), "tags": tags}


def publish_lesson(conn: sqlite3.Connection, lesson_id: int, platform: str, *,
                   progress: Callable[[str, int, str], None] | None = None, **kw) -> dict:
    """Publica y devuelve la Publication. kw: open_id (tiktok) | privacy, publish_at (youtube)."""
    if platform not in ("tiktok", "youtube"):
        raise ValueError(f"plataforma inválida: {platform!r}")
    path = require_publishable(conn, lesson_id)
    lesson = lessons.get_lesson(conn, lesson_id)
    if platform == "youtube":       # validar ANTES de crear la publicación (422, no 'failed')
        youtube.build_body(title=lesson["title"], description="", tags=None,
                           privacy=kw.get("privacy") or "private", publish_at=kw.get("publish_at"),
                           duration_s=lesson.get("duration_s"))
    elif not kw.get("open_id"):
        raise ValueError("open_id requerido para TikTok")
    pub = lessons.create_publication(conn, lesson_id, platform)
    try:
        if platform == "tiktok":
            res = tiktok_bridge.send_draft(path, kw["open_id"], f"lesson-{lesson_id}", progress=progress)
            status = TIKTOK_STATUS.get(res["status"], "sent")
            pub = lessons.update_publication(conn, pub["id"], status=status, external_id=res["publish_id"],
                                             detail=res["status"])
            if status == "failed":
                raise PublishError(f"TikTok devolvió FAILED para {res['publish_id']}")
        else:
            meta = youtube_metadata(lesson)
            res = youtube.upload(path, title=meta["title"], description=meta["description"], tags=meta["tags"],
                                 privacy=kw.get("privacy") or "private", publish_at=kw.get("publish_at"),
                                 duration_s=lesson.get("duration_s"), progress=progress)
            detail = f"privacy={res['privacy']}" + (f" publishAt={res['publish_at']}" if res.get("publish_at") else "")
            pub = lessons.update_publication(conn, pub["id"], status="published", external_id=res["video_id"],
                                             url=res["url"], detail=detail)
    except PublishError:
        raise
    except Exception as e:
        log.warning("Publicación %s en %s falló: %s", lesson_id, platform, e)
        lessons.update_publication(conn, pub["id"], status="failed", detail=f"{type(e).__name__}: {e}")
        raise PublishError(f"{platform}: {e}") from e
    lessons.mark_published(conn, lesson_id)
    return pub
