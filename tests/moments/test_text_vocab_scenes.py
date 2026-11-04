from __future__ import annotations

import pytest

from apps.moments import scenes, text, vocab


# ── texto ───────────────────────────────────────────────────────────

@pytest.mark.unit
def test_normalize_and_tokens():
    assert text.normalize("¡Están VINIENDO, Bárbara!") == "estan viniendo barbara"
    assert text.normalize("niño") == "niño"
    assert text.tokens("They're coming to get you, Barbara") == ["they're", "coming", "barbara"]


@pytest.mark.unit
def test_tfidf_cosine_ranks_related_docs():
    tf = text.Tfidf(["zombies attack the farmhouse at night", "a love letter in paris",
                     "the dead walk and attack the house"])
    sim = text.cosine_matrix(tf.matrix, tf.matrix)
    assert sim[0, 2] > sim[0, 1]
    assert sim[0, 0] == pytest.approx(1.0, abs=1e-5)


@pytest.mark.unit
def test_fuzzy_ratio_tolerates_asr_noise():
    assert text.fuzzy_ratio("They're coming to get you, Barbara!",
                            "uh they are coming to get you barbara look") > 0.8
    assert text.fuzzy_ratio("They're coming to get you", "a love letter in paris") < 0.5


# ── vocabulario ─────────────────────────────────────────────────────

@pytest.mark.unit
def test_vocab_ids_unique_and_complete():
    v = vocab.load_vocab()
    for dim in vocab.DIMENSIONS:
        ids = vocab.ids(dim)
        assert ids and len(ids) == len(set(ids)), dim
    for t in v["trope"]:
        assert t["desc_es"] and t["desc_en"] and (t["cues_en"] or t["cues_es"]), t["id"]
        assert set(t["themes"]) <= set(vocab.ids("theme")), t["id"]


@pytest.mark.unit
def test_cue_hits_and_parse_spec():
    hits = vocab.trope_cue_hits("They're coming to get you, Barbara! Board up the windows, the cellar!")
    assert hits["the_dead_return"] >= 1 and hits["siege"] >= 2
    assert vocab.trope_cue_hits("Confié en ti, maestro. ¿Cómo pudiste?")["mentor_betrayal"] == 3
    assert vocab.parse_spec("trope:siege") == ("trope", "siege")
    with pytest.raises(ValueError):
        vocab.parse_spec("trope:no_existe")
    with pytest.raises(ValueError):
        vocab.parse_spec("genre:horror")


@pytest.mark.unit
def test_beat_prior_peaks_inside_range():
    pri = vocab.beat_prior(0.88)
    assert pri["climax"] == 1.0 and pri["ordinary_world"] == 0.0


@pytest.mark.unit
def test_sync_vocab_table(mconn):
    n = vocab.sync_vocab_table(mconn)
    assert n == sum(len(x) for x in vocab.load_vocab().values())
    row = mconn.execute("SELECT label_es FROM vocab WHERE dimension='trope' AND value='siege'").fetchone()
    assert row[0] == "Encerrados juntos"


# ── candidatos ──────────────────────────────────────────────────────

SHOTS = [(0, 3000), (3000, 9000), (9000, 9500), (9500, 20000), (20000, 60000)]


@pytest.mark.unit
def test_dialogue_blocks_merge_small_gaps():
    segs = [{"start_ms": 1000, "end_ms": 2000, "text": "Hi."},
            {"start_ms": 2500, "end_ms": 3500, "text": "Hello."},
            {"start_ms": 8000, "end_ms": 9000, "text": "Later."}]
    blocks = scenes.dialogue_blocks(segs)
    assert [(b["start_ms"], b["end_ms"]) for b in blocks] == [(1000, 3500), (8000, 9000)]


@pytest.mark.unit
def test_snap_window_prefers_shot_edges_and_grows_to_min():
    # Diálogo 3.4–8.6 s dentro del plano 3–9 s: se ajusta a los bordes del plano.
    assert scenes.snap_window(3400, 8600, SHOTS, 60000)[:2] == (3000, 9000)
    # Diálogo corto en un plano largo: corte en palabra (+250 ms), luego crece a 4 s por planos.
    s, e, _, _ = scenes.snap_window(25000, 26000, SHOTS, 60000)
    assert e - s >= scenes.MIN_MS and s <= 25000 - 250 and e >= 26000
    # Nunca supera el máximo aunque el plano sea enorme.
    s, e, _, _ = scenes.snap_window(21000, 50000, SHOTS, 60000)
    assert e - s <= scenes.MAX_MS


@pytest.mark.unit
def test_candidate_windows_include_silent_energy_peaks_and_dedupe():
    segs = [{"start_ms": 3400, "end_ms": 8600, "text": "Get in the house!"}]
    cands = scenes.candidate_windows(segs, SHOTS, 60000, energy_peaks_ms=[5000, 40000])
    kinds = [c["kind"] for c in cands]
    assert kinds == ["dialogue", "energy_peak"]          # el pico en 5 s cae dentro del diálogo
    assert all(0 <= c["position"] <= 1 for c in cands)


@pytest.mark.unit
def test_long_block_splits_at_sentence_ends():
    segs = [{"start_ms": i * 4000, "end_ms": i * 4000 + 3500, "text": f"Sentence {i}."} for i in range(10)]
    parts = scenes._split_long({"start_ms": 0, "end_ms": 39500, "segments": segs}, 15000)
    assert len(parts) >= 3 and all(p["end_ms"] - p["start_ms"] <= 15000 for p in parts)
