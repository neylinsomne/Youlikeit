"""Ciclo de vida: crudo intocable, caché con tope, análisis desechable, render efímero."""
from __future__ import annotations

import os
import time

import pytest

from apps.media import storage
from apps.media.models import media_cache_dir
from apps.moments import pipeline
from tests.moments.conftest import seed_asset, write_wav

SHOTS = [(i * 5000, (i + 1) * 5000) for i in range(24)]


@pytest.mark.integration
def test_prune_segments_removes_least_recently_used_first(tmp_path):
    cache = tmp_path / "segments"
    cache.mkdir()
    now = time.time()
    for i, name in enumerate(["old", "mid", "new"]):
        (cache / f"{name}.mkv").write_bytes(b"x" * 1000)
        (cache / f"{name}.json").write_text("{}")
        os.utime(cache / f"{name}.mkv", (now - 100 + i * 10, now - 100 + i * 10))
    storage.touch(cache / "old.mkv")                      # se volvió a usar → ahora es el más reciente
    out = storage.prune_segments(1500, cache_dir=cache)
    assert out["removed"] == 2 and out["remaining_bytes"] == 1000
    assert [p.stem for p in cache.glob("*.mkv")] == ["old"]
    assert not (cache / "mid.json").exists()


def _asset_with_cached_analysis(conn, tmp_path, *, raw_proxy: bool = False):
    analysis = media_cache_dir("analysis", "1")
    analysis.mkdir(parents=True)
    wav = write_wav(analysis / "audio16k.wav", 120, loud_at=[(100.0, 101.0)])
    proxy = tmp_path / "E" / "raw_movie.mkv" if raw_proxy else analysis / "proxy.mp4"
    proxy.parent.mkdir(parents=True, exist_ok=True)
    proxy.write_bytes(b"p" * 5000)
    aid = seed_asset(conn, title="Night of the Living Dead", year=1968, duration_ms=120_000, shots=SHOTS,
                     audio_path=str(wav), segments=[(30_000, 33_000, "They're coming to get you, Barbara.")])
    conn.execute("UPDATE media_assets SET proxy_path = ? WHERE id = ?", (str(proxy), aid))
    conn.commit()
    return aid, wav, proxy


@pytest.mark.integration
def test_detect_cleans_analysis_keeps_envelope_and_reuses_it(mconn, tmp_path):
    aid, wav, proxy = _asset_with_cached_analysis(mconn, tmp_path)
    first = pipeline.detect_moments(mconn, aid, fetch_anchors=False)
    assert first["cleanup"]["cleared"] == ["audio_path", "proxy_path"]
    assert not wav.exists() and not proxy.exists()
    assert storage.envelope_path(aid).exists() and storage.envelope_path(aid).stat().st_size < 50_000
    row = mconn.execute("SELECT audio_path, proxy_path FROM media_assets WHERE id = ?", (aid,)).fetchone()
    assert tuple(row) == (None, None)

    again = pipeline.detect_moments(mconn, aid, fetch_anchors=False)   # sin wav: usa loudness.npy
    assert again["energy_peaks"] == first["energy_peaks"] >= 1


@pytest.mark.integration
def test_cleanup_never_deletes_raw_files_outside_cache(mconn, tmp_path):
    aid, wav, raw = _asset_with_cached_analysis(mconn, tmp_path, raw_proxy=True)
    pipeline.detect_moments(mconn, aid, fetch_anchors=False)
    assert raw.exists(), "el crudo local nunca se borra"
    assert not wav.exists()


@pytest.mark.integration
def test_keep_analysis_files_env_and_incomplete_assets_are_respected(mconn, tmp_path, monkeypatch):
    aid, wav, proxy = _asset_with_cached_analysis(mconn, tmp_path)
    monkeypatch.setenv("KEEP_ANALYSIS_FILES", "true")
    rep = pipeline.detect_moments(mconn, aid, fetch_anchors=False)
    assert "cleanup" not in rep and wav.exists() and proxy.exists()
    mconn.execute("UPDATE media_assets SET transcribed_at = NULL WHERE id = ?", (aid,))
    assert "skipped" in storage.cleanup_analysis(mconn, aid)          # sin transcripción no se borra nada
    assert wav.exists()


@pytest.mark.unit
def test_work_dir_is_removed_on_success_and_kept_on_failure():
    with storage.work_dir("ok-job") as d:
        (d / "short.mp4").write_bytes(b"v")
    assert not d.exists()
    with pytest.raises(RuntimeError):
        with storage.work_dir("bad-job") as d2:
            raise RuntimeError("render falló")
    assert d2.exists()


@pytest.mark.integration
def test_usage_report(mconn, tmp_path):
    _asset_with_cached_analysis(mconn, tmp_path)
    rep = storage.usage(mconn)
    assert rep["analysis"]["files"] == 2 and rep["segments"]["cap_gb"] == 5.0
    assert rep["raw_remote_not_downloaded"]["assets"] == 1
