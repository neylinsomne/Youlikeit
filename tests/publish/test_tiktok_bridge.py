from __future__ import annotations

import json

import pytest
import requests
import responses

from apps.publish import tiktok_bridge as tb

BASE = "https://web.example"
UPLOAD = "https://open-upload.tiktokapis.com/upload/?upload_id=1&upload_token=t"


@pytest.mark.unit
def test_not_configured_without_env():
    with pytest.raises(tb.BridgeNotConfigured):
        tb.list_accounts()


@pytest.mark.unit
def test_base_url_must_be_https_except_localhost(monkeypatch):
    monkeypatch.setenv("STUDIO_API_KEY", "k")
    monkeypatch.setenv("WEB_BASE_URL", "http://evil.example")
    with pytest.raises(tb.BridgeNotConfigured):
        tb.list_accounts()


@pytest.mark.integration
def test_list_accounts_sends_bearer(bridge_env, mocked_http):
    mocked_http.get(f"{BASE}/api/studio/accounts", json={"accounts": [
        {"open_id": "o1", "display_name": "Ana"}, {"display_name": "sin id"}]})
    assert tb.list_accounts() == [{"open_id": "o1", "display_name": "Ana"}]
    assert mocked_http.calls[0].request.headers["Authorization"] == "Bearer bridge-key-test"


@pytest.mark.integration
def test_bridge_errors_carry_detail_and_status(bridge_env, mocked_http):
    mocked_http.post(f"{BASE}/api/studio/tiktok/init", status=409, json={"detail": "reconnect"})
    with pytest.raises(tb.BridgeError) as e:
        tb.init_upload("o1", 10, "lesson-1")
    assert e.value.status_code == 409 and "reconnect" in str(e.value)
    mocked_http.get(f"{BASE}/api/studio/accounts", body=requests.ConnectionError("down"))
    with pytest.raises(tb.BridgeError, match="no responde"):
        tb.list_accounts()


@pytest.mark.integration
def test_send_draft_full_flow(bridge_env, mocked_http, tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00" * 1234)
    mocked_http.post(f"{BASE}/api/studio/tiktok/init", json={"publish_id": "p_1", "upload_url": UPLOAD})
    mocked_http.put(UPLOAD, status=201)
    mocked_http.get(f"{BASE}/api/studio/tiktok/status/p_1", json={"status": "PROCESSING_UPLOAD"})
    mocked_http.get(f"{BASE}/api/studio/tiktok/status/p_1", json={"status": "SEND_TO_USER_INBOX"})
    sleeps = []
    out = tb.send_draft(video, "o1", "lesson-7", sleep=sleeps.append, poll_interval=0.01)
    assert out == {"publish_id": "p_1", "status": "SEND_TO_USER_INBOX"} and sleeps == [0.01]
    init_body = json.loads(mocked_http.calls[0].request.body)
    assert init_body == {"open_id": "o1", "video_size": 1234, "lesson_ref": "lesson-7"}
    put = mocked_http.calls[1].request
    assert put.method == "PUT" and put.headers["Content-Range"] == "bytes 0-1233/1234"
    assert put.headers["Content-Type"] == "video/mp4" and "Authorization" not in put.headers  # nada de la key
    assert len(put.body) == 1234


@pytest.mark.integration
def test_send_draft_without_poll_and_put_failure(bridge_env, mocked_http, tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x" * 10)
    mocked_http.post(f"{BASE}/api/studio/tiktok/init", json={"publish_id": "p_2", "upload_url": UPLOAD})
    mocked_http.put(UPLOAD, status=201)
    assert tb.send_draft(video, "o1", "l", poll=False)["status"] == "PROCESSING_UPLOAD"
    mocked_http.replace(responses.PUT, UPLOAD, status=500)
    with pytest.raises(tb.BridgeError, match="HTTP 500"):
        tb.send_draft(video, "o1", "l", poll=False)


@pytest.mark.integration
def test_upload_url_must_be_tiktok_https(bridge_env, mocked_http, tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    for bad in ("http://open-upload.tiktokapis.com/u", "https://evil.example/u", "https://tiktokapis.com.evil.io/u"):
        mocked_http.post(f"{BASE}/api/studio/tiktok/init", json={"publish_id": "p", "upload_url": bad})
        with pytest.raises(tb.BridgeError, match="upload_url rechazada"):
            tb.send_draft(video, "o1", "l", poll=False)
        mocked_http.reset()


@pytest.mark.unit
def test_send_draft_rejects_empty_and_huge(bridge_env, tmp_path, monkeypatch):
    empty = tmp_path / "e.mp4"
    empty.write_bytes(b"")
    with pytest.raises(tb.BridgeError, match="vacío"):
        tb.send_draft(empty, "o1", "l")
    monkeypatch.setattr(tb, "MAX_SINGLE_CHUNK", 4)
    big = tmp_path / "b.mp4"
    big.write_bytes(b"12345")
    with pytest.raises(tb.BridgeError, match="64 MB"):
        tb.send_draft(big, "o1", "l")


@pytest.mark.integration
def test_poll_stops_at_timeout(bridge_env, mocked_http, tmp_path, monkeypatch):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    mocked_http.post(f"{BASE}/api/studio/tiktok/init", json={"publish_id": "p_3", "upload_url": UPLOAD})
    mocked_http.put(UPLOAD, status=200)
    mocked_http.get(f"{BASE}/api/studio/tiktok/status/p_3", json={"status": "PROCESSING_UPLOAD"})
    out = tb.send_draft(video, "o1", "l", poll_timeout=0, sleep=lambda s: None)
    assert out["status"] == "PROCESSING_UPLOAD"
