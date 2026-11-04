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
