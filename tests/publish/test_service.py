from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.publish import service, tiktok_bridge, youtube
from apps.supercut import lessons, planner
from tests.supercut.helpers import seed_fear_world


def _approved(conn, *, video: bool = True) -> int:
    seed_fear_world(conn)
    lid = planner.plan_lesson(conn, "emotion:fear")["id"]
    lessons.begin_render(conn, lid)
    path = lessons.video_path(lid)
    if video:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x00" * 100)
    lessons.finish_render(conn, lid, path, 42.0)
    lessons.approve(conn, lid)
    return lid


@pytest.mark.integration
def test_requires_approved_lesson_with_video(pconn):
    seed_fear_world(pconn)
    lid = planner.plan_lesson(pconn, "emotion:fear")["id"]
    with pytest.raises(service.NotApproved):
        service.publish_lesson(pconn, lid, "tiktok", open_id="o1")
    assert isinstance(service.NotApproved("x"), lessons.InvalidState)          # → 409 en la API


@pytest.mark.integration
def test_approved_without_video_is_not_publishable(pconn):
    lid = _approved(pconn, video=False)
    with pytest.raises(service.NotApproved, match="video"):
        service.publish_lesson(pconn, lid, "tiktok", open_id="o1")


@pytest.mark.integration
def test_tiktok_draft_marks_sent_and_lesson_published(pconn, monkeypatch):
    lid = _approved(pconn)
    seen = {}

    def fake_send(path, open_id, lesson_ref, **kw):
        seen.update(path=path, open_id=open_id, ref=lesson_ref)
        return {"publish_id": "p_9", "status": "SEND_TO_USER_INBOX"}

    monkeypatch.setattr(tiktok_bridge, "send_draft", fake_send)
    pub = service.publish_lesson(pconn, lid, "tiktok", open_id="o1")
    assert (pub["status"], pub["external_id"], pub["detail"]) == ("sent", "p_9", "SEND_TO_USER_INBOX")
    assert seen == {"path": lessons.video_path(lid), "open_id": "o1", "ref": f"lesson-{lid}"}
    assert lessons.get_status(pconn, lid) == "published"


@pytest.mark.integration
def test_tiktok_failed_and_bridge_error_mark_publication_failed(pconn, monkeypatch):
    lid = _approved(pconn)
    monkeypatch.setattr(tiktok_bridge, "send_draft", lambda *a, **k: {"publish_id": "p", "status": "FAILED"})
    with pytest.raises(service.PublishError):
        service.publish_lesson(pconn, lid, "tiktok", open_id="o1")

    def boom(*a, **k):
        raise tiktok_bridge.BridgeError("Puente: reconnect", 409)

    monkeypatch.setattr(tiktok_bridge, "send_draft", boom)
    with pytest.raises(service.PublishError, match="reconnect"):
        service.publish_lesson(pconn, lid, "tiktok", open_id="o1")
    pubs = lessons.list_publications(pconn, lid)
    assert [p["status"] for p in pubs] == ["failed", "failed"] and "reconnect" in pubs[1]["detail"]
    assert lessons.get_status(pconn, lid) == "approved"


@pytest.mark.integration
def test_youtube_publish_and_second_platform_after_published(pconn, monkeypatch):
    lid = _approved(pconn)
    future = (datetime.now(UTC) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    seen = {}

    def fake_upload(path, **kw):
        seen.update(kw)
        return {"video_id": "v1", "url": "https://youtu.be/v1", "privacy": kw["privacy"],
                "publish_at": kw["publish_at"]}

    monkeypatch.setattr(youtube, "upload", fake_upload)
    pub = service.publish_lesson(pconn, lid, "youtube", privacy="private", publish_at=future)
    assert (pub["status"], pub["url"]) == ("published", "https://youtu.be/v1") and future in pub["detail"]
    assert seen["duration_s"] == 42.0 and "Carnival of Souls (1962)" in seen["description"]
    assert lessons.get_status(pconn, lid) == "published"
    monkeypatch.setattr(tiktok_bridge, "send_draft", lambda *a, **k: {"publish_id": "p", "status": "PROCESSING_UPLOAD"})
    assert service.publish_lesson(pconn, lid, "tiktok", open_id="o1")["status"] == "sent"


@pytest.mark.integration
def test_youtube_validation_happens_before_creating_publication(pconn):
    lid = _approved(pconn)
    future = (datetime.now(UTC) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with pytest.raises(ValueError):
        service.publish_lesson(pconn, lid, "youtube", privacy="public", publish_at=future)
    with pytest.raises(ValueError):
        service.publish_lesson(pconn, lid, "tiktok")
    assert lessons.list_publications(pconn, lid) == []
