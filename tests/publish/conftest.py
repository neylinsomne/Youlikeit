from __future__ import annotations

import pytest

from tests.supercut.helpers import isolate_env, schema_conn


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    isolate_env(tmp_path, monkeypatch)
    import apps.publish.youtube as yt
    yt._pending.clear()
    return tmp_path


@pytest.fixture
def bridge_env(monkeypatch):
    monkeypatch.setenv("WEB_BASE_URL", "https://web.example")
    monkeypatch.setenv("STUDIO_API_KEY", "bridge-key-test")


@pytest.fixture
def fernet_key(monkeypatch):
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("TOKEN_ENC_KEY", key)
    return key


@pytest.fixture
def client_secrets(tmp_path, monkeypatch):
    import json
    path = tmp_path / "client_secrets.json"
    path.write_text(json.dumps({"installed": {
        "client_id": "cid.apps.googleusercontent.com", "client_secret": "csecret", "project_id": "p",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"]}}), encoding="utf-8")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRETS", str(path))
    return path


@pytest.fixture
def pconn():
    c = schema_conn()
    yield c
    c.close()
