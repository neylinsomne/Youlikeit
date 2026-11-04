"""Cliente del puente de publicación de web/ (contrato en docs/architecture/STUDIO_API.md).

    GET  {WEB_BASE_URL}/api/studio/accounts                  → cuentas de TikTok conectadas
    POST {WEB_BASE_URL}/api/studio/tiktok/init               → {publish_id, upload_url}
    PUT  upload_url  (bytes del MP4, directo a TikTok, 1 trozo ≤ 64 MB)
    GET  {WEB_BASE_URL}/api/studio/tiktok/status/{id}         → hasta SEND_TO_USER_INBOX | FAILED

Auth del puente: `Authorization: Bearer ${STUDIO_API_KEY}`. El `upload_url`
solo se acepta si es https en *.tiktokapis.com: el estudio nunca sube el
video a otro host aunque el puente esté comprometido.
"""
from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote, urlparse

import requests

log = logging.getLogger(__name__)

MAX_SINGLE_CHUNK = 64 * 1024 * 1024
UPLOAD_HOST_SUFFIX = ".tiktokapis.com"
FINAL_STATUSES = {"SEND_TO_USER_INBOX", "PUBLISH_COMPLETE", "FAILED"}
TIMEOUT = 30


class BridgeError(RuntimeError):
    """El puente o TikTok fallaron. status_code = HTTP del puente (si hubo respuesta)."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class BridgeNotConfigured(BridgeError):
    """Faltan WEB_BASE_URL o STUDIO_API_KEY en el .env del estudio."""


def _config() -> tuple[str, str]:
    base = (os.getenv("WEB_BASE_URL") or "").strip().rstrip("/")
    key = (os.getenv("STUDIO_API_KEY") or "").strip()
    if not base or not key:
        raise BridgeNotConfigured("Configura WEB_BASE_URL y STUDIO_API_KEY en el .env del estudio")
    parsed = urlparse(base)
    local = parsed.hostname in ("127.0.0.1", "localhost")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
        raise BridgeNotConfigured("WEB_BASE_URL debe ser https (http solo para 127.0.0.1/localhost)")
    return base, key


def _detail(resp: requests.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return f"HTTP {resp.status_code}"
    detail = body.get("detail") if isinstance(body, dict) else None
    return str(detail) if detail else f"HTTP {resp.status_code}"


def _call(method: str, path: str, *, json: dict | None = None, timeout: float = TIMEOUT) -> dict:
    base, key = _config()
    try:
        resp = requests.request(method, f"{base}{path}", json=json, timeout=timeout,
                                headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    except requests.RequestException as e:
        raise BridgeError(f"El puente no responde: {type(e).__name__}") from e
    if resp.status_code >= 400:
        raise BridgeError(f"Puente {path}: {_detail(resp)}", resp.status_code)
    try:
        return resp.json()
    except ValueError as e:
        raise BridgeError(f"Puente {path}: respuesta no JSON", resp.status_code) from e


def list_accounts() -> list[dict]:
    """[{open_id, display_name}] de las cuentas de TikTok conectadas en el sitio."""
    data = _call("GET", "/api/studio/accounts")
    return [{"open_id": a.get("open_id"), "display_name": a.get("display_name")}
            for a in data.get("accounts") or [] if a.get("open_id")]


def init_upload(open_id: str, video_size: int, lesson_ref: str) -> dict:
    data = _call("POST", "/api/studio/tiktok/init",
                 json={"open_id": open_id, "video_size": int(video_size), "lesson_ref": lesson_ref})
    if not data.get("publish_id") or not data.get("upload_url"):
        raise BridgeError("El puente no devolvió publish_id/upload_url")
    return data


def check_upload_url(url: str) -> None:
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if p.scheme != "https" or not (host.endswith(UPLOAD_HOST_SUFFIX) or host == UPLOAD_HOST_SUFFIX[1:]):
        raise BridgeError(f"upload_url rechazada (se espera https://*{UPLOAD_HOST_SUFFIX})")


def put_video(upload_url: str, data: bytes, *, timeout: float = 600) -> None:
    """PUT directo a TikTok: un solo trozo con Content-Range."""
    check_upload_url(upload_url)
    size = len(data)
    try:
        resp = requests.put(upload_url, data=data, timeout=timeout,
                            headers={"Content-Type": "video/mp4", "Content-Length": str(size),
                                     "Content-Range": f"bytes 0-{size - 1}/{size}"})
    except requests.RequestException as e:
        raise BridgeError(f"Subida a TikTok falló: {type(e).__name__}") from e
    if resp.status_code not in (200, 201, 206):
        raise BridgeError(f"Subida a TikTok falló: HTTP {resp.status_code}", resp.status_code)


def fetch_status(publish_id: str) -> str:
    return str(_call("GET", f"/api/studio/tiktok/status/{quote(publish_id, safe='')}").get("status") or "")


def send_draft(video_path: str | Path, open_id: str, lesson_ref: str, poll: bool = True, *,
               poll_interval: float = 5.0, poll_timeout: float = 300.0,
               sleep: Callable[[float], None] = time.sleep,
               progress: Callable[[str, int, str], None] | None = None) -> dict:
    """Sube el MP4 como borrador al inbox de la cuenta. Devuelve {publish_id, status}.

    status final: SEND_TO_USER_INBOX (listo en la app), PUBLISH_COMPLETE, FAILED, o el
    último visto si se agotó poll_timeout (p. ej. PROCESSING_UPLOAD).
    """
    data = Path(video_path).read_bytes()
    size = len(data)
    if size == 0:
        raise BridgeError("El video está vacío")
    if size > MAX_SINGLE_CHUNK:
        raise BridgeError(f"El video pesa {size / 1e6:.1f} MB: el máximo en un trozo es 64 MB")
    if progress:
        progress("init", 10, "pidiendo upload_url al puente")
    init = init_upload(open_id, size, lesson_ref)
    publish_id = init["publish_id"]
    if progress:
        progress("upload", 30, f"{size / 1e6:.1f} MB → TikTok")
    put_video(init["upload_url"], data)
    status = "PROCESSING_UPLOAD"
    if poll:
        deadline = time.monotonic() + poll_timeout
        while True:
            status = fetch_status(publish_id) or status
            if progress:
                progress("status", 80, status)
            if status in FINAL_STATUSES or time.monotonic() >= deadline:
                break
            sleep(poll_interval)
    log.info("TikTok %s → %s", publish_id, status)
    return {"publish_id": publish_id, "status": status}
