"""Regresiones encontradas en la primera corrida real (Groq, 3 películas de IA)."""
from __future__ import annotations

import pytest
import responses

from apps.moments import anchors, labeling, schema
from apps.moments.pipeline import detect_moments
from tests.moments.conftest import seed_asset

API = "https://en.wikiquote.org/w/api.php"


@pytest.mark.integration
def test_exact_title_beats_fulltext_search(mocked_http):
    """"Horror Express 1972 film" en búsqueda devolvía páginas de personas."""
    mocked_http.get(API, match=[responses.matchers.query_param_matcher({
        "action": "query", "titles": "Horror Express (1972 film)|Horror Express (film)|Horror Express",
        "redirects": "1", "prop": "pageprops", "ppprop": "disambiguation", "format": "json"})],
        json={"query": {"pages": {
            "-1": {"title": "Horror Express (1972 film)", "missing": ""},
            "-2": {"title": "Horror Express (film)", "missing": ""},
            "42": {"title": "Horror Express", "pageid": 42}}}})
    mocked_http.get(API, match=[responses.matchers.query_param_matcher({
        "action": "parse", "page": "Horror Express", "prop": "wikitext", "format": "json",
        "redirects": "1", "section": "0"})],
        json={"parse": {"wikitext": {"*": "'''Horror Express''' is a 1972 horror film."}}})
    assert anchors._resolve_page("en.wikiquote.org", "Horror Express", 1972) == "Horror Express"


@pytest.mark.integration
def test_disambiguation_pages_are_skipped(mocked_http):
    mocked_http.get(API, json={"query": {"pages": {
        "1": {"title": "Carnival (film)", "pageprops": {"disambiguation": ""}},
        "2": {"title": "Carnival", "pageprops": {"disambiguation": ""}}}}})
    assert anchors._resolve_exact("en.wikiquote.org", "Carnival", None) is None


@pytest.mark.unit
def test_empty_anchor_cache_expires(mconn):
    aid = seed_asset(mconn, title="Grave of the Vampire", year=1974, duration_ms=1000, segments=[], shots=[])
    wid = mconn.execute("SELECT work_id FROM media_assets WHERE id = ?", (aid,)).fetchone()[0]
    schema.save_work_texts(mconn, wid, "plot", [])
    assert schema.get_work_texts(mconn, wid, "plot") == []                  # recién bajado: se respeta
    mconn.execute("UPDATE work_texts SET fetched_at = datetime('now', '-8 days')")
    assert schema.get_work_texts(mconn, wid, "plot") is None                # vacío viejo: reintentar
    schema.save_work_texts(mconn, wid, "plot", ["A sentence about the vampire."])
    mconn.execute("UPDATE work_texts SET fetched_at = datetime('now', '-30 days')")
    assert schema.get_work_texts(mconn, wid, "plot") == ["A sentence about the vampire."]  # lleno: no caduca


@pytest.mark.integration
def test_duplicate_candidate_ranges_do_not_crash(mconn):
    """Cita y bloque de diálogo ajustados al mismo plano → UNIQUE constraint en NOTLD."""
    shots = [(0, 10_000), (10_000, 20_000)]
    aid = seed_asset(mconn, title="Night of the Living Dead", year=1968, duration_ms=20_000, shots=shots,
                     segments=[(2_000, 4_000, "They're coming to get you, Barbara.")])
    wid = mconn.execute("SELECT work_id FROM media_assets WHERE id = ?", (aid,)).fetchone()[0]
    schema.save_work_texts(mconn, wid, "wikiquote", [{"text": "They're coming to get you, Barbara!"}])
    schema.save_work_texts(mconn, wid, "plot", ["x y z w"])
    rep = detect_moments(mconn, aid, fetch_anchors=False, cleanup=False)
    rows = mconn.execute("SELECT start_ms, end_ms FROM moments WHERE asset_id = ?", (aid,)).fetchall()
    assert rep["candidates"] == len(rows) == len({tuple(r) for r in rows})


@pytest.mark.unit
def test_sanitize_items_drops_out_of_vocab_values_per_item():
    data = {"items": [
        {"id": 1, "tropes": ["siege", "not_a_trope"], "beat": "standoff", "emotion": "fear",
         "roles": ["monster", "sidekick"], "summary_es": "x", "importance": 0.5, "confidence": 0.7},
        {"id": 2, "tropes": [], "beat": "climax", "emotion": "joyful", "summary_es": "y",
         "importance": 0.4, "confidence": 0.6}]}
    out = labeling.sanitize_items(data)
    assert [it["id"] for it in out["items"]] == [1]                         # emoción inválida → fuera
    it = out["items"][0]
    assert it["tropes"] == ["siege"] and it["beat"] == "none" and it["roles"] == ["monster"]


@pytest.mark.unit
def test_year_matches_tolerates_release_differences():
    assert anchors.year_matches("is a 1973 British/Spanish horror film", 1972)
    assert anchors.year_matches("Grave of the Vampire is a 1972 American horror film", 1974)
    assert not anchors.year_matches("a 1990 remake", 1968)
