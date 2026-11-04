"""YouLikeIt — sitio público: explorar películas por emoción + estudio de creadores.

Rutas
  /                      inicio (qué es, cómo funciona)
  /explore               guía de emociones + biblioteca de películas
  /explore/{emotion}     una emoción: qué es, cómo la muestra el cine, pausa, tropos, películas
  /studio                conectar TikTok (Login Kit) y ver la cuenta conectada
  /auth/tiktok/*         OAuth (login, callback, disconnect)
  /terms /privacy /contact /healthz
"""
from __future__ import annotations

import json
import os
import secrets
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app import store, tiktok
from app.content import EMOTION_BY_ID, EMOTIONS

BASE = Path(__file__).resolve().parent
CONTACT = os.getenv("CONTACT_EMAIL", "contact@vara-alta.lat")
LAST_UPDATED = "November 3, 2026"

app = FastAPI(title="YouLikeIt", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET") or secrets.token_hex(32),
    https_only=os.getenv("PUBLIC_BASE_URL", "").startswith("https"),
    same_site="lax", max_age=60 * 60 * 24 * 14,
)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")


def load_catalog() -> dict:
    path = BASE / "data" / "catalog.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"tropes": {}, "films": []}


CATALOG = load_catalog()
EMOTION_COUNTS = {e["id"]: sum(e["id"] in f.get("emotions", []) for f in CATALOG["films"]) for e in EMOTIONS}


def render(request: Request, name: str, **ctx):
    return templates.TemplateResponse(request, name, {
        "year": datetime.now().year, "contact": CONTACT, "last_updated": LAST_UPDATED,
        "emotions": EMOTIONS, "films": CATALOG["films"], "tropes": CATALOG["tropes"],
        "emotion_counts": EMOTION_COUNTS, **ctx})


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/")
def home(request: Request):
    return render(request, "home.html")


@app.get("/explore")
def explore(request: Request):
    return render(request, "explore.html")


@app.get("/explore/{emotion_id}")
def emotion(request: Request, emotion_id: str):
    emo = EMOTION_BY_ID.get(emotion_id)
    if emo is None:
        raise HTTPException(404)
    films = [f for f in CATALOG["films"] if emotion_id in f.get("emotions", [])]
    return render(request, "emotion.html", emo=emo, emo_films=films)


@app.get("/terms")
@app.get("/terms.html")
def terms(request: Request):
    return render(request, "terms.html")


@app.get("/privacy")
@app.get("/privacy.html")
def privacy(request: Request):
    return render(request, "privacy.html")


@app.get("/contact")
def contact(request: Request):
    return render(request, "contact.html")


# ── Studio + TikTok Login Kit ───────────────────────────────────────


@app.get("/studio")
def studio(request: Request):
    account, avatar, notice = None, None, request.query_params.get("notice")
    open_id = request.session.get("open_id")
    if open_id:
        account = store.get_account(open_id)
        if account is None:
            request.session.pop("open_id", None)
        else:
            try:
                avatar = tiktok.user_info(account["access_token"]).get("avatar_url")
            except Exception:  # noqa: BLE001 — el avatar es opcional (no se almacena)
                avatar = None
    return render(request, "studio.html", account=account, avatar=avatar, notice=notice,
                  tiktok_ready=tiktok.configured(), scopes=tiktok.SCOPES)


@app.get("/auth/tiktok/login")
def tiktok_login(request: Request):
    if not tiktok.configured():
        return RedirectResponse("/studio?notice=not_configured", status_code=303)
    state = secrets.token_urlsafe(24)
    request.session["oauth_state"] = state
    return RedirectResponse(tiktok.authorize_url(state), status_code=303)


@app.get("/auth/tiktok/callback")
def tiktok_callback(request: Request, code: str | None = None, state: str | None = None,
                    error: str | None = None):
    expected = request.session.pop("oauth_state", None)
    if error:
        return RedirectResponse("/studio?notice=denied", status_code=303)
    if not code or not state or not expected or not secrets.compare_digest(state, expected):
        return RedirectResponse("/studio?notice=invalid_state", status_code=303)
    try:
        token = tiktok.exchange_code(code)
        user = tiktok.user_info(token["access_token"])
    except tiktok.TikTokError:
        return RedirectResponse("/studio?notice=tiktok_error", status_code=303)
    open_id = user.get("open_id") or token.get("open_id")
    store.save_account(open_id, user.get("display_name"), token)
    request.session["open_id"] = open_id
    return RedirectResponse("/studio?notice=connected", status_code=303)


@app.post("/auth/tiktok/disconnect")
def tiktok_disconnect(request: Request):
    open_id = request.session.pop("open_id", None)
    if open_id:
        account = store.get_account(open_id)
        if account:
            try:
                tiktok.revoke(account["access_token"])
            except Exception:  # noqa: BLE001 — igual se borra localmente
                pass
        store.delete_account(open_id)
    return RedirectResponse("/studio?notice=disconnected", status_code=303)
