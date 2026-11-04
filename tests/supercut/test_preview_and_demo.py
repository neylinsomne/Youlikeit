from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from apps.media.models import Mezzanine
from apps.supercut import preview
from tests.supercut.helpers import needs_ffmpeg, probe, seed_fear_world

ROOT = Path(__file__).resolve().parents[2]


@needs_ffmpeg
@pytest.mark.integration
def test_moment_preview_is_480p_and_cached(sconn, masters, monkeypatch):
    world = seed_fear_world(sconn, masters)
    mid = world["moments"]["Carnival of Souls"]
    path = preview.moment_preview(sconn, mid)
    assert path.parent == preview.preview_dir() and path.suffix == ".mp4"
    video = next(s for s in probe(path)["streams"] if s["codec_type"] == "video")
    assert video["height"] == preview.PREVIEW_HEIGHT
    assert not list(path.parent.glob("*.part.mp4"))

    def boom(*a, **k):
        raise AssertionError("no debería recodificar: está en caché")

    monkeypatch.setattr(preview, "cut_exact", boom)
    assert preview.moment_preview(sconn, mid) == path


@pytest.mark.integration
def test_moment_preview_unknown_moment(sconn):
    with pytest.raises(preview.MomentNotFound):
        preview.moment_preview(sconn, 12345)


@needs_ffmpeg
@pytest.mark.integration
@pytest.mark.slow
def test_demo_lesson_script_still_builds_with_render_helpers(masters, tmp_path, monkeypatch):
    """scripts/web/make_demo_lesson.py reutiliza render.* y sigue armando el 9:16 (sin red)."""
    spec = importlib.util.spec_from_file_location("make_demo_lesson", ROOT / "scripts" / "web" / "make_demo_lesson.py")
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    start = demo.START_MS - 1_000                     # el master sintético hace de mezzanine (30 s)
    mezz = Mezzanine(path=str(masters["Horror Express"]), start_ms=start, end_ms=start + 30_000,
                     requested_start_ms=demo.START_MS, requested_end_ms=demo.END_MS)
    monkeypatch.setattr(demo, "extract_segment", lambda *a, **k: mezz)
    out = demo.build(tmp_path / "demo.mp4")
    info = probe(out)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (1080, 1920)
    assert abs(float(info["format"]["duration"]) - ((demo.END_MS - demo.START_MS) / 1000 + demo.END_CARD_S)) < 0.3
