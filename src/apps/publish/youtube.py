"""YouTube desde el estudio: OAuth de app instalada + subida resumible.

    auth_url()          → URL de consentimiento de Google (PKCE + state de un solo uso)
    handle_callback()   ← GET /api/publish/youtube/callback?state&code (en 127.0.0.1)
    status()            → {"connected", "channel_title"} SIN red (lee el token cifrado)
    upload(...)         → {"video_id", "url"}: privado por defecto, publishAt opcional

Tokens: tokens/youtube_studio.json.enc, cifrados con Fernet (TOKEN_ENC_KEY del
.env local). Nunca se escriben en claro ni se imprimen.
Redirect: http://127.0.0.1:{STUDIO_PORT}/api/publish/youtube/callback (Google
acepta loopback http para clientes "Aplicación de escritorio").
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from collections.abc import Callable
from datetime import datetime, UTC
from pathlib import Path

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.readonly"]
CATEGORY_EDUCATION = "27"
PRIVACY = ("private", "unlisted", "public")
SHORTS_MAX_S = 60
STATE_TTL_S = 600
CHUNK = 8 * 1024 * 1024


class YouTubeError(RuntimeError):
    """Falla de Google/YouTube (red, API, token revocado)."""


class YouTubeNotConfigured(YouTubeError):
    """Falta client_secrets.json o TOKEN_ENC_KEY."""


class YouTubeNotConnected(YouTubeError):
    """No hay token guardado: primero GET /api/publish/youtube/connect."""


class YouTubeAuthError(YouTubeError):
    """state inválido / vencido o Google devolvió error en el callback."""


# ── configuración ───────────────────────────────────────────────────


def token_path() -> Path:
    return Path(os.getenv("TOKENS_DIR", "tokens")) / "youtube_studio.json.enc"


def client_secrets_path() -> Path:
    return Path(os.getenv("GOOGLE_CLIENT_SECRETS") or "client_secrets.json")


def redirect_uri() -> str:
    return f"http://127.0.0.1:{int(os.getenv('STUDIO_PORT') or 8001)}/api/publish/youtube/callback"


def _fernet():
    from cryptography.fernet import Fernet
    key = (os.getenv("TOKEN_ENC_KEY") or "").strip()
    if not key:
        raise YouTubeNotConfigured(
            "Falta TOKEN_ENC_KEY. Genera una con: python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\" y guárdala en el .env")
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as e:
        raise YouTubeNotConfigured("TOKEN_ENC_KEY no es una clave Fernet válida") from e


def _client_config() -> dict:
    path = client_secrets_path()
    if not path.exists():
        raise YouTubeNotConfigured(f"Falta {path.name} (GOOGLE_CLIENT_SECRETS): crea un cliente OAuth "
                                   "de tipo 'Aplicación de escritorio' en Google Cloud")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise YouTubeNotConfigured(f"{path.name} ilegible") from e
    if not (data.get("installed") or data.get("web")):
        raise YouTubeNotConfigured(f"{path.name} no es un client_secrets de OAuth")
    return data


# ── almacenamiento cifrado ──────────────────────────────────────────


def save_token(payload: dict) -> None:
    path = token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = _fernet().encrypt(json.dumps(payload).encode("utf-8"))
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(blob)
    os.replace(tmp, path)


def load_token() -> dict | None:
    """Payload descifrado ({credentials, channel_title, ...}) o None si no hay token."""
    path = token_path()
    if not path.exists():
        return None
    from cryptography.fernet import InvalidToken
    try:
        return json.loads(_fernet().decrypt(path.read_bytes()).decode("utf-8"))
    except (InvalidToken, ValueError) as e:
        raise YouTubeNotConfigured("No se pudo descifrar el token de YouTube (¿cambió TOKEN_ENC_KEY?)") from e


def status() -> dict:
    """Sin red: ¿hay token con refresh_token? + título del canal guardado al conectar."""
    try:
        payload = load_token()
    except YouTubeError as e:
        return {"connected": False, "channel_title": None, "detail": str(e)}
    if not payload or not (payload.get("credentials") or {}).get("refresh_token"):
        return {"connected": False, "channel_title": None}
    return {"connected": True, "channel_title": payload.get("channel_title")}


def disconnect() -> None:
    token_path().unlink(missing_ok=True)


# ── OAuth (app instalada, loopback) ─────────────────────────────────

_pending: dict[str, tuple[str | None, float]] = {}
_pending_lock = threading.Lock()


def _make_flow(*, state: str | None = None, code_verifier: str | None = None):
    from google_auth_oauthlib.flow import Flow
    kw = {"redirect_uri": redirect_uri()}
    if state:
        kw["state"] = state
    if code_verifier:
        kw["code_verifier"] = code_verifier
    return Flow.from_client_config(_client_config(), scopes=SCOPES, **kw)


def auth_url() -> str:
    """URL de consentimiento. Guarda state → code_verifier (un solo uso, 10 min)."""
    _fernet()                                    # sin clave no tiene sentido pedir el token
    flow = _make_flow()
    url, state = flow.authorization_url(access_type="offline", prompt="consent")
    now = time.monotonic()
    with _pending_lock:
        for s in [s for s, (_, t) in _pending.items() if now - t > STATE_TTL_S]:
            _pending.pop(s, None)
        _pending[state] = (getattr(flow, "code_verifier", None), now)
    return url


def handle_callback(*, state: str | None, code: str | None, error: str | None = None) -> dict:
    """Canjea el code por tokens, los cifra y guarda. Devuelve status()."""
    with _pending_lock:
        pending = _pending.pop(state or "", None)
    if pending is None or time.monotonic() - pending[1] > STATE_TTL_S:
        raise YouTubeAuthError("state inválido o vencido: vuelve a conectar desde el estudio")
    if error or not code:
        raise YouTubeAuthError(f"Google no autorizó: {error or 'sin code'}")
    os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")   # Google puede sumar scopes ya concedidos
    flow = _make_flow(state=state, code_verifier=pending[0])
    try:
        flow.fetch_token(code=code)
    except Exception as e:  # noqa: BLE001 — oauthlib/requests: cualquier falla es "no se pudo canjear"
        raise YouTubeError(f"No se pudo canjear el code: {type(e).__name__}") from e
    creds = flow.credentials
    payload = {"credentials": json.loads(creds.to_json()), "connected_at": _now_iso()}
    try:
        ch = _build_service(creds).channels().list(part="snippet", mine=True).execute()
        item = (ch.get("items") or [{}])[0]
        payload["channel_id"] = item.get("id")
        payload["channel_title"] = (item.get("snippet") or {}).get("title")
    except Exception as e:  # noqa: BLE001 — el título es cosmético; el token ya sirve
        log.warning("No se pudo leer el canal: %s", type(e).__name__)
    save_token(payload)
    return status()


# ── subida ──────────────────────────────────────────────────────────


def _build_service(creds):
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def load_credentials():
    """Credenciales vigentes (refresca y vuelve a guardar si vencieron)."""
    payload = load_token()
    info = (payload or {}).get("credentials") or {}
    if not info.get("refresh_token"):
        raise YouTubeNotConnected("YouTube no está conectado: usa Conectar YouTube en el estudio")
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    creds = Credentials.from_authorized_user_info(info, SCOPES)
    if not creds.valid:
        try:
            creds.refresh(Request())
        except Exception as e:  # noqa: BLE001 — RefreshError/TransportError
            raise YouTubeError(f"No se pudo refrescar el token ({type(e).__name__}): reconecta YouTube") from e
        payload["credentials"] = json.loads(creds.to_json())
        save_token(payload)
    return creds


def parse_publish_at(value: str | None) -> str | None:
    """ISO-8601 → RFC3339 UTC 'YYYY-MM-DDTHH:MM:SSZ'. Debe ser futuro."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as e:
        raise ValueError(f"publish_at inválido: {value!r} (usa ISO-8601, p. ej. 2026-11-05T15:00:00Z)") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    if dt <= datetime.now(UTC):
        raise ValueError("publish_at debe ser una fecha futura")
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def shorts_title(title: str, duration_s: float | None) -> str:
    """≤ 100 caracteres, sin < > (YouTube los rechaza) y con #Shorts si dura ≤ 60 s."""
    title = re.sub(r"[<>]", "", " ".join((title or "").split())) or "YouLikeIt"
    if duration_s is not None and duration_s <= SHORTS_MAX_S and "#shorts" not in title.lower():
        title = f"{title[:100 - len(' #Shorts')].rstrip()} #Shorts"
    return title[:100]


def build_body(*, title: str, description: str, tags: list[str] | None, privacy: str,
               publish_at: str | None, duration_s: float | None, category_id: str = CATEGORY_EDUCATION) -> dict:
    if privacy not in PRIVACY:
        raise ValueError(f"privacy inválida: {privacy!r} (usa {', '.join(PRIVACY)})")
    publish_at = parse_publish_at(publish_at)
    if publish_at and privacy != "private":
        raise ValueError("publish_at requiere privacy=private (YouTube lo publica a esa hora)")
    status_ = {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}
    if publish_at:
        status_["publishAt"] = publish_at
    return {"snippet": {"title": shorts_title(title, duration_s), "description": (description or "")[:5000],
                        "tags": [t for t in (tags or []) if t][:30], "categoryId": category_id},
            "status": status_}


def upload(video_path: str | Path, *, title: str, description: str = "", tags: list[str] | None = None,
           privacy: str = "private", publish_at: str | None = None, duration_s: float | None = None,
           progress: Callable[[str, int, str], None] | None = None) -> dict:
    """Subida resumible. Devuelve {video_id, url, privacy, publish_at}."""
    body = build_body(title=title, description=description, tags=tags, privacy=privacy,
                      publish_at=publish_at, duration_s=duration_s)
    creds = load_credentials()
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload
    media = MediaFileUpload(str(video_path), mimetype="video/mp4", chunksize=CHUNK, resumable=True)
    try:
        request = _build_service(creds).videos().insert(part="snippet,status", body=body, media_body=media)
        response = None
        while response is None:
            st, response = request.next_chunk()
            if st and progress:
                progress("upload", int(10 + 85 * st.progress()), f"{st.progress():.0%}")
    except HttpError as e:
        raise YouTubeError(f"YouTube rechazó la subida: HTTP {getattr(e.resp, 'status', '?')}") from e
    video_id = response.get("id")
    if not video_id:
        raise YouTubeError("YouTube no devolvió el id del video")
    return {"video_id": video_id, "url": f"https://youtu.be/{video_id}",
            "privacy": privacy, "publish_at": body["status"].get("publishAt")}


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
