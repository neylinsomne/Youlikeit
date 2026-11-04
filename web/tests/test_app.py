"""Sitio público + estudio: páginas, requisitos de revisión de TikTok y OAuth seguro."""
from __future__ import annotations

import re
import sqlite3
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TOKEN_ENC_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://youlikeit.example")
    monkeypatch.delenv("TIKTOK_CLIENT_KEY", raising=False)
    monkeypatch.delenv("TIKTOK_CLIENT_SECRET", raising=False)
    from app.main import app
    return TestClient(app, base_url="https://youlikeit.example")


PAGES = ["/", "/explore", "/explore/fear", "/explore/grief", "/terms", "/privacy", "/contact", "/studio"]


@pytest.mark.parametrize("path", PAGES)
def test_pages_render_with_visible_terms_and_privacy_links(client, path):
    r = client.get(path)
    assert r.status_code == 200
    header = r.text.split("</header>")[0]
    assert 'href="/terms"' in header and 'href="/privacy"' in header     # visibles sin abrir un menú


def test_unknown_emotion_404_and_health(client):
    assert client.get("/explore/no-such-emotion").status_code == 404
    assert client.get("/healthz").json() == {"ok": True}
    assert client.get("/docs").status_code == 404                        # sin docs públicas de la API


def test_privacy_and_terms_content(client):
    privacy = client.get("/privacy").text
    terms = client.get("/terms").text
    for scope in ("user.info.basic", "video.upload"):
        assert scope in privacy
    assert "encrypted" in privacy and "drafts" in privacy
    assert "personal content creation" not in (privacy + terms).lower()  # motivo de rechazo anterior
    assert client.get("/terms.html").status_code == 200                  # URLs viejas siguen vivas


def test_explore_lists_library_films(client):
    html = client.get("/explore").text
    assert "Night of the Living Dead" in html and "Public domain" in html


def test_login_without_credentials_degrades_gracefully(client):
    r = client.get("/auth/tiktok/login", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/studio?notice=not_configured"


@pytest.fixture
def tiktok_client(client, monkeypatch):
    monkeypatch.setenv("TIKTOK_CLIENT_KEY", "ck_test")
    monkeypatch.setenv("TIKTOK_CLIENT_SECRET", "cs_test")
    return client


def test_login_redirects_to_tiktok_with_minimal_scopes(tiktok_client):
    r = tiktok_client.get("/auth/tiktok/login", follow_redirects=False)
    url = urlparse(r.headers["location"])
    q = parse_qs(url.query)
    assert url.netloc == "www.tiktok.com" and url.path == "/v2/auth/authorize/"
    assert q["client_key"] == ["ck_test"] and q["response_type"] == ["code"]
    assert q["scope"] == ["user.info.basic,video.upload"]
    assert q["redirect_uri"] == ["https://youlikeit.example/auth/tiktok/callback"]
    assert len(q["state"][0]) >= 24


def test_callback_rejects_bad_state_and_user_denial(tiktok_client):
    tiktok_client.get("/auth/tiktok/login", follow_redirects=False)
    r = tiktok_client.get("/auth/tiktok/callback?code=abc&state=forged", follow_redirects=False)
    assert r.headers["location"] == "/studio?notice=invalid_state"
    r = tiktok_client.get("/auth/tiktok/callback?error=access_denied&state=x", follow_redirects=False)
    assert r.headers["location"] == "/studio?notice=denied"


def test_full_connect_stores_encrypted_tokens_and_disconnect_revokes(tiktok_client, monkeypatch, tmp_path):
    from app import tiktok
    revoked = []
    monkeypatch.setattr(tiktok, "exchange_code", lambda code: {
        "access_token": "act.SECRET-ACCESS", "refresh_token": "rft.SECRET-REFRESH", "open_id": "oid-1",
        "scope": "user.info.basic,video.upload", "expires_in": 86400, "refresh_expires_in": 31536000})
    monkeypatch.setattr(tiktok, "user_info", lambda token: {
        "open_id": "oid-1", "display_name": "Cine y Empatía", "avatar_url": "https://p16.tiktokcdn.com/a.jpg"})
    monkeypatch.setattr(tiktok, "revoke", lambda token: revoked.append(token))

    login = tiktok_client.get("/auth/tiktok/login", follow_redirects=False)
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    r = tiktok_client.get(f"/auth/tiktok/callback?code=abc&state={state}", follow_redirects=False)
    assert r.headers["location"] == "/studio?notice=connected"

    raw = sqlite3.connect(tmp_path / "web.db").execute("SELECT * FROM tiktok_accounts").fetchone()
    blob = b"".join(v if isinstance(v, bytes) else str(v).encode() for v in raw)
    assert b"SECRET-ACCESS" not in blob and b"SECRET-REFRESH" not in blob   # cifrado en reposo
    assert not re.search(rb"avatar|tiktokcdn", blob)                       # el avatar no se guarda

    studio = tiktok_client.get("/studio?notice=connected").text
    assert "Cine y Empatía" in studio and "Disconnect and revoke access" in studio

    r = tiktok_client.post("/auth/tiktok/disconnect", follow_redirects=False)
    assert r.headers["location"] == "/studio?notice=disconnected"
    assert revoked == ["act.SECRET-ACCESS"]
    assert sqlite3.connect(tmp_path / "web.db").execute("SELECT COUNT(*) FROM tiktok_accounts").fetchone()[0] == 0


def test_store_refuses_to_save_without_encryption_key(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("TOKEN_ENC_KEY", raising=False)
    from app import store
    with pytest.raises(RuntimeError, match="TOKEN_ENC_KEY"):
        store.save_account("oid", "x", {"access_token": "t"})


def test_tiktok_url_verification_only_for_allowlisted_tokens(client, monkeypatch):
    shipped = "tiktok6SqmAImuROUyUPH61nJk6s8TjcqpaJXF.txt"
    r = client.get(f"/{shipped}")
    assert r.status_code == 200 and r.text == "tiktok-developers-site-verification=6SqmAImuROUyUPH61nJk6s8TjcqpaJXF"
    assert r.headers["content-type"].startswith("text/plain")

    assert client.get("/tiktokNotAllowed12345.txt").status_code == 404     # no se firma cualquier token
    monkeypatch.setenv("TIKTOK_SITE_TOKENS", "AbCdEf123456, Zz99Yy88Xx77")
    r = client.get("/tiktokZz99Yy88Xx77.txt")
    assert r.status_code == 200 and r.text == "tiktok-developers-site-verification=Zz99Yy88Xx77"
    for bad in ("/tiktok..%2Fmain.py", "/robots.txt", "/tiktokAbC.txt"):
        assert client.get(bad).status_code == 404


# ── Send to TikTok (Content Posting API, borrador) ──────────────────────────

@pytest.fixture
def connected(tiktok_client, monkeypatch, tmp_path):
    """Cliente con cuenta TikTok conectada y una lección de prueba (sin depender del MP4 real)."""
    from app import main, tiktok
    lesson_dir = tmp_path / "lessons"
    lesson_dir.mkdir()
    (lesson_dir / "demo.mp4").write_bytes(b"\x00" * 2048)
    lesson = {"id": "demo", "title": "Fear demo", "emotion": "fear", "film": "NOTLD", "year": 1968,
              "rights": "Public domain", "file": "demo.mp4", "duration_s": 26.0,
              "summary": "x", "source_url": "https://archive.org/details/x"}
    monkeypatch.setattr(main, "LESSONS_DIR", lesson_dir)
    monkeypatch.setattr(main, "LESSONS", [lesson])
    monkeypatch.setattr(main, "LESSON_BY_ID", {"demo": lesson})
    monkeypatch.setattr(tiktok, "exchange_code", lambda code: {
        "access_token": "act.1", "refresh_token": "rft.1", "open_id": "oid-1",
        "scope": "user.info.basic,video.upload", "expires_in": 86400, "refresh_expires_in": 31536000})
    monkeypatch.setattr(tiktok, "user_info", lambda token: {"open_id": "oid-1", "display_name": "Cine"})
    login = tiktok_client.get("/auth/tiktok/login", follow_redirects=False)
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    tiktok_client.get(f"/auth/tiktok/callback?code=c&state={state}", follow_redirects=False)
    return tiktok_client


def test_send_requires_connection(tiktok_client, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "LESSON_BY_ID", {"demo": {"id": "demo", "file": "demo.mp4"}})
    r = tiktok_client.post("/studio/send/demo", follow_redirects=False)
    assert r.headers["location"] == "/studio?notice=connect_first"


def test_send_uploads_draft_and_shows_inbox_status(connected, monkeypatch):
    from app import tiktok
    calls = {}

    def fake_upload(token, path):
        calls["upload"] = (token, path.name, path.stat().st_size)
        return "pub-123"

    monkeypatch.setattr(tiktok, "upload_draft", fake_upload)
    monkeypatch.setattr(tiktok, "fetch_status", lambda token, pid: {"status": "SEND_TO_USER_INBOX"})
    studio = connected.get("/studio").text
    assert "Send to TikTok as draft" in studio and "Fear demo" in studio
    r = connected.post("/studio/send/demo", follow_redirects=False)
    assert r.headers["location"] == "/studio/sent/pub-123"
    assert calls["upload"] == ("act.1", "demo.mp4", 2048)
    page = connected.get("/studio/sent/pub-123").text
    assert "Delivered to your TikTok inbox as a draft." in page and "never posts for you" in page


def test_expired_token_is_refreshed_before_upload(connected, monkeypatch):
    from app import store, tiktok
    acc = store.get_account("oid-1")
    store.save_account("oid-1", acc["display_name"], {"access_token": "act.old", "refresh_token": "rft.1",
                                                     "expires_in": 0, "refresh_expires_in": 1000})
    monkeypatch.setattr(tiktok, "refresh", lambda rt: {"access_token": "act.new", "refresh_token": "rft.2",
                                                      "expires_in": 86400, "refresh_expires_in": 1000})
    used = []
    monkeypatch.setattr(tiktok, "upload_draft", lambda token, path: used.append(token) or "pub-9")
    connected.post("/studio/send/demo", follow_redirects=False)
    assert used == ["act.new"] and store.get_account("oid-1")["refresh_token"] == "rft.2"


def test_tiktok_errors_are_explained_to_the_creator(connected, monkeypatch):
    from app import tiktok

    def boom(token, path):
        raise tiktok.TikTokError("spam_risk_too_many_pending_share")

    monkeypatch.setattr(tiktok, "upload_draft", boom)
    r = connected.post("/studio/send/demo", follow_redirects=False)
    assert r.headers["location"] == "/studio"
    assert "at most 5 pending drafts" in connected.get("/studio").text


def test_sent_page_is_private_to_its_owner(connected, monkeypatch, client):
    from app import store
    store.record_publish("pub-x", "someone-else", "demo")
    assert connected.get("/studio/sent/pub-x").status_code == 404
    assert connected.get("/studio/sent/does-not-exist").status_code == 404


def test_upload_draft_protocol(monkeypatch, tmp_path):
    """init FILE_UPLOAD de un solo trozo + PUT con Content-Range exacto."""
    from app import tiktok
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x" * 1000)
    seen = {}

    class Resp:
        def __init__(self, status, body=None):
            self.status_code, self._body = status, body or {}

        def json(self):
            return self._body

    def fake_post(url, **kw):
        seen["init"] = (url, kw["json"], kw["headers"]["Authorization"])
        return Resp(200, {"data": {"publish_id": "p1", "upload_url": "https://upload/u?x=1"},
                          "error": {"code": "ok"}})

    def fake_put(url, **kw):
        seen["put"] = (url, kw["headers"], len(kw["content"]))
        return Resp(201)

    monkeypatch.setattr(tiktok.httpx, "post", fake_post)
    monkeypatch.setattr(tiktok.httpx, "put", fake_put)
    assert tiktok.upload_draft("tok", video) == "p1"
    url, body, auth = seen["init"]
    assert url.endswith("/v2/post/publish/inbox/video/init/") and auth == "Bearer tok"
    assert body == {"source_info": {"source": "FILE_UPLOAD", "video_size": 1000, "chunk_size": 1000,
                                    "total_chunk_count": 1}}
    put_url, headers, n = seen["put"]
    assert put_url == "https://upload/u?x=1" and n == 1000
    assert headers["Content-Range"] == "bytes 0-999/1000" and headers["Content-Type"] == "video/mp4"
