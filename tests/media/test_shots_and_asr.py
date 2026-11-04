from __future__ import annotations

from types import SimpleNamespace

import pytest

from apps.media.shots import cuts_to_shots, parse_scdet
from apps.media.transcribe import segments_to_dicts

SCDET_STDERR = """
[Parsed_scdet_1 @ 0000025101499c80] lavfi.scd.score: 14.058, lavfi.scd.time: 3.885
frame=  100 fps=0.0 q=-0.0 size=N/A time=00:00:04.17
[Parsed_scdet_1 @ 0000025101499c80] lavfi.scd.score: 14.876, lavfi.scd.time: 7.848
"""


@pytest.mark.unit
def test_parse_scdet_with_offset():
    assert parse_scdet(SCDET_STDERR) == [3885, 7848]
    assert parse_scdet(SCDET_STDERR, offset_ms=1000) == [4885, 8848]
    assert parse_scdet(SCDET_STDERR, min_score=14.5) == [7848]


@pytest.mark.unit
def test_cuts_to_shots_contiguous_and_merges_flashes():
    shots = cuts_to_shots([3885, 4000, 7848, 9900], 10_000, min_shot_ms=400)
    # 4000 queda a 115 ms del corte anterior → se funde; 9900 deja un plano final de 100 ms → se funde
    assert shots == [(0, 3885), (3885, 7848), (7848, 10_000)]
    assert all(a < b for a, b in shots)
    assert cuts_to_shots([], 5000) == [(0, 5000)]


@pytest.mark.unit
def test_segments_to_dicts_milliseconds_and_words():
    seg = SimpleNamespace(
        start=1.234, end=3.5, text=" They're coming to get you, Barbara. ",
        avg_logprob=-0.21, no_speech_prob=0.01,
        words=[SimpleNamespace(start=1.234, end=1.5, word=" They're", probability=0.98),
               SimpleNamespace(start=1.5, end=1.81, word=" coming", probability=0.97)],
    )
    empty = SimpleNamespace(start=4, end=5, text="  ", avg_logprob=0, no_speech_prob=0.9, words=[])
    out = segments_to_dicts([seg, empty], "en")
    assert len(out) == 1
    assert out[0]["start_ms"] == 1234 and out[0]["end_ms"] == 3500
    assert out[0]["text"] == "They're coming to get you, Barbara."
    assert out[0]["words"][1] == {"start_ms": 1500, "end_ms": 1810, "word": " coming", "prob": 0.97}


@pytest.mark.unit
def test_load_wav_16k_reads_pcm16_mono(tmp_path):
    import wave

    import numpy as np

    from apps.media.transcribe import load_wav_16k
    path = tmp_path / "a.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(np.array([0, 16384, -32768], dtype=np.int16).tobytes())
    audio = load_wav_16k(path)
    assert audio.dtype == np.float32 and list(audio) == [0.0, 0.5, -1.0]

    bad = tmp_path / "b.wav"
    with wave.open(str(bad), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(bytes(8))
    with pytest.raises(ValueError):
        load_wav_16k(bad)
