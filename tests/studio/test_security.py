from __future__ import annotations

import pytest
from starlette.websockets import WebSocketDisconnect

from apps.supercut import lessons
from tests.studio.conftest import AUTH, TOKEN

PROTECTED = ["/api/overview", "/api/works", "/api/lessons", "/api/jobs", "/api/vocab",
             "/api/publish/youtube/status", "/api/files/lesson/1.mp4"]


@pytest.mark.integration
def test_health_is_public(anon):
    r = anon.get("/api/health")
    assert r.status_code == 200 and r.json() == {"ok": True}


@pytest.mark.integration
@pytest.mark.parametrize("path", PROTECTED)
def test_no_token_is_401(anon, path):
    r = anon.get(path)
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"


@pytest.mark.integration
@pytest.mark.parametrize("header", [f"Bearer {TOKEN}x", "Bearer ", f"Basic {TOKEN}", TOKEN, "Bearer wrong"])
def test_wrong_token_is_401(anon, header):
    assert anon.get("/api/overview", headers={"Authorization": header}).status_code == 401


@pytest.mark.integration
def test_scheme_is_case_insensitive(anon):
    assert anon.get("/api/works", headers={"Authorization": f"bearer {TOKEN}"}).status_code == 200


@pytest.mark.integration
def test_server_without_token_rejects_everything(anon, monkeypatch):
    monkeypatch.delenv("STUDIO_TOKEN")
    assert anon.get("/api/works", headers=AUTH).status_code == 401
    assert anon.get("/api/works", headers={"Authorization": "Bearer "}).status_code == 401


@pytest.fixture
def secrets_on_disk(tmp_path):
    """Archivos sensibles junto a las carpetas servidas: nunca deben salir por /api/files."""
    (tmp_path / ".env").write_text("STUDIO_TOKEN=leak", encoding="utf-8")
    (tmp_path / "outputs").mkdir(exist_ok=True)
    (tmp_path / "outputs" / ".env").write_text("SECRET=1", encoding="utf-8")
    (tmp_path / "tokens").mkdir(exist_ok=True)
    (tmp_path / "tokens" / "youtube_studio.json.enc").write_bytes(b"secret")
    out = lessons.output_dir()
    out.mkdir(parents=True, exist_ok=True)
    (out / "1.mp4").write_bytes(bytes(range(256)) * 4)
    (out / "notes.txt").write_text("not a video", encoding="utf-8")
    return out


@pytest.mark.integration
@pytest.mark.parametrize("path", [
    "/api/files/lesson/..%2F.env", "/api/files/lesson/..%2F..%2F.env", "/api/files/lesson/.env",
    "/api/files/lesson/%2E%2E%2F%2E%2E%2Ftokens%2Fyoutube_studio.json.enc", "/api/files/preview/..%5C..%5C.env",
    "/api/files/lesson/notes.txt", "/api/files/lesson/2.mp4", "/api/files/data/shorts_pipeline.db",
    "/api/files/tokens/youtube_studio.json.enc", "/api/files/lesson/..", "/api/files/lesson/C:%5Cwindows%5Cwin.ini",
])
def test_files_traversal_and_unknown_are_404(client, secrets_on_disk, path):
    r = client.get(path)
    assert r.status_code == 404
    assert b"leak" not in r.content and b"SECRET" not in r.content and b"secret" != r.content


@pytest.mark.integration
def test_files_serves_allowlisted_video_with_range(client, secrets_on_disk):
    full = client.get("/api/files/lesson/1.mp4")
    assert full.status_code == 200 and full.headers["content-type"] == "video/mp4" and len(full.content) == 1024
    part = client.get("/api/files/lesson/1.mp4", headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and part.headers["content-range"] == "bytes 0-99/1024" and len(part.content) == 100


@pytest.mark.integration
def test_cors_only_for_vite_front(client):
    ok = client.options("/api/works", headers={"Origin": "http://127.0.0.1:5180",
                                               "Access-Control-Request-Method": "GET",
                                               "Access-Control-Request-Headers": "authorization"})
    assert ok.status_code == 200 and ok.headers["access-control-allow-origin"] == "http://127.0.0.1:5180"
    local = client.get("/api/works", headers={"Origin": "http://localhost:5180"})
    assert local.headers["access-control-allow-origin"] == "http://localhost:5180"
    evil = client.options("/api/works", headers={"Origin": "http://evil.example",
                                                 "Access-Control-Request-Method": "GET"})
    assert evil.status_code == 403 and "access-control-allow-origin" not in evil.headers


@pytest.mark.integration
def test_foreign_origin_cannot_trigger_actions_even_with_token(client):
    r = client.post("/api/jobs", json={"type": "detect", "params": {"asset_id": 1}},
                    headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json() == {"detail": "Origen no permitido"}


@pytest.mark.integration
def test_websocket_requires_token(anon):
    with pytest.raises(WebSocketDisconnect) as e:
        with anon.websocket_connect("/ws") as ws:
            ws.receive_text()
    assert e.value.code == 1008
    with pytest.raises(WebSocketDisconnect):
        with anon.websocket_connect("/ws?token=wrong") as ws:
            ws.receive_text()
    with pytest.raises(WebSocketDisconnect):
        with anon.websocket_connect(f"/ws?token={TOKEN}", headers={"Origin": "http://evil.example"}) as ws:
            ws.receive_text()


@pytest.mark.integration
@pytest.mark.parametrize("how", ["query", "header"])
def test_websocket_receives_job_events(anon, how):
    from utils.websocket_hub import notify
    url, headers = (f"/ws?token={TOKEN}", {}) if how == "query" else ("/ws", AUTH)
    notify("studio.job", "seed", {"job_id": 0})                     # asegura un catchup no vacío
    with anon.websocket_connect(url, headers=headers) as ws:
        first = ws.receive_json()
        assert first["type"] == "catchup" and first["events"]
        notify("studio.job", "render", {"job_id": 999, "type": "render", "status": "running", "stage": "render",
                                        "pct": 40, "detail": "tramo 1/3"})
        event = ws.receive_json()
        assert event["source"] == "studio.job" and event["data"]["job_id"] == 999 and event["ts"].endswith("Z")
