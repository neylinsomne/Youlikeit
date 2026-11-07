"""
ex36 - Upload de Shorts a TikTok via Content Posting API (inbox flow).

El video llega al inbox de TikTok y el usuario lo edita desde el celular
(agrega cancion, texto, filtros) antes de publicar.

Requisitos:
  1. App en developers.tiktok.com con Content Posting activado
  2. Scope video.upload aprobado
  3. TIKTOK_CLIENT_KEY y TIKTOK_CLIENT_SECRET en .env
  4. Primera ejecucion: abre navegador para autorizar

Uso:
  python src/main.py ex36 --video outputs/video/finals/short_villain.mp4
  python src/main.py ex36 --video short.mp4 --persona deep_mind
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests

from core.config import Settings
from utils.logger import build_logger


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TIKTOK_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
TIKTOK_UPLOAD_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"
TIKTOK_STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"

REDIRECT_URI = "http://localhost:9876/callback"
SCOPES = "video.upload"


# ---------------------------------------------------------------------------
# Token management (per persona)
# ---------------------------------------------------------------------------

def _get_token_path(persona: str = "default") -> Path:
    """Token file per persona."""
    tokens_dir = Path("tokens")
    tokens_dir.mkdir(exist_ok=True)
    return tokens_dir / f"tiktok_{persona}.json"


def _load_token(persona: str = "default") -> dict | None:
    path = _get_token_path(persona)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("access_token"):
            return data
    except Exception:
        pass
    return None


def _save_token(data: dict, persona: str = "default"):
    path = _get_token_path(persona)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _refresh_token(token_data: dict, persona: str = "default") -> dict | None:
    """Refresh an expired access token."""
    client_key = os.getenv("TIKTOK_CLIENT_KEY", "")
    client_secret = os.getenv("TIKTOK_CLIENT_SECRET", "")
    refresh = token_data.get("refresh_token", "")

    if not all([client_key, client_secret, refresh]):
        return None

    resp = requests.post(TIKTOK_TOKEN_URL, json={
        "client_key": client_key,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh,
    }, timeout=15)

    if resp.status_code != 200:
        return None

    data = resp.json()
    if data.get("access_token"):
        _save_token(data, persona)
        return data
    return None


# ---------------------------------------------------------------------------
# OAuth flow (local server catches callback)
# ---------------------------------------------------------------------------

def authorize(persona: str = "default", log=None) -> dict | None:
    """
    Run OAuth flow: open browser, start local server to catch callback,
    exchange code for token.
    """
    client_key = os.getenv("TIKTOK_CLIENT_KEY", "")
    client_secret = os.getenv("TIKTOK_CLIENT_SECRET", "")

    if not client_key or not client_secret:
        msg = (
            "TIKTOK_CLIENT_KEY y TIKTOK_CLIENT_SECRET no estan en .env\n"
            "1. Crea app en https://developers.tiktok.com\n"
            "2. Agrega Content Posting con scope video.upload\n"
            "3. Agrega las keys al .env"
        )
        if log:
            log.error(msg)
        print(f"\n  ERROR: {msg}\n")
        return None

    import urllib.parse
    import threading
    from http.server import HTTPServer, BaseHTTPRequestHandler

    # Build authorization URL
    params = urllib.parse.urlencode({
        "client_key": client_key,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "response_type": "code",
        "state": f"persona_{persona}",
    })
    auth_url = f"{TIKTOK_AUTH_URL}?{params}"

    # Capture the auth code via local server
    auth_code = [None]

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            auth_code[0] = qs.get("code", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>OK! Puedes cerrar esta ventana.</h1>")

        def log_message(self, *args):
            pass  # Silence server logs

    server = HTTPServer(("localhost", 9876), CallbackHandler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()

    print(f"\n  Abre esta URL para autorizar TikTok ({persona}):")
    print(f"  {auth_url}\n")

    # Try to open browser automatically
    try:
        import webbrowser
        webbrowser.open(auth_url)
    except Exception:
        pass

    thread.join(timeout=120)
    server.server_close()

    if not auth_code[0]:
        if log:
            log.error("No se recibio el codigo de autorizacion")
        return None

    # Exchange code for token
    resp = requests.post(TIKTOK_TOKEN_URL, json={
        "client_key": client_key,
        "client_secret": client_secret,
        "code": auth_code[0],
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    }, timeout=15)

    if resp.status_code != 200:
        if log:
            log.error(f"Token exchange failed: {resp.status_code} {resp.text[:200]}")
        return None

    data = resp.json()
    if data.get("access_token"):
        _save_token(data, persona)
        if log:
            log.info(f"TikTok authorized for persona '{persona}'")
        return data

    if log:
        log.error(f"Token response has no access_token: {data}")
    return None


def get_access_token(persona: str = "default", log=None) -> str | None:
    """Get a valid access token, refreshing or re-authorizing if needed."""
    token_data = _load_token(persona)

    if token_data:
        expires_in = token_data.get("expires_in", 0)
        created_at = token_data.get("created_at", 0)
        if created_at and time.time() - created_at > expires_in - 300:
            # Token expired or about to — refresh
            refreshed = _refresh_token(token_data, persona)
            if refreshed:
                return refreshed["access_token"]
            # Refresh failed — need re-auth
            token_data = None
        else:
            return token_data["access_token"]

    # No valid token — run OAuth flow
    new_token = authorize(persona, log)
    if new_token:
        new_token["created_at"] = time.time()
        _save_token(new_token, persona)
        return new_token["access_token"]

    return None


# ---------------------------------------------------------------------------
# Upload to inbox
# ---------------------------------------------------------------------------

def upload_to_inbox(
    video_path: str,
    access_token: str,
    log=None,
) -> dict:
    """
    Upload a video to TikTok's inbox flow.
    The user receives a notification and can edit (add music, text, etc.)
    before publishing from the mobile app.
    """
    video = Path(video_path)
    if not video.exists():
        return {"ok": False, "error": f"Video not found: {video_path}"}

    video_size = video.stat().st_size

    # Step 1: Initialize upload
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
    }

    init_body = {
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": video_size,
            "chunk_size": video_size,  # Single chunk for files <64MB
            "total_chunk_count": 1,
        }
    }

    resp = requests.post(TIKTOK_UPLOAD_INIT_URL, headers=headers, json=init_body, timeout=15)

    if resp.status_code != 200:
        return {"ok": False, "error": f"Init failed: {resp.status_code} {resp.text[:300]}"}

    data = resp.json()
    if data.get("error", {}).get("code") != "ok":
        return {"ok": False, "error": f"Init error: {data.get('error', {})}"}

    publish_id = data["data"]["publish_id"]
    upload_url = data["data"]["upload_url"]

    if log:
        log.info(f"Upload initialized: {publish_id}")

    # Step 2: Upload video file
    with open(video_path, "rb") as f:
        video_bytes = f.read()

    upload_headers = {
        "Content-Type": "video/mp4",
        "Content-Length": str(video_size),
        "Content-Range": f"bytes 0-{video_size - 1}/{video_size}",
    }

    resp = requests.put(upload_url, headers=upload_headers, data=video_bytes, timeout=120)

    if resp.status_code not in (200, 201):
        return {"ok": False, "error": f"Upload failed: {resp.status_code} {resp.text[:300]}"}

    if log:
        log.info("Video uploaded, waiting for processing...")

    # Step 3: Poll status
    for i in range(30):
        time.sleep(2)
        status_resp = requests.post(
            TIKTOK_STATUS_URL,
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json={"publish_id": publish_id},
            timeout=10,
        )
        if status_resp.status_code == 200:
            status_data = status_resp.json()
            status = status_data.get("data", {}).get("status", "")
            if log:
                log.info(f"  Status ({i+1}/30): {status}")
            if status == "SEND_TO_USER_INBOX":
                return {
                    "ok": True,
                    "publish_id": publish_id,
                    "status": status,
                    "message": "Video enviado al inbox de TikTok. Abre la app para editar y publicar.",
                }
            if status in ("FAILED", "PUBLISH_CANCELLED"):
                return {"ok": False, "error": f"Upload failed with status: {status}",
                        "details": status_data}

    return {"ok": True, "publish_id": publish_id, "status": "processing",
            "message": "Video subido. Revisa tu inbox de TikTok en unos minutos."}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(
    settings: Settings,
    video: str = "",
    persona: str = "default",
) -> Path:
    log = build_logger("ex36", settings.output_dir / "logs" / "ex36.log")

    # Find video
    video_path = video
    if not video_path:
        # Try latest final video
        finals_dir = settings.output_dir / "video" / "finals"
        if finals_dir.exists():
            videos = sorted(finals_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
            if videos:
                video_path = str(videos[0])

    if not video_path or not Path(video_path).exists():
        log.error("No video file found. Pass --video or run ex11 first.")
        rp = settings.output_dir / "logs" / "ex36_report.txt"
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text("ex36 - ERROR: No video file\n", encoding="utf-8")
        return rp

    log.info(f"Video: {video_path}")
    log.info(f"Persona: {persona}")

    # Get access token
    access_token = get_access_token(persona, log)
    if not access_token:
        rp = settings.output_dir / "logs" / "ex36_report.txt"
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(
            "ex36 - ERROR: No TikTok access token.\n"
            "Set TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET in .env,\n"
            "then run: python src/main.py ex36 --persona deep_mind\n",
            encoding="utf-8",
        )
        return rp

    # Upload
    result = upload_to_inbox(video_path, access_token, log)

    # Report
    rp = settings.output_dir / "logs" / "ex36_tiktok_report.txt"
    rp.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "ex36 - TikTok Upload Report",
        "=" * 40,
        f"Video: {video_path}",
        f"Persona: {persona}",
        f"Result: {'OK' if result.get('ok') else 'FAILED'}",
        f"Publish ID: {result.get('publish_id', 'N/A')}",
        f"Status: {result.get('status', 'N/A')}",
        f"Message: {result.get('message', result.get('error', 'N/A'))}",
    ]
    rp.write_text("\n".join(lines), encoding="utf-8")

    if result.get("ok"):
        log.info(f"OK: {result.get('message')}")
    else:
        log.error(f"FAILED: {result.get('error')}")

    return rp
