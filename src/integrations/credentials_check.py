"""Diagnóstico de credenciales y entorno (`ylk doctor`).

Cada check hace UNA llamada mínima al servicio real y devuelve solo un
estado + detalle corto. Nunca imprime ni registra valores de las keys.

Estados: OK | INVALID | MISSING | WARN | ERROR
"""
from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import requests

T = 15


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""
    needed_for: str = ""


def _env(k: str) -> str:
    return (os.getenv(k) or "").strip()


def _missing(name: str, var: str, needed_for: str) -> Check:
    return Check(name, "MISSING", f"{var} vacío", needed_for)


def _http(name: str, needed_for: str, var: str, call: Callable[[str], requests.Response],
          ok: Callable[[requests.Response], bool] = lambda r: r.ok) -> Check:
    key = _env(var)
    if not key:
        return _missing(name, var, needed_for)
    try:
        r = call(key)
    except requests.RequestException as e:
        return Check(name, "ERROR", type(e).__name__, needed_for)
    if ok(r):
        return Check(name, "OK", str(r.status_code), needed_for)
    msg = ""
    try:
        body = r.json()
        err = body.get("error") if isinstance(body, dict) else None
        msg = (err.get("message") if isinstance(err, dict) else err) or body.get("Error") or ""
    except ValueError:
        pass
    return Check(name, "INVALID", f"{r.status_code} {str(msg)[:70]}".strip(), needed_for)


def check_api_keys() -> list[Check]:
    out = [
        _http("TMDB", "metadatos de obras", "TMDB_API_KEY",
              lambda k: requests.get("https://api.themoviedb.org/3/configuration", params={"api_key": k}, timeout=T)),
        _http("OMDb", "ratings (opcional)", "OMDB_API_KEY",
              lambda k: requests.get("https://www.omdbapi.com/", params={"apikey": k, "i": "tt0063350"}, timeout=T),
              lambda r: r.ok and r.json().get("Response") == "True"),
        _http("OpenSubtitles", "subtítulos (opcional; Whisper los reemplaza)", "OPENSUBTITLES_API_KEY",
              lambda k: requests.get("https://api.opensubtitles.com/api/v1/infos/formats",
                                     headers={"Api-Key": k, "User-Agent": "youlikeit v1.0"}, timeout=T)),
        _http("YouTube Data API key", "lectura de canal/analytics", "YOUTUBE_API_KEY",
              lambda k: requests.get("https://www.googleapis.com/youtube/v3/channels",
                                     params={"key": k, "id": _env("YOUTUBE_CHANNEL_ID"), "part": "id"}, timeout=T),
              lambda r: r.ok and bool(r.json().get("items"))),
        _http("Gemini", "LLM por API (cascada)", "GEMINI_API_KEY",
              lambda k: requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                                     params={"key": k}, timeout=T)),
        _http("Groq", "ASR por API + LLM por API", "GROQ_API_KEY",
              lambda k: requests.get("https://api.groq.com/openai/v1/models",
                                     headers={"Authorization": f"Bearer {k}"}, timeout=T)),
        _http("Hugging Face", "descarga de modelos con licencia", "HF_TOKEN",
              lambda k: requests.get("https://huggingface.co/api/whoami-v2",
                                     headers={"Authorization": f"Bearer {k}"}, timeout=T)),
        _http("Trakt", "trending (opcional)", "TRAKT_CLIENT_ID",
              lambda k: requests.get("https://api.trakt.tv/movies/trending", params={"limit": 1}, timeout=T,
                                     headers={"trakt-api-key": k, "trakt-api-version": "2"})),
    ]
    tk = "OK" if _env("TIKTOK_CLIENT_KEY") and _env("TIKTOK_CLIENT_SECRET") else "MISSING"
    out.append(Check("TikTok app (client key/secret)", tk,
                     "" if tk == "OK" else "TIKTOK_CLIENT_KEY/SECRET vacíos", "subir borradores a TikTok"))
    return out


def _client_secrets() -> dict:
    p = Path(_env("GOOGLE_CLIENT_SECRETS") or "client_secrets.json")
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return data.get("installed") or data.get("web") or {}


def check_youtube_oauth(token_paths: list[Path] | None = None) -> list[Check]:
    """Intenta refrescar cada token (sin guardarlo) para saber si sigue vivo."""
    app = _client_secrets()
    out = [Check("OAuth client (client_secrets.json)", "OK" if app else "MISSING",
                 app.get("project_id", "") if app else "falta client_secrets.json", "subir a YouTube")]
    if token_paths is None:
        out.append(check_youtube_studio(app))
    paths = token_paths if token_paths is not None else sorted(Path("tokens").glob("youtube_*.json"))
    for p in paths:                                  # tokens por persona del producto anterior, si quedan
        try:
            t = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            out.append(Check(f"OAuth {p.name}", "ERROR", type(e).__name__, "subir a YouTube"))
            continue
        out.append(_refresh_check(f"OAuth {p.name}", t, app))
    return out


def _refresh_check(name: str, t: dict, app: dict) -> Check:
    """Pide un access token con el refresh token (no lo guarda) para saber si sigue vivo."""
    cid = t.get("client_id") or app.get("client_id")
    secret = t.get("client_secret") or app.get("client_secret")
    if not t.get("refresh_token") or not cid:
        return Check(name, "INVALID", "sin refresh_token/client_id", "subir a YouTube")
    try:
        r = requests.post("https://oauth2.googleapis.com/token", timeout=T, data={
            "client_id": cid, "client_secret": secret, "refresh_token": t["refresh_token"],
            "grant_type": "refresh_token"})
        body = r.json()
    except (requests.RequestException, ValueError) as e:
        return Check(name, "ERROR", type(e).__name__, "subir a YouTube")
    if "access_token" in body:
        return Check(name, "OK", "refresh OK", "subir a YouTube")
    hint = " (app OAuth en 'Testing' vence tokens a 7 días → publicarla)" \
        if body.get("error") == "invalid_grant" else ""
    return Check(name, "INVALID", f"{body.get('error')}{hint}", "subir a YouTube")


def check_youtube_studio(app: dict) -> Check:
    """Token del estudio (tokens/youtube_studio.json.enc, cifrado con TOKEN_ENC_KEY)."""
    from apps.publish import youtube
    name = "YouTube del estudio"
    try:
        payload = youtube.load_token()
    except youtube.YouTubeError as e:
        return Check(name, "ERROR", str(e), "subir a YouTube")
    if not payload:
        return Check(name, "MISSING", "sin conectar: estudio → Revisión → Conectar YouTube", "subir a YouTube")
    c = _refresh_check(name, payload.get("credentials") or {}, app)
    if c.status != "OK":
        return c
    warning = payload.get("warning")
    return Check(name, "WARN" if warning else "OK",
                 (warning or f"canal: {payload.get('channel_title') or '?'}")[:160], "subir a YouTube")


def check_local_stack() -> list[Check]:
    out = []
    ffmpeg = shutil.which("ffmpeg")
    out.append(Check("ffmpeg", "OK" if ffmpeg else "MISSING", ffmpeg or "", "todo el ETL"))
    if ffmpeg:
        from utils.ffmpeg import has_nvenc
        out.append(Check("NVENC (h264_nvenc)", "OK" if has_nvenc() else "WARN",
                         "" if has_nvenc() else "render en CPU (libx264)", "render rápido"))
    from apps.media.transcribe import local_cuda_available
    out.append(Check("faster-whisper + CUDA", "OK" if local_cuda_available() else "WARN",
                     "" if local_cuda_available() else "ASR local no disponible (usar ASR_BACKEND=groq)",
                     "ASR local"))
    from integrations.ai import llm_json
    ok = llm_json.available("ollama")
    out.append(Check(f"Ollama ({llm_json.model_for('ollama')})", "OK" if ok else "WARN",
                     "" if ok else f"no responde o falta `ollama pull {llm_json.model_for('ollama')}`",
                     "LLM local"))
    movies = Path(_env("MOVIES_DIR") or "E:/movies")
    out.append(Check("MOVIES_DIR", "OK" if movies.is_dir() else "WARN",
                     str(movies) + ("" if movies.is_dir() else " no montado (USB desconectada?)"),
                     "biblioteca local"))
    return out


def check_stremio_addon() -> Check:
    """Addon de Stremio (opcional): manifest alcanzable y si sirve para buscar. Solo muestra el host."""
    from apps.media.stremio_addon import StremioAddonError, StremioAddonProvider
    name, needed = "Addon Stremio", "buscar fuentes en tu addon (opcional)"
    if not _env("STREMIO_ADDON_URL"):
        return _missing(name, "STREMIO_ADDON_URL", needed)
    try:
        prov = StremioAddonProvider()
        m = prov.manifest()
        searchable, imdb = bool(prov.search_catalogs()), prov.accepts_imdb()
    except StremioAddonError as e:
        return Check(name, "ERROR", str(e)[:160], needed)
    detail = f"{m.get('name') or m['id']} {m.get('version') or ''} en {prov.host}".replace("  ", " ")
    if not (searchable or imdb):
        return Check(name, "WARN", f"{detail}: sin catálogo con búsqueda ni IDs tt (no hay cómo buscar)", needed)
    if not prov.own:
        return Check(name, "WARN", f"{detail}: STREMIO_OWN_HOSTS vacío, solo se usarán enlaces de archive.org",
                     needed)
    return Check(name, "OK", detail, needed)


def run_all(*, network: bool = True) -> list[Check]:
    checks = check_local_stack()
    if network:
        checks += check_api_keys() + check_youtube_oauth() + [check_stremio_addon()]
    return checks
