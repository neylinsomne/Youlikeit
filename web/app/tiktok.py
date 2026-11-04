"""TikTok Login Kit (OAuth v2, web) + perfil básico + revocación.

Scopes pedidos: user.info.basic y video.upload (borradores). Nada más.
Docs: https://developers.tiktok.com/doc/oauth-user-access-token-management
"""
from __future__ import annotations

import os
from urllib.parse import urlencode

import httpx

AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
REVOKE_URL = "https://open.tiktokapis.com/v2/oauth/revoke/"
USER_INFO_URL = "https://open.tiktokapis.com/v2/user/info/"
SCOPES = ("user.info.basic", "video.upload")


class TikTokError(RuntimeError):
    pass


def client_key() -> str:
    return os.getenv("TIKTOK_CLIENT_KEY", "")


def configured() -> bool:
    return bool(client_key() and os.getenv("TIKTOK_CLIENT_SECRET"))


def redirect_uri() -> str:
    base = os.getenv("PUBLIC_BASE_URL", "http://localhost:8080").rstrip("/")
    return f"{base}/auth/tiktok/callback"


def authorize_url(state: str) -> str:
    return AUTHORIZE_URL + "?" + urlencode({
        "client_key": client_key(), "scope": ",".join(SCOPES), "response_type": "code",
        "redirect_uri": redirect_uri(), "state": state})


def exchange_code(code: str) -> dict:
    resp = httpx.post(TOKEN_URL, timeout=20, headers={"Content-Type": "application/x-www-form-urlencoded"},
                      data={"client_key": client_key(), "client_secret": os.getenv("TIKTOK_CLIENT_SECRET", ""),
                            "code": code, "grant_type": "authorization_code", "redirect_uri": redirect_uri()})
    data = resp.json()
    if resp.status_code != 200 or "access_token" not in data:
        raise TikTokError(data.get("error_description") or data.get("error") or f"HTTP {resp.status_code}")
    return data


def user_info(access_token: str) -> dict:
    resp = httpx.get(USER_INFO_URL, timeout=20, params={"fields": "open_id,avatar_url,display_name"},
                     headers={"Authorization": f"Bearer {access_token}"})
    data = resp.json()
    err = (data.get("error") or {})
    if resp.status_code != 200 or err.get("code") not in (None, "ok"):
        raise TikTokError(err.get("message") or f"HTTP {resp.status_code}")
    return (data.get("data") or {}).get("user") or {}


def revoke(access_token: str) -> None:
    httpx.post(REVOKE_URL, timeout=20, headers={"Content-Type": "application/x-www-form-urlencoded"},
               data={"client_key": client_key(), "client_secret": os.getenv("TIKTOK_CLIENT_SECRET", ""),
                     "token": access_token})


# ── Token refresh + Content Posting API (borrador al inbox) ─────────────────
INBOX_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"
STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
MAX_SINGLE_CHUNK = 64 * 1024 * 1024        # hasta 64 MB se sube en un solo trozo
FRIENDLY_ERRORS = {
    "spam_risk_too_many_pending_share": "TikTok allows at most 5 pending drafts per 24 hours. "
                                        "Open your TikTok inbox, finish or discard a draft, and try again.",
    "scope_not_authorized": "The video.upload permission was not granted. Reconnect TikTok and accept it.",
    "access_token_invalid": "Your TikTok session expired. Please reconnect.",
    "rate_limit_exceeded": "Too many requests. Please wait a minute and try again.",
    "url_ownership_unverified": "This site is not verified in the TikTok app settings.",
}


def refresh(refresh_token: str) -> dict:
    resp = httpx.post(TOKEN_URL, timeout=20, headers={"Content-Type": "application/x-www-form-urlencoded"},
                      data={"client_key": client_key(), "client_secret": os.getenv("TIKTOK_CLIENT_SECRET", ""),
                            "grant_type": "refresh_token", "refresh_token": refresh_token})
    data = resp.json()
    if resp.status_code != 200 or "access_token" not in data:
        raise TikTokError(data.get("error_description") or data.get("error") or f"HTTP {resp.status_code}")
    return data


def _api_error(resp: httpx.Response) -> str | None:
    try:
        err = resp.json().get("error") or {}
    except ValueError:
        return f"http_{resp.status_code}"
    code = err.get("code")
    return None if code in (None, "ok") and resp.status_code < 400 else (code or f"http_{resp.status_code}")


def upload_draft(access_token: str, video_path, *, timeout: float = 300) -> str:
    """Sube un MP4 al inbox del creador como borrador. Devuelve publish_id."""
    from pathlib import Path
    data = Path(video_path).read_bytes()
    size = len(data)
    if size > MAX_SINGLE_CHUNK:
        raise TikTokError("video too large for single-chunk upload")
    init = httpx.post(INBOX_INIT_URL, timeout=30,
                      headers={"Authorization": f"Bearer {access_token}",
                               "Content-Type": "application/json; charset=UTF-8"},
                      json={"source_info": {"source": "FILE_UPLOAD", "video_size": size,
                                            "chunk_size": size, "total_chunk_count": 1}})
    code = _api_error(init)
    if code:
        raise TikTokError(code)
    payload = init.json()["data"]
    put = httpx.put(payload["upload_url"], content=data, timeout=timeout,
                    headers={"Content-Type": "video/mp4", "Content-Length": str(size),
                             "Content-Range": f"bytes 0-{size - 1}/{size}"})
    if put.status_code not in (200, 201):
        raise TikTokError(f"upload_failed_http_{put.status_code}")
    return payload["publish_id"]


def fetch_status(access_token: str, publish_id: str) -> dict:
    resp = httpx.post(STATUS_URL, timeout=20,
                      headers={"Authorization": f"Bearer {access_token}",
                               "Content-Type": "application/json; charset=UTF-8"},
                      json={"publish_id": publish_id})
    code = _api_error(resp)
    if code:
        raise TikTokError(code)
    return resp.json().get("data") or {}
