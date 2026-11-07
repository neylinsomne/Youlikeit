"""`ylk doctor`: estados sin filtrar valores de las keys."""
from __future__ import annotations

import json

import pytest

from integrations import credentials_check as cc


@pytest.mark.unit
def test_missing_key_is_reported_without_calling(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    c = cc._http("Groq", "x", "GROQ_API_KEY", lambda k: pytest.fail("no debe llamar"))
    assert c.status == "MISSING"


@pytest.mark.integration
def test_invalid_key_shows_service_message_not_value(mocked_http, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "SECRETO123")
    mocked_http.get("https://generativelanguage.googleapis.com/v1beta/models", status=400,
                    json={"error": {"message": "API key not valid."}})
    checks = {c.name: c for c in cc.check_api_keys()}
    g = checks["Gemini"]
    assert g.status == "INVALID" and "not valid" in g.detail
    assert all("SECRETO123" not in (c.detail + c.name) for c in checks.values())


@pytest.mark.integration
def test_oauth_invalid_grant_hints_testing_mode(mocked_http, monkeypatch, tmp_path):
    secrets = tmp_path / "client_secrets.json"
    secrets.write_text(json.dumps({"installed": {"client_id": "cid", "client_secret": "cs", "project_id": "p"}}))
    monkeypatch.setenv("GOOGLE_CLIENT_SECRETS", str(secrets))
    tok = tmp_path / "youtube_deep_mind.json"
    tok.write_text(json.dumps({"refresh_token": "rt"}))
    mocked_http.post("https://oauth2.googleapis.com/token", status=400, json={"error": "invalid_grant"})
    out = {c.name: c for c in cc.check_youtube_oauth([tok])}
    assert out["OAuth client (client_secrets.json)"].status == "OK"
    assert out["OAuth youtube_deep_mind.json"].status == "INVALID"
    assert "Testing" in out["OAuth youtube_deep_mind.json"].detail


@pytest.mark.integration
def test_doctor_checks_the_studio_youtube_token(mocked_http, monkeypatch, tmp_path):
    from cryptography.fernet import Fernet

    from apps.publish import youtube
    monkeypatch.setenv("TOKEN_ENC_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("TOKENS_DIR", str(tmp_path))
    app = {"client_id": "cid", "client_secret": "cs"}
    assert cc.check_youtube_studio(app).status == "MISSING"

    youtube.save_token({"credentials": {"refresh_token": "RT-SECRET"}, "channel_title": "Mi canal"})
    mocked_http.post("https://oauth2.googleapis.com/token", json={"access_token": "a"})
    ok = cc.check_youtube_studio(app)
    assert ok.status == "OK" and "Mi canal" in ok.detail and "RT-SECRET" not in ok.detail

    youtube.save_token({"credentials": {"refresh_token": "RT-SECRET"}, "warning": "Habilita la API"})
    mocked_http.post("https://oauth2.googleapis.com/token", json={"access_token": "a"})
    assert cc.check_youtube_studio(app).status == "WARN"
