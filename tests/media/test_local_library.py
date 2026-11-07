from __future__ import annotations

import sys
from pathlib import Path

import pytest

from apps.media.local_library import LocalLibraryProvider, parse_filename
from apps.media.models import RIGHTS_OWNED

CASES = [
    ("Night.of.the.Living.Dead.1968.1080p.BluRay.x264.mkv",
     ("Night of the Living Dead", 1968, None, None)),
    ("Columbo/Season 1/Columbo.S01E03.Murder.by.the.Book.mkv", ("Columbo", None, 1, 3)),
    ("El Chavo/Temporada 2/S02E05.mkv", ("El Chavo", None, 2, 5)),
    ("The Twilight Zone 1x02.avi", ("The Twilight Zone", None, 1, 2)),
]


def _check(parsed, expected):
    title, year, season, episode = expected
    assert parsed.title.lower() == title.lower()
    assert parsed.year == year
    assert parsed.season == season
    assert parsed.episode == episode


@pytest.mark.unit
@pytest.mark.parametrize("rel,expected", CASES)
def test_parse_filename_regex_fallback(monkeypatch, rel, expected):
    monkeypatch.setitem(sys.modules, "guessit", None)   # fuerza el camino regex
    _check(parse_filename(Path(rel)), expected)


@pytest.mark.unit
@pytest.mark.parametrize("rel,expected", CASES)
def test_parse_filename_guessit(rel, expected):
    pytest.importorskip("guessit")
    _check(parse_filename(Path(rel)), expected)


@pytest.mark.integration
def test_scan_and_search(tmp_path):
    (tmp_path / "Night.of.the.Living.Dead.1968.mkv").write_bytes(b"x")
    (tmp_path / "Columbo" / "Season 1").mkdir(parents=True)
    (tmp_path / "Columbo" / "Season 1" / "Columbo.S01E01.mkv").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("not a video")
    prov = LocalLibraryProvider(tmp_path)

    cands = prov.scan()
    assert len(cands) == 2 and all(c.rights == RIGHTS_OWNED and c.usable for c in cands)

    hit = prov.search("night of the living dead", 1968)
    assert hit and hit[0].year == 1968 and hit[0].kind == "movie"
    ep = prov.search("Columbo")
    assert ep and ep[0].kind == "episode" and (ep[0].season, ep[0].episode) == (1, 1)


@pytest.mark.unit
def test_missing_root_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        LocalLibraryProvider(tmp_path / "usb_desconectada").scan()
