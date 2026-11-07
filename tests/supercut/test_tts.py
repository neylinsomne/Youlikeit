from __future__ import annotations

import sys
import types

import pytest

from apps.supercut import tts


def _fake_edge(chunks: list[dict], seen: dict):
    class Communicate:
        def __init__(self, text, voice, *, boundary="SentenceBoundary", **kw):
            seen.update(text=text, voice=voice, boundary=boundary)

        async def stream(self):
            for c in chunks:
                yield c

    return types.SimpleNamespace(Communicate=Communicate)


@pytest.mark.unit
def test_edge_backend_writes_audio_and_word_timings(tmp_path, monkeypatch):
    seen: dict = {}
    chunks = [{"type": "WordBoundary", "offset": 500_000, "duration": 3_000_000, "text": "Hola"},
              {"type": "audio", "data": b"ID3abc"},
              {"type": "WordBoundary", "offset": 4_000_000, "duration": 2_000_000, "text": "mundo"},
              {"type": "audio", "data": b"def"}]
    monkeypatch.setitem(sys.modules, "edge_tts", _fake_edge(chunks, seen))
    path, words = tts.synthesize("Hola mundo", lang="es", out_path=tmp_path / "n.mp3")
    assert path.read_bytes() == b"ID3abcdef"
    assert words == [{"word": "Hola", "start_ms": 50, "end_ms": 350}, {"word": "mundo", "start_ms": 400, "end_ms": 600}]
    assert seen == {"text": "Hola mundo", "voice": "es-MX-DaliaNeural", "boundary": "WordBoundary"}


@pytest.mark.unit
def test_edge_backend_without_audio_raises(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "edge_tts", _fake_edge([], {}))
    with pytest.raises(tts.TTSError):
        tts.synthesize("Hola", lang="es", out_path=tmp_path / "n.mp3")


@pytest.mark.unit
def test_edge_backend_network_error_is_tts_error(tmp_path, monkeypatch):
    class Boom:
        def __init__(self, *a, **k):
            pass

        async def stream(self):
            raise ConnectionError("sin red")
            yield  # pragma: no cover

    monkeypatch.setitem(sys.modules, "edge_tts", types.SimpleNamespace(Communicate=Boom))
    with pytest.raises(tts.TTSError, match="ConnectionError"):
        tts.synthesize("Hola", lang="es", out_path=tmp_path / "n.mp3")


@pytest.mark.unit
def test_local_backend_is_a_stub(tmp_path):
    with pytest.raises(NotImplementedError):
        tts.synthesize("Hola", lang="es", out_path=tmp_path / "n.wav", backend="local")


@pytest.mark.unit
def test_backend_selection_and_voices(monkeypatch):
    with pytest.raises(ValueError):
        tts.get_backend("fish")
    monkeypatch.setenv("TTS_BACKEND", "local")
    assert tts.get_backend().name == "local"
    assert tts.default_voice("en") == "en-US-AriaNeural"
    assert tts.default_voice("es-CO") == "es-CO-SalomeNeural"
    monkeypatch.setenv("TTS_VOICE_ES", "es-CO-SalomeNeural")
    assert tts.default_voice("es") == "es-CO-SalomeNeural"


@pytest.mark.unit
def test_empty_text_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "edge_tts", _fake_edge([], {}))
    with pytest.raises(ValueError):
        tts.synthesize("   ", lang="es", out_path=tmp_path / "n.mp3")


def test_edge_403_explains_how_to_fix():
    from apps.supercut import tts

    async def boom():
        raise RuntimeError("WSServerHandshakeError: 403, message='Invalid response status', url='wss://x?TrustedClientToken=abc'")

    with pytest.raises(tts.TTSError, match="pip install -U edge-tts") as e:
        tts._run_coro(boom, timeout=5)
    assert "TrustedClientToken" not in str(e.value)               # no se vuelca la URL larga
