from __future__ import annotations

import pytest

from apps.supercut import lessons, planner
from tests.supercut.helpers import add_asset, add_moment, seed_fear_world


@pytest.fixture
def lesson(sconn):
    seed_fear_world(sconn)
    return planner.plan_lesson(sconn, "emotion:fear")


@pytest.mark.integration
def test_plan_creates_draft_in_contract_shape(sconn, lesson):
    assert lesson["status"] == "draft" and lesson["format"] == "essay" and lesson["lang"] == "es"
    assert [i["work_year"] for i in lesson["items"]] == [1962, 1968, 1972]           # orden por año
    assert "Restricted Film" not in [i["work_title"] for i in lesson["items"]]
    item = lesson["items"][0]
    assert set(item) == {"idx", "moment_id", "work_title", "work_year", "in_ms", "out_ms", "caption", "text",
                         "preview_url"}
    assert item["preview_url"] == f"/api/moments/{item['moment_id']}/preview"
    assert lesson["video_url"] is None and lesson["issues"] == 0 and lesson["publications"] == []
    assert lesson["script"]["segments"][0]["idx"] == 0 and lesson["script_source"] == "template"
    assert all(i["caption"] for i in lesson["items"])
    assert lesson["created_at"].endswith("Z")


@pytest.mark.integration
def test_status_machine_and_edit_returns_to_draft(sconn, lesson):
    lid = lesson["id"]
    with pytest.raises(lessons.InvalidState):
        lessons.approve(sconn, lid)                                   # draft → approved: no
    lessons.begin_render(sconn, lid)
    with pytest.raises(lessons.InvalidState):
        lessons.update_lesson(sconn, lid, title="x")                  # rendering está bloqueada
    with pytest.raises(lessons.InvalidState):
        lessons.begin_render(sconn, lid)
    out = lessons.finish_render(sconn, lid, lessons.video_path(lid), 30.456)
    assert out["status"] == "rendered" and out["duration_s"] == 30.46
    assert lessons.reject(sconn, lid, "voz baja")["reject_reason"] == "voz baja"
    with pytest.raises(lessons.InvalidState):
        lessons.approve(sconn, lid)                                   # rejected → approved: no
    edited = lessons.update_lesson(sconn, lid, title="Miedo en el cine")
    assert edited["status"] == "draft" and edited["title"] == "Miedo en el cine"
    lessons.begin_render(sconn, lid)
    lessons.finish_render(sconn, lid, lessons.video_path(lid), 30)
    assert lessons.approve(sconn, lid)["reject_reason"] is None
    lessons.mark_published(sconn, lid)
    assert lessons.get_status(sconn, lid) == "published"
    with pytest.raises(lessons.InvalidState):
        lessons.update_lesson(sconn, lid, title="otra")


@pytest.mark.integration
def test_fail_render_goes_back_to_draft(sconn, lesson):
    lessons.begin_render(sconn, lesson["id"])
    lessons.fail_render(sconn, lesson["id"])
    assert lessons.get_status(sconn, lesson["id"]) == "draft"


@pytest.mark.integration
def test_reject_needs_reason(sconn, lesson):
    lessons.begin_render(sconn, lesson["id"])
    lessons.finish_render(sconn, lesson["id"], lessons.video_path(lesson["id"]), 30)
    with pytest.raises(ValueError):
        lessons.reject(sconn, lesson["id"], "  ")


@pytest.mark.integration
def test_validate_items_rejects_bad_ranges_unknown_and_restricted(sconn):
    world = seed_fear_world(sconn)
    good = world["moments"]["Horror Express"]
    assert lessons.validate_items(sconn, [{"moment_id": good, "in_ms": 0, "out_ms": 10, "caption": " hi "}])[0][
        "caption"] == "hi"
    bad = [
        [{"moment_id": good, "in_ms": 500, "out_ms": 500}],
        [{"moment_id": good, "in_ms": 0, "out_ms": 61_000}],
        [{"moment_id": 99_999, "in_ms": 0, "out_ms": 1000}],
        [{"moment_id": world["moments"]["Restricted Film"], "in_ms": 0, "out_ms": 1000}],
        [{"moment_id": good, "in_ms": "x", "out_ms": 1000}],
    ]
    for items in bad:
        with pytest.raises(ValueError):
            lessons.validate_items(sconn, items)


@pytest.mark.integration
def test_patch_items_and_script(sconn, lesson):
    first = lesson["items"][0]
    out = lessons.update_lesson(sconn, lesson["id"], items=[
        {"moment_id": first["moment_id"], "in_ms": first["in_ms"], "out_ms": first["in_ms"] + 3000,
         "caption": "Nuevo texto"}],
        script={"hook": "¿Qué sientes?", "outro": "Respira.",
                "segments": [{"idx": 0, "narration": "Mira.", "caption": "Nuevo texto"}]})
    assert len(out["items"]) == 1 and out["items"][0]["caption"] == "Nuevo texto"
    assert out["script"]["hook"] == "¿Qué sientes?" and out["script_source"] == "manual"
    with pytest.raises(ValueError):
        lessons.update_lesson(sconn, lesson["id"], script={"hook": "x"})


@pytest.mark.integration
def test_issues_crud(sconn, lesson):
    lid = lesson["id"]
    issue = lessons.add_issue(sconn, lid, issue_type="caption", start_s=3.2, end_s=5.0, note="typo")
    assert set(issue) == {"id", "issue_type", "start_s", "end_s", "note", "created_at"}
    assert lessons.get_lesson(sconn, lid)["issues"] == 1
    with pytest.raises(ValueError):
        lessons.add_issue(sconn, lid, issue_type="music", start_s=0, end_s=1)
    with pytest.raises(ValueError):
        lessons.add_issue(sconn, lid, issue_type="other", start_s=5, end_s=1)
    lessons.delete_issue(sconn, lid, issue["id"])
    assert lessons.list_issues(sconn, lid) == []
    with pytest.raises(lessons.LessonNotFound):
        lessons.delete_issue(sconn, lid, issue["id"])
    with pytest.raises(lessons.LessonNotFound):
        lessons.list_issues(sconn, 999)


@pytest.mark.integration
def test_publications(sconn, lesson):
    pub = lessons.create_publication(sconn, lesson["id"], "tiktok")
    assert pub["status"] == "pending" and pub["platform"] == "tiktok"
    pub = lessons.update_publication(sconn, pub["id"], status="sent", external_id="p_1", detail="SEND_TO_USER_INBOX")
    assert (pub["status"], pub["external_id"]) == ("sent", "p_1")
    assert lessons.get_lesson(sconn, lesson["id"])["publications"][0]["id"] == pub["id"]
    with pytest.raises(ValueError):
        lessons.create_publication(sconn, lesson["id"], "vimeo")


@pytest.mark.integration
def test_list_lessons_filters_by_status(sconn, lesson):
    assert [x["id"] for x in lessons.list_lessons(sconn, "draft")] == [lesson["id"]]
    assert lessons.list_lessons(sconn, "approved") == []
    with pytest.raises(ValueError):
        lessons.list_lessons(sconn, "nope")


@pytest.mark.integration
def test_get_db_creates_supercut_and_studio_tables(tmp_path):
    from core.db import get_db
    conn = get_db(tmp_path)
    try:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        conn.close()
    assert {"lessons", "lesson_items", "lesson_issues", "publications", "studio_jobs"} <= names


@pytest.mark.integration
def test_lesson_not_found(sconn):
    with pytest.raises(lessons.LessonNotFound):
        lessons.get_lesson(sconn, 1)
    aid = add_asset(sconn, title="Solo", year=2000)
    add_moment(sconn, aid, start_ms=0, end_ms=1000)
    with pytest.raises(lessons.LessonNotFound):
        lessons.update_lesson(sconn, 42, title="x")
