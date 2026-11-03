from __future__ import annotations

from pathlib import Path

import pytest

from apps.media import fetch
from apps.media.models import Mezzanine

REMOTE = "https://archive.org/download/x/film.mkv"


@pytest.mark.unit
def test_extract_cmd_seeks_before_input_and_keeps_timestamps():
    cmd = fetch.build_extract_cmd(REMOTE, 1_798_500, 13_000, "out.mkv")
    i = cmd.index("-i")
    assert cmd.index("-ss") < i and cmd.index("-t") < i          # seek + duración de ENTRADA
    assert cmd[cmd.index("-ss") + 1] == "1798.500"
    assert "-copyts" in cmd and cmd[cmd.index("-c") + 1] == "copy"
    assert cmd[cmd.index("-f") + 1] == "matroska"
    assert "-reconnect" in cmd                                    # entrada HTTP


@pytest.mark.unit
def test_extract_cmd_local_has_no_http_flags():
    assert "-reconnect" not in fetch.build_extract_cmd("E:/movies/film.mkv", 0, 1000, "o.mkv")


@pytest.mark.unit
def test_cache_key_depends_on_range():
    a = fetch.cache_key(REMOTE, 1000, 2000, 1500)
    assert a == fetch.cache_key(REMOTE, 1000, 2000, 1500)
    assert a != fetch.cache_key(REMOTE, 1000, 2001, 1500)


@pytest.mark.unit
def test_cut_cmd_uses_offset_relative_to_mezzanine_start():
    mezz = Mezzanine(path="m.mkv", start_ms=1_796_288, end_ms=1_811_520,
                     requested_start_ms=1_800_000, requested_end_ms=1_810_000)
    assert mezz.offset_ms == 3712
    cmd = fetch.build_cut_cmd(mezz, 1_800_000, 1_810_000, "out.mp4")
    assert cmd[cmd.index("-ss") + 1] == "3.712"
    assert cmd[cmd.index("-t") + 1] == "10.000"
    with pytest.raises(ValueError):
        fetch.build_cut_cmd(mezz, 1_790_000, 1_800_000, "out.mp4")


@pytest.mark.integration
def test_extract_segment_retries_when_keyframe_inside_range_and_caches(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(fetch.ff, "run", lambda args, **kw: calls.append(args) or None)
    bounds = iter([(1_799_000, 1_811_000),      # 1er intento: keyframe adentro → no cubre
                   (1_794_000, 1_812_000)])     # 2do intento con más padding: cubre
    monkeypatch.setattr(fetch, "measure_bounds", lambda p: next(bounds))

    mezz = fetch.extract_segment("E:/movies/film.mkv", 1_798_000, 1_810_000, cache_dir=tmp_path)
    assert len(calls) == 2
    assert (mezz.start_ms, mezz.end_ms) == (1_794_000, 1_812_000)
    assert not mezz.cached

    Path(mezz.path).write_bytes(b"mkv")      # el run simulado no escribe el archivo
    again = fetch.extract_segment("E:/movies/film.mkv", 1_798_000, 1_810_000, cache_dir=tmp_path)
    assert again.cached and len(calls) == 2  # no vuelve a llamar a ffmpeg


@pytest.mark.unit
def test_extract_segment_rejects_empty_range(tmp_path):
    with pytest.raises(ValueError):
        fetch.extract_segment(REMOTE, 5000, 5000, cache_dir=tmp_path)
