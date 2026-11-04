from __future__ import annotations

import json

import pytest

from apps.moments import labeling, pipeline, retrieval, schema
from integrations.ai import llm_json
from tests.moments.conftest import seed_asset, write_wav

SHOTS = [(i * 5000, (i + 1) * 5000) for i in range(120)]           # 10 min, planos de 5 s


def _seed_notld(conn, tmp_path):
    wav = write_wav(tmp_path / "notld.wav", 600, loud_at=[(420.0, 421.0)])
    aid = seed_asset(conn, title="Night of the Living Dead", year=1968, duration_ms=600_000, shots=SHOTS,
                     audio_path=str(wav), segments=[
                         (61_000, 63_000, "Hey, you're still afraid, aren't ya?"),
                         (63_500, 65_500, "They are coming to get you, Barbara."),
                         (300_000, 304_000, "We have to board up the windows. Get down in the cellar."),
                         (540_000, 544_000, "They're dead. They came back. Shoot them in the head."),
                     ])
    work_id = conn.execute("SELECT work_id FROM media_assets WHERE id = ?", (aid,)).fetchone()[0]
    schema.save_work_texts(conn, work_id, "wikiquote",
                           [{"text": "They're coming to get you, Barbara!", "speaker": "Johnny"}])
    schema.save_work_texts(conn, work_id, "plot", ["Barbra and Johnny visit a cemetery.",
                                                   "Ben boards up the windows of the farmhouse.",
                                                   "The dead return and are shot in the head."])
    return aid


@pytest.mark.integration
def test_detect_moments_end_to_end_offline(mconn, tmp_path):
    aid = _seed_notld(mconn, tmp_path)
    rep = pipeline.detect_moments(mconn, aid, fetch_anchors=False)
    assert rep["candidates"] >= 4 and rep["quotes"] == {"found": 1, "matched": 1}
    assert rep["energy_peaks"] == 1

    rows = mconn.execute("SELECT id, start_ms, end_ms, signal_score, anchors_json, features_json "
                         "FROM moments WHERE asset_id = ? ORDER BY signal_score DESC", (aid,)).fetchall()
    top = rows[0]
    assert json.loads(top["anchors_json"])["quote"].startswith("They're coming")   # la cita célebre gana
    # Inicio: el plano empieza 1 s antes del diálogo → se ajusta al corte (60 s).
    # Final: el plano sigue 4.5 s después → se corta en la palabra + 250 ms, no se estira.
    assert (top["start_ms"], top["end_ms"]) == (60_000, 65_750)
    feats = json.loads(top["features_json"])
    assert feats["contrib"]["quote_anchor"] > 0

    labels = {(r["dimension"], r["value"], r["source"]) for r in mconn.execute(
        "SELECT dimension, value, source FROM moment_labels")}
    assert ("trope", "siege", "lexical") in labels and ("trope", "the_dead_return", "lexical") in labels
    peak = [r for r in rows if 415_000 <= r["start_ms"] <= 421_000 <= r["end_ms"]]
    assert peak, "el grito sin diálogo también es candidato"

    # Re-detectar no duplica y respeta lo ya etiquetado.
    mconn.execute("UPDATE moments SET status = 'labeled' WHERE id = ?", (top["id"],))
    pipeline.detect_moments(mconn, aid, fetch_anchors=False)
    assert mconn.execute("SELECT COUNT(*) FROM moments WHERE start_ms = ? AND end_ms = ?",
                         (top["start_ms"], top["end_ms"])).fetchone()[0] == 1


@pytest.mark.unit
def test_schema_and_prompt_are_built_from_vocab():
    sch = labeling.build_schema()
    item = sch["properties"]["items"]["items"]
    assert "siege" in item["properties"]["tropes"]["items"]["enum"]
    prompt = labeling.build_prompt("Night of the Living Dead", 1968, [
        {"id": 7, "start_ms": 63_000, "end_ms": 66_000, "position": 0.1, "text": "They're coming",
         "anchors": {"quote": "They're coming to get you, Barbara!", "plot": "They visit a cemetery."},
         "features": {"cue_tropes": ["the_dead_return"]}}])
    assert "id=7" in prompt and "Cita célebre" in prompt and "- siege:" in prompt


@pytest.mark.integration
def test_label_moments_with_fake_llm_blends_importance(mconn, tmp_path, monkeypatch):
    aid = _seed_notld(mconn, tmp_path)
    pipeline.detect_moments(mconn, aid, fetch_anchors=False)

    def fake_llm(prompt, *, schema, **kw):
        ids = [int(x) for x in __import__("re").findall(r"id=(\d+)", prompt)]
        items = [{"id": i, "tropes": ["the_dead_return"], "beat": "climax", "emotion": "dread",
                  "roles": ["monster"], "summary_es": "Los muertos vuelven.", "importance": 0.9,
                  "confidence": 0.8} for i in ids]
        items.append({"id": 999999, "tropes": ["siege"], "beat": "none", "emotion": "fear",
                      "summary_es": "id inventado", "importance": 1, "confidence": 1})
        return {"items": items}, "groq"

    monkeypatch.setattr(llm_json, "complete_json", fake_llm)
    rep = pipeline.label_asset(mconn, aid, top_k=3, batch_size=2)
    assert rep["labeled"] == 3 and rep["providers"] == {"groq": 3}
    r = mconn.execute("SELECT importance, signal_score, status, labeled_by, summary_es FROM moments "
                      "WHERE status = 'labeled' ORDER BY importance DESC").fetchone()
    assert r["labeled_by"] == "llm:groq" and r["summary_es"] == "Los muertos vuelven."
    assert r["importance"] == pytest.approx(0.6 * r["signal_score"] + 0.4 * 0.9, abs=1e-3)
    assert mconn.execute("SELECT COUNT(*) FROM moment_labels WHERE moment_id = 999999").fetchone()[0] == 0


@pytest.mark.integration
def test_label_moments_without_llm_reports_and_keeps_weak_labels(mconn, tmp_path, monkeypatch):
    aid = _seed_notld(mconn, tmp_path)
    pipeline.detect_moments(mconn, aid, fetch_anchors=False)
    monkeypatch.setattr(llm_json, "available", lambda name: False)
    rep = pipeline.label_asset(mconn, aid, top_k=5)
    assert rep["labeled"] == 0 and rep["errors"]
    assert mconn.execute("SELECT COUNT(*) FROM moment_labels WHERE source = 'lexical'").fetchone()[0] > 0


def _label(conn, aid, start, value, conf, imp, text):
    cur = conn.execute("INSERT INTO moments (asset_id, start_ms, end_ms, text, importance, summary_es, status) "
                       "VALUES (?, ?, ?, ?, ?, ?, 'labeled')", (aid, start, start + 8000, text, imp, text))
    schema.add_label(conn, cur.lastrowid, "trope", value, conf, "llm:test")


@pytest.mark.integration
def test_find_moments_crosses_works_respects_rights_and_warns(mconn):
    a1 = seed_asset(mconn, title="Night of the Living Dead", year=1968, duration_ms=1, segments=[], shots=[])
    a2 = seed_asset(mconn, title="Horror Express", year=1972, duration_ms=1, segments=[], shots=[])
    a3 = seed_asset(mconn, title="Carnival of Souls", year=1962, duration_ms=1, segments=[], shots=[])
    a4 = seed_asset(mconn, title="Restricted Film", year=1975, duration_ms=1, segments=[], shots=[],
                    rights="restricted")
    _label(mconn, a1, 1000, "the_dead_return", 0.9, 0.95, "the dead rise from the cemetery")
    _label(mconn, a1, 90000, "the_dead_return", 0.9, 0.94, "the dead rise again at the farmhouse")
    _label(mconn, a2, 1000, "the_dead_return", 0.8, 0.7, "the frozen creature thaws and kills")
    _label(mconn, a3, 1000, "the_dead_return", 0.7, 0.6, "ghouls dance in the pavilion")
    _label(mconn, a4, 1000, "the_dead_return", 1.0, 1.0, "should never appear")

    res = retrieval.find_moments(mconn, "trope", "the_dead_return", limit=5, min_works=3)
    titles = [i["title"] for i in res["items"]]
    assert titles == ["Night of the Living Dead", "Horror Express", "Carnival of Souls"]
    assert "Restricted Film" not in titles and "warning" not in res

    two = retrieval.find_moments(mconn, "trope", "the_dead_return", limit=5, min_works=3, max_per_work=2)
    assert [i["title"] for i in two["items"]].count("Night of the Living Dead") == 2

    few = retrieval.find_moments(mconn, "trope", "the_dead_return", min_works=3, min_confidence=0.85)
    assert few["distinct_works"] == 1 and "warning" in few
