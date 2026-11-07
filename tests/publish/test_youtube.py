from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest

from apps.publish import youtube as yt

FUTURE = (datetime.now(UTC) + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
CREDS = {"token": "access-123", "refresh_token": "refresh-SECRET-456", "client_id": "cid", "client_secret": "cs",
         "token_uri": "https://oauth2.googleapis.com/token", "scopes": yt.SCOPES,
         "expiry": (datetime.now(UTC) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")}


class FakeCreds:
    def to_json(self):
        return json.dumps(CREDS)


class FakeFlow:
    def __init__(self):
        self.code = None
        self.credentials = FakeCreds()

    def fetch_token(self, *, code):
        self.code = code


class FakeService:
    def __init__(self, *, insert_error=None, channels_error=None, channels=None):
        self.body = None
        self.insert_error = insert_error
        self.channels_error = channels_error
        self.channels_result = channels if channels is not None else {
            "items": [{"id": "UC1", "snippet": {"title": "Mi canal"}}]}

    def channels(self):
        svc = self

        class Ch:
            def list(self, **kw):
                class Req:
                    def execute(self_inner):
                        if svc.channels_error:
                            raise svc.channels_error
                        return svc.channels_result
                return Req()
        return Ch()


    def videos(self):
        svc = self

        class Vid:
            def insert(self, *, part, body, media_body):
                svc.body = body
                svc.part = part

                class Req:
                    calls = 0

                    def next_chunk(self_inner):
                        if svc.insert_error:
                            raise svc.insert_error
                        Req.calls += 1
                        if Req.calls == 1:
                            return type("St", (), {"progress": lambda s: 0.5})(), None
                        return None, {"id": "vid_1"}
                return Req()
        return Vid()


def http_error(status: int, reason: str):
    from googleapiclient.errors import HttpError
    resp = type("R", (), {"status": status, "reason": "x"})()
    body = {"error": {"code": status, "message": "m", "errors": [{"reason": reason}]}}
    return HttpError(resp, json.dumps(body).encode())


@pytest.mark.unit
def test_status_without_token_is_disconnected():
    assert yt.status() == {"connected": False, "channel_title": None}


@pytest.mark.unit
def test_token_is_encrypted_at_rest(fernet_key):
    yt.save_token({"credentials": CREDS, "channel_title": "Canal"})
    raw = yt.token_path().read_bytes()
    assert b"refresh-SECRET-456" not in raw and b"Canal" not in raw
    assert yt.load_token()["credentials"]["refresh_token"] == "refresh-SECRET-456"
    assert yt.status() == {"connected": True, "channel_title": "Canal", "warning": None}


@pytest.mark.unit
def test_wrong_or_missing_key(fernet_key, monkeypatch):
    yt.save_token({"credentials": CREDS})
    from cryptography.fernet import Fernet
    monkeypatch.setenv("TOKEN_ENC_KEY", Fernet.generate_key().decode())
    with pytest.raises(yt.YouTubeNotConfigured):
        yt.load_token()
    assert yt.status()["connected"] is False
    monkeypatch.delenv("TOKEN_ENC_KEY")
    st = yt.status()
    assert st["connected"] is False and "TOKEN_ENC_KEY" in st["detail"]
    monkeypatch.setenv("TOKEN_ENC_KEY", "not-a-key")
    with pytest.raises(yt.YouTubeNotConfigured, match="no es una clave"):
        yt.save_token({})


@pytest.mark.unit
def test_auth_url_is_installed_app_loopback_with_pkce(fernet_key, client_secrets, monkeypatch):
    monkeypatch.setenv("STUDIO_PORT", "8011")
    url = yt.auth_url()
    q = parse_qs(urlparse(url).query)
    assert url.startswith("https://accounts.google.com/")
    assert q["redirect_uri"] == ["http://127.0.0.1:8011/api/publish/youtube/callback"]
    assert q["access_type"] == ["offline"] and q["code_challenge_method"] == ["S256"]
    assert set(q["scope"][0].split()) == set(yt.SCOPES)
    assert q["state"][0] in yt._pending


@pytest.mark.unit
def test_auth_url_requires_config(client_secrets, fernet_key, monkeypatch):
    monkeypatch.delenv("TOKEN_ENC_KEY")
    with pytest.raises(yt.YouTubeNotConfigured):
        yt.auth_url()
    monkeypatch.setenv("TOKEN_ENC_KEY", fernet_key)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRETS", "nope.json")
    with pytest.raises(yt.YouTubeNotConfigured):
        yt.auth_url()


@pytest.mark.integration
def test_callback_exchanges_code_stores_token_and_state_is_single_use(fernet_key, client_secrets, monkeypatch):
    url = yt.auth_url()
    state = parse_qs(urlparse(url).query)["state"][0]
    flows = []

    def make_flow(**kw):
        flows.append(kw)
        f = FakeFlow()
        flows.append(f)
        return f

    monkeypatch.setattr(yt, "_make_flow", make_flow)
    monkeypatch.setattr(yt, "_build_service", lambda creds: FakeService())
    st = yt.handle_callback(state=state, code="the-code")
    assert st == {"connected": True, "channel_title": "Mi canal", "warning": None}
    assert flows[0]["state"] == state and flows[0]["code_verifier"] and flows[1].code == "the-code"
    with pytest.raises(yt.YouTubeAuthError):
        yt.handle_callback(state=state, code="again")


@pytest.mark.unit
def test_callback_rejects_unknown_state_and_google_error(fernet_key, client_secrets):
    with pytest.raises(yt.YouTubeAuthError):
        yt.handle_callback(state="forged", code="c")
    state = parse_qs(urlparse(yt.auth_url()).query)["state"][0]
    with pytest.raises(yt.YouTubeAuthError, match="access_denied"):
        yt.handle_callback(state=state, code=None, error="access_denied")


@pytest.mark.unit
def test_build_body_rules():
    body = yt.build_body(title="Miedo <en> el cine", description="d", tags=["a", ""], privacy="private",
                         publish_at=FUTURE, duration_s=54.2)
    assert body["snippet"]["title"] == "Miedo en el cine #Shorts"
    assert body["snippet"]["categoryId"] == "27" and body["snippet"]["tags"] == ["a"]
    assert body["status"] == {"privacyStatus": "private", "selfDeclaredMadeForKids": False, "publishAt": FUTURE}
    long = yt.build_body(title="x" * 150, description="", tags=None, privacy="unlisted", publish_at=None,
                         duration_s=90)
    assert len(long["snippet"]["title"]) == 100 and "#Shorts" not in long["snippet"]["title"]
    assert len(yt.shorts_title("y" * 150, 30)) == 100 and yt.shorts_title("y" * 150, 30).endswith("#Shorts")
    with pytest.raises(ValueError, match="private"):
        yt.build_body(title="t", description="", tags=None, privacy="public", publish_at=FUTURE, duration_s=10)
    with pytest.raises(ValueError, match="futura"):
        yt.build_body(title="t", description="", tags=None, privacy="private",
                      publish_at="2020-01-01T00:00:00Z", duration_s=10)
    with pytest.raises(ValueError):
        yt.build_body(title="t", description="", tags=None, privacy="friends", publish_at=None, duration_s=10)
    with pytest.raises(ValueError):
        yt.parse_publish_at("mañana")


@pytest.mark.integration
def test_upload_resumable_private_with_publish_at(fernet_key, tmp_path, monkeypatch):
    yt.save_token({"credentials": CREDS})
    svc = FakeService()
    monkeypatch.setattr(yt, "_build_service", lambda creds: svc)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00" * 2048)
    steps = []
    out = yt.upload(video, title="Miedo", description="desc", tags=["cine"], privacy="private",
                    publish_at=FUTURE, duration_s=40, progress=lambda s, p, d: steps.append(p))
    assert out == {"video_id": "vid_1", "url": "https://youtu.be/vid_1", "privacy": "private", "publish_at": FUTURE}
    assert svc.part == "snippet,status" and svc.body["snippet"]["title"] == "Miedo #Shorts"
    assert steps == [52]


@pytest.mark.integration
def test_upload_errors(fernet_key, tmp_path, monkeypatch):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    with pytest.raises(yt.YouTubeNotConnected):
        yt.upload(video, title="t")
    yt.save_token({"credentials": CREDS})
    from googleapiclient.errors import HttpError
    resp = type("R", (), {"status": 403, "reason": "Forbidden"})()
    monkeypatch.setattr(yt, "_build_service", lambda creds: FakeService(insert_error=HttpError(resp, b"{}")))
    with pytest.raises(yt.YouTubeError, match="403"):
        yt.upload(video, title="t")


@pytest.mark.integration
def test_expired_token_is_refreshed_and_saved_encrypted(fernet_key, monkeypatch):
    from google.oauth2.credentials import Credentials
    yt.save_token({"credentials": {**CREDS, "expiry": "2020-01-01T00:00:00Z"}, "channel_title": "C"})

    def fake_refresh(self, request):
        self.token = "access-NEW"
        self.expiry = (datetime.now(UTC) + timedelta(hours=1)).replace(tzinfo=None)

    monkeypatch.setattr(Credentials, "refresh", fake_refresh)
    creds = yt.load_credentials()
    assert creds.token == "access-NEW"
    saved = yt.load_token()
    assert saved["credentials"]["token"] == "access-NEW" and saved["channel_title"] == "C"
    assert b"access-NEW" not in yt.token_path().read_bytes()


def _connect(monkeypatch, svc):
    state = parse_qs(urlparse(yt.auth_url()).query)["state"][0]
    monkeypatch.setattr(yt, "_make_flow", lambda **kw: FakeFlow())
    monkeypatch.setattr(yt, "_build_service", lambda creds: svc)
    return yt.handle_callback(state=state, code="c")


@pytest.mark.integration
def test_connect_warns_when_api_is_disabled_but_keeps_token(fernet_key, client_secrets, monkeypatch):
    st = _connect(monkeypatch, FakeService(channels_error=http_error(403, "accessNotConfigured")))
    assert st["connected"] is True
    assert "YouTube Data API v3" in st["warning"] and "proyecto de Google Cloud p" in st["warning"]
    assert yt.status()["warning"] == st["warning"]


@pytest.mark.integration
def test_connect_warns_when_account_has_no_channel(fernet_key, client_secrets, monkeypatch):
    st = _connect(monkeypatch, FakeService(channels={"items": []}))
    assert st["connected"] is True and "no tiene canal" in st["warning"]


@pytest.mark.integration
def test_upload_error_explains_reason_without_leaking_tokens(fernet_key, tmp_path, monkeypatch):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    yt.save_token({"credentials": CREDS})
    monkeypatch.setattr(yt, "_build_service", lambda creds: FakeService(insert_error=http_error(403, "quotaExceeded")))
    with pytest.raises(yt.YouTubeError) as ei:
        yt.upload(video, title="t")
    msg = str(ei.value)
    assert "HTTP 403 (quotaExceeded)" in msg and "cuota" in msg
    assert "refresh-SECRET-456" not in msg
