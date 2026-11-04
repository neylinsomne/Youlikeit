"""Excepciones de dominio → códigos HTTP del contrato.

    404 no existe · 409 estado inválido · 422 validación · 502 falla externa
    503 falta configuración local (WEB_BASE_URL/STUDIO_API_KEY, client_secrets, TOKEN_ENC_KEY)

Los endpoints usan `with api() as conn:`: abre una conexión propia (get_db) y
traduce las excepciones conocidas; las desconocidas siguen siendo 500.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager

from fastapi import HTTPException

from apps.publish import service, tiktok_bridge, youtube
from apps.studio import settings
from apps.supercut import lessons, planner, preview, script, tts
from integrations.ai.llm_json import LLMUnavailable
from utils.ffmpeg import FFmpegError

log = logging.getLogger(__name__)


class NotFound(LookupError):
    """Recurso inexistente (asset, momento, job…)."""


# Orden importa: subclases antes que sus bases.
_MAP: tuple[tuple[type[BaseException], int], ...] = (
    (NotFound, 404),
    (lessons.LessonNotFound, 404),
    (preview.MomentNotFound, 404),
    (lessons.InvalidState, 409),               # incluye service.NotApproved
    (planner.PlanError, 409),
    (youtube.YouTubeNotConnected, 409),
    (youtube.YouTubeAuthError, 400),
    (youtube.YouTubeNotConfigured, 503),
    (tiktok_bridge.BridgeNotConfigured, 503),
    (script.ScriptUnavailable, 502),
    (tiktok_bridge.BridgeError, 502),
    (youtube.YouTubeError, 502),
    (service.PublishError, 502),
    (tts.TTSError, 502),
    (LLMUnavailable, 502),
    (FFmpegError, 502),
    (ValueError, 422),
)


def to_http(exc: BaseException) -> HTTPException | None:
    for cls, code in _MAP:
        if isinstance(exc, cls):
            if code == 502:
                log.warning("Falla externa: %s: %s", type(exc).__name__, exc)
            return HTTPException(status_code=code, detail=str(exc)[:1000] or type(exc).__name__)
    return None


@contextmanager
def api():
    """Conexión por request + traducción de errores de dominio."""
    with settings.db() as conn:
        try:
            yield conn
        except HTTPException:
            raise
        except Exception as e:
            http = to_http(e)
            if http is None:
                raise
            raise http from e
