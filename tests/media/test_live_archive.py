"""Criterios de salida de la Fase 1 contra Internet Archive REAL.

Saltado por defecto (marker `network`). Correr con:
    python -m pytest tests/media/test_live_archive.py -m network -v

Usa "Night of the Living Dead" (1968), dominio público.
"""
from __future__ import annotations

import re
import shutil

import pytest

from apps.media import fetch
from apps.media.archive_org import ArchiveOrgProvider
from utils import ffmpeg as ff

IDENTIFIER = "Night.Of.The.Living.Dead_1080p"
START_MS, END_MS = 1_800_000, 1_810_000          # 30:00 → 30:10

pytestmark = [pytest.mark.network, pytest.mark.slow,
              pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg no instalado")]


@pytest.fixture(scope="module")
def candidate():
    cand = ArchiveOrgProvider().get_item(IDENTIFIER)
    assert cand is not None and cand.usable
    return cand


def _psnr(a, b) -> float:
    out = ff.run(["ffmpeg", "-hide_banner", "-i", str(a), "-i", str(b), "-lavfi", "psnr",
                  "-f", "null", "-"]).stderr
    m = re.search(r"average:(inf|[\d.]+)", out)
    return float("inf") if m.group(1) == "inf" else float(m.group(1))


def test_ten_second_clip_downloads_under_5_percent(candidate, tmp_path):
    mezz = fetch.extract_segment(candidate.master_uri, START_MS, END_MS,
                                 cache_dir=tmp_path, measure=True)
    assert mezz.start_ms <= START_MS and mezz.end_ms >= END_MS
    fraction = mezz.bytes_transferred / candidate.size_bytes
    assert fraction < 0.05, f"bajó {fraction:.2%} del archivo"


def test_exact_cut_matches_reference_frame(candidate, tmp_path):
    mezz = fetch.extract_segment(candidate.master_uri, START_MS, END_MS, cache_dir=tmp_path)
    clip = fetch.cut_exact(mezz, START_MS, END_MS, tmp_path / "clip.mp4")

    info = ff.summarize_probe(ff.probe(clip))
    frame_ms = 1000 / (info["fps"] or 24)
    assert abs(info["duration_ms"] - (END_MS - START_MS)) <= 2 * frame_ms

    ref = tmp_path / "ref.png"
    first = tmp_path / "first.png"
    ff.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *ff.HTTP_INPUT_FLAGS,
            "-ss", ff.ms_to_ts(START_MS), "-i", candidate.master_uri, "-frames:v", "1", str(ref)])
    ff.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(clip),
            "-frames:v", "1", str(first)])
    # El clip se recodifica: PSNR alto (no idéntico) = mismo frame; un frame
    # vecino en esta película da ~25 dB.
    assert _psnr(first, ref) > 35
