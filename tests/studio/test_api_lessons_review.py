from __future__ import annotations

import pytest

from apps.supercut import lessons
from integrations.ai import llm_json
from tests.studio.conftest import run_jobs
from tests.supercut.helpers import add_asset, add_moment, make_master, needs_ffmpeg, seed_fear_world


def _create(client, **kw):
    r = client.post("/api/lessons", json={"spec": "emotion:fear", **kw})
    assert r.status_code == 200, r.text
    return r.json()


def _fake_rendered(db, lesson_id: int) -> None:
    """Simula un render terminado (sin ffmpeg)."""
    lessons.begin_render(db, lesson_id)
    path = lessons.video_path(lesson_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * 2048)
    lessons.finish_render(db, lesson_id, path, 41.5)


@pytest.mark.integration
def test_create_lesson_contract(client, world):
    lesson = _create(client, title="Miedo", max_works=5, max_duration_s=58, lang="es")
    assert lesson["status"] == "draft" and lesson["title"] == "Miedo" and lesson["spec"] == "emotion:fear"
    assert {"id", "title", "spec", "format", "lang", "status", "duration_s", "video_url", "script", "items", "issues",
            "publications", "reject_reason", "created_at", "updated_at"} <= set(lesson)
    assert [i["work_year"] for i in lesson["items"]] == [1962, 1968, 1972]
    assert client.get(f"/api/lessons/{lesson['id']}").json()["id"] == lesson["id"]
    assert [x["id"] for x in client.get("/api/lessons?status=draft").json()["items"]] == [lesson["id"]]
    assert client.get("/api/lessons?status=approved").json()["items"] == []
    assert client.get("/api/lessons/999").status_code == 404


@pytest.mark.integration
def test_create_lesson_errors(client, db):
    aid = add_asset(db, title="Only", year=1970)
    add_moment(db, aid, start_ms=0, end_ms=4000)
    r = client.post("/api/lessons", json={"spec": "emotion:fear"})
    assert r.status_code == 409 and "obra" in r.json()["detail"]
    assert client.post("/api/lessons", json={"spec": "emotion:joyful"}).status_code == 422
    assert client.post("/api/lessons", json={"spec": "emotion:fear", "max_works": 1}).status_code == 422
    assert client.post("/api/lessons", json={"spec": "emotion:fear", "lang": "fr"}).status_code == 422


@pytest.mark.integration
def test_patch_lesson_and_back_to_draft(client, world, db):
    lesson = _create(client)
    lid = lesson["id"]
    first = lesson["items"][0]
    _fake_rendered(db, lid)
    assert client.get(f"/api/lessons/{lid}").json()["video_url"] == f"/api/lessons/{lid}/video"
    r = client.patch(f"/api/lessons/{lid}", json={
        "title": "Nuevo", "items": [{"moment_id": first["moment_id"], "in_ms": first["in_ms"],
                                     "out_ms": first["in_ms"] + 2500, "caption": "Hola"}]})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "draft" and body["title"] == "Nuevo" and len(body["items"]) == 1
    bad_range = [{"moment_id": first["moment_id"], "in_ms": 5000, "out_ms": 100}]
    assert client.patch(f"/api/lessons/{lid}", json={"items": bad_range}).status_code == 422
    bad_moment = [{"moment_id": 9999, "in_ms": 0, "out_ms": 100}]
    assert client.patch(f"/api/lessons/{lid}", json={"items": bad_moment}).status_code == 422
    restricted = [{"moment_id": world["moments"]["Restricted Film"], "in_ms": 0, "out_ms": 100}]
    assert client.patch(f"/api/lessons/{lid}", json={"items": restricted}).status_code == 422
    script = {"hook": "h", "outro": "o", "segments": [{"idx": 0, "narration": "n", "caption": "c"}]}
    assert client.patch(f"/api/lessons/{lid}", json={"script": script}).json()["script"] == script
    assert client.patch(f"/api/lessons/{lid}", json={"script": {"hook": "h"}}).status_code == 422
    lessons.begin_render(db, lid)
    assert client.patch(f"/api/lessons/{lid}", json={"title": "x"}).status_code == 409


@pytest.mark.integration
def test_script_endpoint_502_keeps_template_and_200_with_llm(client, world, monkeypatch):
    lid = _create(client)["id"]
    r = client.post(f"/api/lessons/{lid}/script", json={"provider": None})
    assert r.status_code == 502
    assert client.get(f"/api/lessons/{lid}").json()["script_source"] == "template"
    reply = {"hook": "¿Qué sientes?", "outro": "Respira.",
             "segments": [{"idx": i, "narration": f"n{i}", "caption": f"c{i}"} for i in range(3)]}
    monkeypatch.setattr(llm_json, "complete_json", lambda *a, **k: (reply, "groq"))
    ok = client.post(f"/api/lessons/{lid}/script")
    assert ok.status_code == 200 and ok.json()["script_source"] == "llm:groq"
    assert [i["caption"] for i in ok.json()["items"]] == ["c0", "c1", "c2"]


@pytest.mark.integration
def test_review_approve_reject_and_issues(client, world, db):
    lid = _create(client)["id"]
    assert client.post(f"/api/lessons/{lid}/approve").status_code == 409            # draft
    _fake_rendered(db, lid)
    assert client.post(f"/api/lessons/{lid}/reject", json={"reason": ""}).status_code == 422
    rej = client.post(f"/api/lessons/{lid}/reject", json={"reason": "Texto encima de la cara"})
    assert rej.status_code == 200 and rej.json()["status"] == "rejected"
    assert rej.json()["reject_reason"] == "Texto encima de la cara"
    assert client.post(f"/api/lessons/{lid}/approve").status_code == 409            # rejected
    issue = client.post(f"/api/lessons/{lid}/issues",
                        json={"issue_type": "caption", "start_s": 3.2, "end_s": 5.0, "note": "tapa la cara"})
    assert issue.status_code == 200 and issue.json()["issue_type"] == "caption"
    assert client.post(f"/api/lessons/{lid}/issues", json={"issue_type": "music", "start_s": 0, "end_s": 1}) \
        .status_code == 422
    assert client.post(f"/api/lessons/{lid}/issues", json={"issue_type": "voice", "start_s": 4, "end_s": 1}) \
        .status_code == 422
    assert [i["id"] for i in client.get(f"/api/lessons/{lid}/issues").json()["items"]] == [issue.json()["id"]]
    assert client.get(f"/api/lessons/{lid}").json()["issues"] == 1
    assert client.delete(f"/api/lessons/{lid}/issues/{issue.json()['id']}").json() == {"ok": True}
    assert client.delete(f"/api/lessons/{lid}/issues/{issue.json()['id']}").status_code == 404
    assert client.get("/api/lessons/999/issues").status_code == 404
    client.patch(f"/api/lessons/{lid}", json={"title": "Corregida"})                 # rejected → draft
    _fake_rendered(db, lid)
    ok = client.post(f"/api/lessons/{lid}/approve")
    assert ok.status_code == 200 and ok.json()["status"] == "approved" and ok.json()["reject_reason"] is None


@pytest.mark.integration
def test_video_endpoint_404_until_rendered(client, world, db):
    lid = _create(client)["id"]
    assert client.get(f"/api/lessons/{lid}/video").status_code == 404
    _fake_rendered(db, lid)
    r = client.get(f"/api/lessons/{lid}/video", headers={"Range": "bytes=100-199"})
    assert r.status_code == 206 and r.headers["content-range"] == "bytes 100-199/2048"


@pytest.mark.integration
def test_render_shortcut_queues_job_and_conflicts(client, app, world, db, monkeypatch):
    lid = _create(client)["id"]
    job = client.post(f"/api/lessons/{lid}/render", json={"narrate": False}).json()
    assert job["type"] == "render" and job["status"] == "queued" and job["params"] == {"lesson_id": lid,
                                                                                       "narrate": False}
    assert job["progress"] == {"stage": "queued", "pct": 0, "detail": ""} and job["result"] is None
    lessons.begin_render(db, lid)
    assert client.post(f"/api/lessons/{lid}/render").status_code == 409
    assert client.post("/api/lessons/999/render").status_code == 404


@needs_ffmpeg
@pytest.mark.integration
@pytest.mark.slow
def test_end_to_end_render_review_publish_tiktok(client, app, db, tmp_path, monkeypatch):
    masters = {"Night of the Living Dead": make_master(tmp_path / "m" / "a.mkv", seconds=14),
               "Carnival of Souls": make_master(tmp_path / "m" / "b.mp4", seconds=12, audio=False),
               "Horror Express": make_master(tmp_path / "m" / "c.mkv", seconds=12)}
    seed_fear_world(db, masters)
    lesson = _create(client, max_duration_s=13)
    lid = lesson["id"]
    job = client.post(f"/api/lessons/{lid}/render", json={"narrate": False}).json()
    assert run_jobs(app) == [job["id"]]
    done = client.get(f"/api/jobs/{job['id']}").json()
    assert done["status"] == "done", done["error"]
    assert done["progress"]["pct"] == 100 and done["result"]["height"] == 1920
    rendered = client.get(f"/api/lessons/{lid}").json()
    assert rendered["status"] == "rendered" and rendered["duration_s"] <= 13.3
    video = client.get(rendered["video_url"], headers={"Range": "bytes=0-1023"})
    assert video.status_code == 206 and video.headers["content-type"] == "video/mp4"
    assert client.get(f"/api/files/lesson/{lid}.mp4").status_code == 200

    assert client.post(f"/api/lessons/{lid}/publish/tiktok", json={"open_id": "o1"}).status_code == 409
    assert client.post(f"/api/lessons/{lid}/approve").json()["status"] == "approved"
    import apps.publish.tiktok_bridge as tb
    monkeypatch.setattr(tb, "send_draft", lambda path, open_id, ref, **kw: {"publish_id": "p_1",
                                                                             "status": "SEND_TO_USER_INBOX"})
    pjob = client.post(f"/api/lessons/{lid}/publish/tiktok", json={"open_id": "o1"}).json()
    assert pjob["type"] == "publish_tiktok"
    run_jobs(app)
    assert client.get(f"/api/jobs/{pjob['id']}").json()["status"] == "done"
    pubs = client.get(f"/api/lessons/{lid}/publications").json()["items"]
    assert [(p["platform"], p["status"], p["external_id"]) for p in pubs] == [("tiktok", "sent", "p_1")]
    assert client.get(f"/api/lessons/{lid}").json()["status"] == "published"
