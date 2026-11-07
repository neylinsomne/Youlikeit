"""Sistema: GET /api/health (público) y GET /api/overview."""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends

from apps.media import storage
from apps.publish import youtube
from apps.studio import jobs
from apps.studio.auth import require_token
from apps.studio.errors import api
from apps.supercut.schema import STATUSES

public = APIRouter(prefix="/api", tags=["system"])
router = APIRouter(prefix="/api", tags=["system"], dependencies=[Depends(require_token)])


@public.get("/health")
def health() -> dict:
    return {"ok": True}


def _env(name: str) -> bool:
    return bool((os.getenv(name) or "").strip())


def credentials() -> list[dict]:
    """Solo PRESENCIA de variables/archivos: sin red y sin mostrar valores."""
    checks = [
        ("Groq", _env("GROQ_API_KEY"), "ASR y LLM por API"),
        ("Gemini", _env("GEMINI_API_KEY"), "LLM por API (respaldo)"),
        ("Puente TikTok (web)", _env("WEB_BASE_URL") and _env("STUDIO_API_KEY"),
         "borradores en TikTok (WEB_BASE_URL + STUDIO_API_KEY)"),
        ("YouTube OAuth client", youtube.client_secrets_path().exists(), "conectar YouTube (GOOGLE_CLIENT_SECRETS)"),
        ("Cifrado de tokens", _env("TOKEN_ENC_KEY"), "guardar el token de YouTube (TOKEN_ENC_KEY)"),
        ("YouTube conectado", youtube.token_path().exists(), "subir a YouTube"),
    ]
    return [{"name": n, "status": "OK" if ok else "MISSING", "needed_for": why} for n, ok, why in checks]


def settings_view() -> dict:
    from integrations.ai.llm_json import model_for
    return {"asr_backend": os.getenv("ASR_BACKEND") or "auto", "llm_provider": os.getenv("LLM_PROVIDER") or "auto",
            "groq_model": model_for("groq"), "web_base_url": os.getenv("WEB_BASE_URL") or None,
            "tts_backend": os.getenv("TTS_BACKEND") or "edge"}


@router.get("/overview")
def overview() -> dict:
    with api() as conn:
        one = lambda sql: int(conn.execute(sql).fetchone()[0])  # noqa: E731
        by_status = dict.fromkeys(STATUSES, 0)
        for status, n in conn.execute("SELECT status, COUNT(*) FROM lessons GROUP BY status"):
            by_status[status] = int(n)
        counts = {
            "works": one("SELECT COUNT(*) FROM works"),
            "assets": one("SELECT COUNT(*) FROM media_assets"),
            "assets_indexed": one("SELECT COUNT(*) FROM media_assets WHERE transcribed_at IS NOT NULL "
                                  "AND shots_at IS NOT NULL"),
            "moments": one("SELECT COUNT(*) FROM moments"),
            "moments_labeled": one("SELECT COUNT(*) FROM moments WHERE status = 'labeled'"),
            "lessons": by_status,
        }
        return {"counts": counts, "storage": storage.usage(conn), "credentials": credentials(),
                "settings": settings_view(), "jobs": jobs.list_jobs(conn, limit=10)}
