from __future__ import annotations

import pytest

from apps.supercut import lessons, planner, script
from integrations.ai import llm_json
from tests.supercut.helpers import seed_fear_world


@pytest.fixture
def lesson(sconn):
    seed_fear_world(sconn)
    return planner.plan_lesson(sconn, "emotion:fear")


def _llm_reply(n: int, *, year: int | None = None) -> dict:
    return {"hook": "¿Qué hace el miedo con tu cuerpo?", "outro": "Pausa. Respira lento.",
            "segments": [{"idx": i, "narration": f"Tramo {i}." + (f" En {year}." if year and i == 0 else ""),
                          "caption": f"Caption {i}"} for i in range(n)]}


@pytest.mark.unit
def test_template_script_uses_vocab_and_db_facts():
    tpl = script.template_script("emotion", "fear", [{"work_title": "Nosferatu", "work_year": 1922},
                                                    {"work_title": "Sin año", "work_year": None}])
    assert tpl["hook"].startswith("Miedo")
    assert [s["idx"] for s in tpl["segments"]] == [0, 1]
    assert tpl["segments"][0]["narration"].startswith("Nosferatu, 1922.")
    assert tpl["segments"][1]["narration"].startswith("Sin año.")
    en = script.template_script("trope", "mentor_betrayal", [{"work_title": "X", "work_year": 1990}], lang="en")
    assert en["hook"].startswith("The mentor betrays.")


@pytest.mark.integration
def test_generate_script_with_llm_updates_script_and_captions(sconn, lesson, monkeypatch):
    seen = {}

    def fake(prompt, *, schema, system, provider, temperature, max_tokens):
        seen.update(prompt=prompt, schema=schema, system=system, provider=provider)
        return _llm_reply(3, year=1968), "groq"

    monkeypatch.setattr(llm_json, "complete_json", fake)
    lessons.begin_render(sconn, lesson["id"])
    lessons.finish_render(sconn, lesson["id"], lessons.video_path(lesson["id"]), 30)
    out = script.generate_script(sconn, lesson["id"], provider="groq")
    assert out["script_source"] == "llm:groq" and out["status"] == "draft"        # editar → draft
    assert [i["caption"] for i in out["items"]] == ["Caption 0", "Caption 1", "Caption 2"]
    assert "Carnival of Souls (1962)" in seen["prompt"] and "Night of the Living Dead (1968)" in seen["prompt"]
    assert "Restricted Film" not in seen["prompt"]
    assert seen["schema"] is lessons.SCRIPT_SCHEMA and seen["provider"] == "groq"
    assert "No inventes" in seen["system"]


@pytest.mark.integration
def test_missing_segments_are_filled_from_template(sconn, lesson, monkeypatch):
    reply = _llm_reply(3)
    reply["segments"] = reply["segments"][:1] + [{"idx": 7, "narration": "fuera", "caption": "x"}]
    monkeypatch.setattr(llm_json, "complete_json", lambda *a, **k: (reply, "gemini"))
    out = script.generate_script(sconn, lesson["id"])
    segs = out["script"]["segments"]
    assert [s["idx"] for s in segs] == [0, 1, 2] and segs[0]["caption"] == "Caption 0"
    assert segs[1]["narration"].startswith("Night of the Living Dead, 1968.")


@pytest.mark.integration
def test_no_llm_keeps_template_and_raises(sconn, lesson, monkeypatch):
    def unavailable(*a, **k):
        raise llm_json.LLMUnavailable("groq: no disponible")

    monkeypatch.setattr(llm_json, "complete_json", unavailable)
    with pytest.raises(script.ScriptUnavailable):
        script.generate_script(sconn, lesson["id"])
    after = lessons.get_lesson(sconn, lesson["id"])
    assert after["script_source"] == "template" and after["script"]["segments"]


@pytest.mark.integration
def test_invented_year_is_rejected_and_manual_script_survives(sconn, lesson, monkeypatch):
    manual = {"hook": "Mío", "outro": "Fin", "segments": [{"idx": i, "narration": "n", "caption": "c"}
                                                           for i in range(3)]}
    lessons.update_lesson(sconn, lesson["id"], script=manual)
    monkeypatch.setattr(llm_json, "complete_json", lambda *a, **k: (_llm_reply(3, year=1999), "groq"))
    with pytest.raises(script.ScriptUnavailable):
        script.generate_script(sconn, lesson["id"])
    after = lessons.get_lesson(sconn, lesson["id"])
    assert after["script"]["hook"] == "Mío" and after["script_source"] == "manual"


@pytest.mark.integration
def test_generate_script_on_locked_lesson_is_invalid_state(sconn, lesson):
    lessons.begin_render(sconn, lesson["id"])
    with pytest.raises(lessons.InvalidState):
        script.generate_script(sconn, lesson["id"])
