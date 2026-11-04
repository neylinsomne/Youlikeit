from __future__ import annotations

import numpy as np
import pytest

from apps.moments import anchors, features
from tests.moments.conftest import write_wav


# ── audio ───────────────────────────────────────────────────────────

@pytest.mark.integration
def test_loudness_envelope_and_peaks_find_the_scream(tmp_path):
    wav = write_wav(tmp_path / "a.wav", 120, loud_at=[(60.0, 61.0)])
    env = features.loudness_envelope(wav)
    assert env.shape[0] == 1200                                   # 120 s / 100 ms
    prof = features.AudioProfile.from_env(env)
    assert prof.onset[600] > 20 and abs(prof.onset[300]) < 5     # subida brusca solo en el grito
    assert any(abs(p - 60_000) <= 1000 for p in features.energy_peaks(prof))
    assert prof.rank(float(env.max())) == 1.0 and prof.rank(-200.0) == 0.0


@pytest.mark.unit
def test_peaks_are_relative_to_each_film_mix():
    """Película con mucho silencio (MAD alto): el z global no ve el pico; el percentil sí."""
    rng = np.random.default_rng(1)
    env = np.concatenate([rng.normal(-60, 2, 3000), rng.normal(-25, 3, 3000)])   # silencio + diálogo
    env[4500:4510] = -12.0                                                         # disparo
    peaks = features.energy_peaks(features.AudioProfile.from_env(env), top_n=3)
    assert any(abs(p - 450_000) <= 1000 for p in peaks)


@pytest.mark.unit
def test_window_signals_ranges_and_importance_is_explainable():
    env = np.full(1000, -30.0)
    env[500:520] = -10.0
    prof = features.AudioProfile.from_env(env)
    sig = features.window_signals(49_000, 55_000, audio=prof,
                                  shot_starts=[50_000, 51_000, 52_000, 53_000],
                                  text="Get down! Now! Get in the cellar!", words=7, position=0.85,
                                  quote_score=0.95, plot_score=0.4, cue_hits=2)
    assert all(0.0 <= v <= 1.0 for v in sig.values())
    assert sig["loudness"] == 1.0 and sig["sudden_onset"] == 1.0
    assert sig["climax_position"] == pytest.approx(1.0)
    score, contrib = features.importance(sig)
    assert score == pytest.approx(sum(contrib.values()), abs=1e-3)
    assert max(contrib, key=contrib.get) == "quote_anchor"        # la cita célebre es lo que más pesa


# ── Wikiquote / trama ───────────────────────────────────────────────

@pytest.mark.unit
def test_parse_wikiquote_real_page(wq_wikitext):
    quotes = anchors.parse_wikiquote(wq_wikitext)
    texts = [q["text"] for q in quotes]
    assert any(t.startswith("Now get the hell down in the cellar") for t in texts)
    barb = [q for q in quotes if "They're coming to get you, Barbara" in q["text"]]
    assert barb and barb[0]["speaker"] == "Johnny" and barb[0]["section"] == "Dialogue"
    assert not any(q["section"] in ("Taglines", "Cast") for q in quotes)
    assert not any("[[" in t or "'''" in t or "[in a creepy voice]" in t for t in texts)


@pytest.mark.unit
def test_parse_plot_real_section(plot_wikitext):
    sents = anchors.parse_plot(plot_wikitext)
    assert len(sents) >= 15
    assert sents[0].startswith("Siblings Barbra and Johnny drive to a cemetery in rural Pennsylvania")
    assert not any("[[" in s or "<!--" in s for s in sents)


SEGS = [
    {"start_ms": 60_000, "end_ms": 62_000, "text": "Hey, you're still afraid, aren't ya?"},
    {"start_ms": 62_500, "end_ms": 64_500, "text": "They are coming to get you, Barbara."},
    {"start_ms": 65_000, "end_ms": 66_000, "text": "Stop it! You're ignorant!"},
    {"start_ms": 900_000, "end_ms": 905_000, "text": "Now get the hell down in the cellar."},
    {"start_ms": 905_500, "end_ms": 909_000, "text": "You can be the boss down there, I'm boss up here!"},
]


@pytest.mark.unit
def test_match_quotes_handles_asr_variation_and_multi_segment_quotes():
    quotes = [{"text": "They're coming to get you, Barbara!", "speaker": "Johnny"},
              {"text": "Now get the hell down in the cellar. You can be the boss down there, "
                       "I'm boss up here!", "speaker": "Ben"},
              {"text": "A line that was never said in this film at all.", "speaker": "X"}]
    found = {m["speaker"]: m for m in anchors.match_quotes(quotes, SEGS)}
    assert set(found) == {"Johnny", "Ben"}
    assert (found["Johnny"]["start_ms"], found["Johnny"]["end_ms"]) == (62_500, 64_500)
    assert (found["Ben"]["start_ms"], found["Ben"]["end_ms"]) == (900_000, 909_000)


@pytest.mark.unit
def test_align_plot_is_monotonic_and_finds_right_region():
    segs = ([{"start_ms": 10_000, "end_ms": 20_000, "text": "the cemetery grave johnny barbra flowers"}]
            + [{"start_ms": 600_000, "end_ms": 610_000, "text": "board the windows rifle farmhouse ben"}]
            + [{"start_ms": 1_500_000, "end_ms": 1_510_000, "text": "posse sheriff shoot ben dawn"}])
    plot = ["Barbra and Johnny visit the grave at the cemetery.",
            "Ben boards the windows of the farmhouse and finds a rifle.",
            "At dawn the sheriff's posse shoots Ben."]
    al = anchors.align_plot(plot, segs, 1_600_000)
    starts = [a["start_ms"] for a in al]
    assert starts == sorted(starts)
    assert al[0]["start_ms"] <= 10_000 and 570_000 <= al[1]["start_ms"] <= 610_000
    assert al[2]["start_ms"] >= 1_440_000


@pytest.mark.integration
def test_fetch_wikiquote_with_mocked_mediawiki(mocked_http, wq_wikitext):
    api = "https://en.wikiquote.org/w/api.php"
    mocked_http.get(api, match=[__import__("responses").matchers.query_param_matcher(
        {"action": "query", "list": "search", "srsearch": "Night of the Living Dead 1968 film",
         "format": "json", "srlimit": "6"})],
        json={"query": {"search": [{"title": "Night of the Living Dead (film series)"},
                                   {"title": "Night of the Living Dead"},
                                   {"title": "Night of the Living Dead (1990 film)"}]}})
    mocked_http.get(api, json={"parse": {"title": "Night of the Living Dead",
                                         "wikitext": {"*": wq_wikitext}}})
    quotes, url = anchors.fetch_wikiquote("Night of the Living Dead", 1968)
    assert url.endswith("/wiki/Night_of_the_Living_Dead")         # no el remake ni la saga
    assert len(quotes) > 20
