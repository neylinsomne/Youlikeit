from __future__ import annotations

import sqlite3
import wave
from pathlib import Path

import numpy as np
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def wq_wikitext() -> str:
    return (FIXTURES / "notld_wikiquote.wikitext").read_text(encoding="utf-8")


@pytest.fixture
def plot_wikitext() -> str:
    return (FIXTURES / "notld_plot.wikitext").read_text(encoding="utf-8")


@pytest.fixture
def mconn() -> sqlite3.Connection:
    """DB en memoria con los esquemas de media + moments."""
    from apps.media.schema import ensure_schema as media_schema
    from apps.moments.schema import ensure_schema as moments_schema
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    media_schema(c)
    moments_schema(c)
    yield c
    c.close()


def write_wav(path: Path, seconds: float, loud_at: list[tuple[float, float]] = ()) -> Path:
    """wav 16 kHz mono: ruido bajo + ráfagas fuertes en [(inicio_s, fin_s)]."""
    sr = 16000
    rng = np.random.default_rng(0)
    x = rng.normal(0, 300, int(seconds * sr))
    for a, b in loud_at:
        x[int(a * sr):int(b * sr)] = rng.normal(0, 12000, int((b - a) * sr))
    pcm = np.clip(x, -32768, 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return path


def seed_asset(conn, *, title: str, year: int, duration_ms: int, segments: list[tuple[int, int, str]],
               shots: list[tuple[int, int]], audio_path: str | None = None, rights: str = "public_domain",
               external_id: str | None = None) -> int:
    """Crea obra + asset ya 'indexado' (transcripción + planos) sin tocar ffmpeg."""
    from apps.media import schema as ms
    from apps.media.indexer import register_candidate
    from apps.media.models import MediaCandidate
    aid = register_candidate(conn, MediaCandidate(
        provider="archive_org", external_id=external_id or title, title=title, year=year,
        master_uri=f"https://ia/{title}.mkv", proxy_uri=f"https://ia/{title}.mp4", rights=rights))
    ms.update_asset(conn, aid, duration_ms=duration_ms, fps=24.0)
    if audio_path:
        ms.update_asset(conn, aid, audio_path=audio_path)
    segs = []
    for s, e, text in segments:
        n = max(1, len(text.split()))
        step = (e - s) // n
        segs.append({"start_ms": s, "end_ms": e, "text": text, "lang": "en",
                     "words": [{"start_ms": s + k * step, "end_ms": s + (k + 1) * step, "word": w}
                               for k, w in enumerate(text.split())]})
    ms.save_transcript(conn, aid, segs)
    ms.save_shots(conn, aid, shots, "scdet")
    return aid


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """media_cache (segmentos, análisis, .npy) nunca escribe en el data/ real del repo."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("KEEP_ANALYSIS_FILES", raising=False)
    monkeypatch.delenv("MEDIA_CACHE_MAX_GB", raising=False)
