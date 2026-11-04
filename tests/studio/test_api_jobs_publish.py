from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest

from apps.studio import jobs
from apps.supercut import lessons, planner
from tests.studio.conftest import AUTH, run_jobs


def _approved(db, world) -> int:
    lid = planner.plan_lesson(db, "emotion:fear")["id"]
    lessons.begin_render(db, lid)
    path = lessons.video_path(lid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * 64)
    lessons.finish_render(db, lid, path, 40)
    lessons.approve(db, lid)
    return lid


@pytest.mark.integration
def test_job_validation_errors(client, world):
    assert client.post("/api/jobs", json={"type": "transcode", "params": {}}).status_code == 422
    assert client.post("/api/jobs", json={"type": "index", "params": {"asset_ids": []}}).status_code == 422
    assert client.post("/api/jobs", json={"type": "index", "params": {"asset_ids": [999]}}).status_code == 404
    assert client.post("/api/jobs", json={"type": "index",
                                          "params": {"asset_ids": [1], "steps": ["upload"]}}).status_code == 422
    assert client.post("/api/jobs", json={"type": "label", "params": {"asset_id": 1, "top_k": 0}}).status_code == 422
    assert client.post("/api/jobs", json={"type": "render", "params": {}}).status_code == 422
    assert client.post("/api/jobs", json={"type": "render", "params": {"lesson_id": 5}}).status_code == 404
    assert client.get("/api/jobs/12345").status_code == 404
    assert client.get("/api/jobs?status=weird").status_code == 422


@pytest.mark.integration
def test_jobs_run_record_progress_result_and_errors(client, app, world, monkeypatch):
    events = []
    monkeypatch.setattr(jobs, "notify", lambda source, stage, data: events.append((source, stage, data)))

    def fake_detect(conn, params, progress):
        progress("detect", 50, "mitad")
        return {"asset_id": params["asset_id"], "candidates": 7}

    def broken_label(conn, params, progress):
        raise RuntimeError("Groq 429")

    monkeypatch.setitem(jobs.HANDLERS, "detect", fake_detect)
    monkeypatch.setitem(jobs.HANDLERS, "label", broken_label)
    aid = world["assets"]["Horror Express"]
    j1 = client.post("/api/jobs", json={"type": "detect", "params": {"asset_id": aid}}).json()
    j2 = client.post("/api/jobs", json={"type": "label", "params": {"asset_id": aid, "top_k": 10}}).json()
    assert j1["params"] == {"asset_id": aid, "fetch_anchors": True}
    assert j2["params"] == {"asset_id": aid, "top_k": 10, "provider": None}
    assert run_jobs(app) == [j1["id"], j2["id"]]
    d1, d2 = client.get(f"/api/jobs/{j1['id']}").json(), client.get(f"/api/jobs/{j2['id']}").json()
    assert d1["status"] == "done" and d1["result"] == {"asset_id": aid, "candidates": 7}
    assert d1["progress"] == {"stage": "done", "pct": 100, "detail": ""} and d1["finished_at"].endswith("Z")
    assert d2["status"] == "error" and "Groq 429" in d2["error"]
    assert [j["id"] for j in client.get("/api/jobs?status=done").json()["items"]] == [j1["id"]]
    assert {e[0] for e in events} == {"studio.job"}
    stages = [(e[2]["job_id"], e[1], e[2]["status"]) for e in events]
    assert (j1["id"], "detect", "running") in stages and (j1["id"], "done", "done") in stages
    assert (j2["id"], "error", "error") in stages
    assert all({"job_id", "type", "status", "stage", "pct", "detail"} <= set(e[2]) for e in events)
    assert client.get("/api/overview").json()["jobs"][0]["id"] == j2["id"]


@pytest.mark.integration
def test_worker_thread_runs_jobs(world, monkeypatch):
    from fastapi.testclient import TestClient

    from apps.studio import settings
    from apps.studio.app import create_app
    queue = jobs.JobQueue(settings.connect, {"detect": lambda conn, p, progress: {"ok": p["asset_id"]}},
                          idle_wait=0.05)
    with TestClient(create_app(queue=queue), headers=AUTH) as client:
        job = client.post("/api/jobs", json={"type": "detect", "params": {"asset_id": 1}}).json()
        deadline = time.monotonic() + 10
        while client.get(f"/api/jobs/{job['id']}").json()["status"] != "done":
            assert time.monotonic() < deadline, "el worker no corrió el job"
            time.sleep(0.05)
    assert not queue._thread.is_alive()                                   # se detiene con el lifespan


@pytest.mark.integration
def test_recover_marks_interrupted_jobs_and_rendering_lessons(app, world, db):
    lid = planner.plan_lesson(db, "emotion:fear")["id"]
    lessons.begin_render(db, lid)
    db.execute("INSERT INTO studio_jobs (type, status, params_json, created_at) VALUES ('render', 'running', '{}', "
               "'2026-11-04T00:00:00Z')")
    db.commit()
    assert app.state.jobs.recover() == {"jobs": 1, "lessons": 1}
    assert lessons.get_status(db, lid) == "draft"
    assert db.execute("SELECT status FROM studio_jobs").fetchone()[0] == "error"


@pytest.mark.integration
def test_index_job_uses_index_many_or_steps(client, app, world, monkeypatch):
    import apps.media.indexer as indexer
    calls = []
    monkeypatch.setattr(indexer, "index_many", lambda factory, ids, **kw: calls.append(("many", ids)) or
                        [{"asset_id": i} for i in ids])
    monkeypatch.setattr(indexer, "index_asset", lambda conn, aid, **kw: calls.append(("one", aid, kw["steps"])) or
                        {"asset_id": aid})
    ids = list(world["assets"].values())[:2]
    client.post("/api/jobs", json={"type": "index", "params": {"asset_ids": ids + ids[:1]}})
    client.post("/api/jobs", json={"type": "index", "params": {"asset_ids": ids[:1], "steps": ["probe"]}})
    run_jobs(app)
    assert calls == [("many", ids), ("one", ids[0], ("probe",))]


@pytest.mark.integration
def test_tiktok_accounts_bridge_states(client, mocked_http, monkeypatch):
    assert client.get("/api/publish/tiktok/accounts").status_code == 503
    monkeypatch.setenv("WEB_BASE_URL", "https://web.example")
    monkeypatch.setenv("STUDIO_API_KEY", "k")
    mocked_http.get("https://web.example/api/studio/accounts", json={"accounts": [{"open_id": "o", "display_name": "A"}]})
    assert client.get("/api/publish/tiktok/accounts").json() == {"accounts": [{"open_id": "o", "display_name": "A"}]}
    mocked_http.replace("GET", "https://web.example/api/studio/accounts", status=503, json={"detail": "no key"})
    r = client.get("/api/publish/tiktok/accounts")
    assert r.status_code == 502 and "no key" in r.json()["detail"]


@pytest.mark.integration
def test_publish_endpoints_require_approved(client, world, db):
    lid = planner.plan_lesson(db, "emotion:fear")["id"]
    assert client.post(f"/api/lessons/{lid}/publish/tiktok", json={"open_id": "o1"}).status_code == 409
    assert client.post(f"/api/lessons/{lid}/publish/youtube", json={"privacy": "private"}).status_code == 409
    assert client.post(f"/api/lessons/{lid}/publish/tiktok", json={}).status_code == 422
    assert client.get(f"/api/lessons/{lid}/publications").json() == {"items": []}
    assert client.get("/api/lessons/999/publications").status_code == 404


@pytest.mark.integration
def test_youtube_status_connect_callback_and_publish(client, anon, world, db, tmp_path, monkeypatch):
    import json

    from cryptography.fernet import Fernet

    import apps.publish.youtube as yt
    assert client.get("/api/publish/youtube/status").json() == {"connected": False, "channel_title": None}
    assert client.get("/api/publish/youtube/connect", follow_redirects=False).status_code == 503
    secrets_file = tmp_path / "cs.json"
    secrets_file.write_text(json.dumps({"installed": {"client_id": "cid", "client_secret": "s",
                                                      "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                                                      "token_uri": "https://oauth2.googleapis.com/token"}}))
    monkeypatch.setenv("GOOGLE_CLIENT_SECRETS", str(secrets_file))
    monkeypatch.setenv("TOKEN_ENC_KEY", Fernet.generate_key().decode())
    r = client.get("/api/publish/youtube/connect", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("https://accounts.google.com/")
    assert "127.0.0.1%3A8001%2Fapi%2Fpublish%2Fyoutube%2Fcallback" in r.headers["location"]
    bad = anon.get("/api/publish/youtube/callback?state=forged&code=x")              # sin token: lo cuida el state
    assert bad.status_code == 400 and "text/html" in bad.headers["content-type"]
    assert "<script" not in anon.get("/api/publish/youtube/callback?state=<script>").text

    lid = _approved(db, world)
    assert client.post(f"/api/lessons/{lid}/publish/youtube", json={"privacy": "private"}).status_code == 409
    yt.save_token({"credentials": {"refresh_token": "r", "token": "t", "client_id": "c", "client_secret": "s"},
                   "channel_title": "Canal"})
    assert client.get("/api/publish/youtube/status").json() == {"connected": True, "channel_title": "Canal", "warning": None}
    future = (datetime.now(UTC) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert client.post(f"/api/lessons/{lid}/publish/youtube",
                       json={"privacy": "public", "publish_at": future}).status_code == 422
    assert client.post(f"/api/lessons/{lid}/publish/youtube", json={"privacy": "friends"}).status_code == 422
    job = client.post(f"/api/lessons/{lid}/publish/youtube", json={"privacy": "private", "publish_at": future})
    assert job.status_code == 200 and job.json()["params"]["publish_at"] == future
