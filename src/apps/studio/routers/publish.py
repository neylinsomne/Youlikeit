"""Publicar: cuentas de TikTok (vía puente de web/), OAuth de YouTube, envío y publicaciones.

El callback de YouTube (`public_router`) NO lleva el token: Google redirige el
navegador directo a 127.0.0.1 sin header. Lo protege el `state` de un solo uso
(10 min) que guardó auth_url().
"""
from __future__ import annotations

from html import escape
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from apps.publish import tiktok_bridge, youtube
from apps.studio import settings
from apps.studio.auth import require_token
from apps.studio.errors import api, to_http
from apps.studio.routers.jobs import submit
from apps.supercut import lessons

router = APIRouter(prefix="/api", tags=["publish"], dependencies=[Depends(require_token)])
public_router = APIRouter(prefix="/api", tags=["publish"])


class TikTokIn(BaseModel):
    open_id: str = Field(min_length=1, max_length=200)


class YouTubeIn(BaseModel):
    privacy: Literal["private", "unlisted", "public"] = "private"
    publish_at: str | None = Field(default=None, max_length=40)


@router.get("/publish/tiktok/accounts")
def tiktok_accounts() -> dict:
    with api():
        return {"accounts": tiktok_bridge.list_accounts()}       # BridgeError → 502


@router.post("/lessons/{lesson_id}/publish/tiktok")
def publish_tiktok(lesson_id: int, body: TikTokIn, request: Request) -> dict:
    with api() as conn:
        return submit(request, conn, "publish_tiktok", {"lesson_id": lesson_id, "open_id": body.open_id})


@router.get("/publish/youtube/status")
def youtube_status() -> dict:
    return youtube.status()


@router.get("/publish/youtube/connect")
def youtube_connect() -> RedirectResponse:
    with api():
        url = youtube.auth_url()                                  # sin client_secrets/TOKEN_ENC_KEY → 503
    return RedirectResponse(url, status_code=302)


def _page(title: str, message: str, status_code: int = 200) -> HTMLResponse:
    back = escape(settings.front_url(), quote=True)
    body = (f"<!doctype html><html lang='es'><meta charset='utf-8'><title>{escape(title)}</title>"
            "<body style='font-family:system-ui;background:#070710;color:#eee;padding:3rem'>"
            f"<h1>{escape(title)}</h1><p>{escape(message)}</p>"
            f"<p><a style='color:#7ad7ff' href='{back}'>Volver al estudio</a></p></body></html>")
    return HTMLResponse(body, status_code=status_code)


@public_router.get("/publish/youtube/callback", include_in_schema=False)
def youtube_callback(state: str | None = None, code: str | None = None, error: str | None = None) -> HTMLResponse:
    try:
        st = youtube.handle_callback(state=state, code=code, error=error)
    except youtube.YouTubeError as e:
        http = to_http(e)
        return _page("No se pudo conectar YouTube", str(e), http.status_code if http else 502)
    return _page("YouTube conectado", f"Canal: {st.get('channel_title') or 'conectado'}. Ya puedes cerrar esta pestaña.")


@router.post("/lessons/{lesson_id}/publish/youtube")
def publish_youtube(lesson_id: int, body: YouTubeIn, request: Request) -> dict:
    with api() as conn:
        return submit(request, conn, "publish_youtube",
                      {"lesson_id": lesson_id, "privacy": body.privacy, "publish_at": body.publish_at})


@router.get("/lessons/{lesson_id}/publications")
def publications(lesson_id: int) -> dict:
    with api() as conn:
        lessons.get_lesson(conn, lesson_id)
        return {"items": lessons.list_publications(conn, lesson_id)}
