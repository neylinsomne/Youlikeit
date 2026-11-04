from __future__ import annotations

import pytest

from apps.media import archive_org as ia
from apps.media.models import RIGHTS_OPEN, RIGHTS_PUBLIC_DOMAIN, RIGHTS_RESTRICTED, RIGHTS_UNKNOWN


@pytest.mark.unit
@pytest.mark.parametrize("url,rights,expected", [
    ("http://creativecommons.org/licenses/publicdomain/", None, RIGHTS_PUBLIC_DOMAIN),
    ("http://creativecommons.org/publicdomain/mark/1.0/", None, RIGHTS_PUBLIC_DOMAIN),
    ("https://creativecommons.org/publicdomain/zero/1.0/", None, RIGHTS_PUBLIC_DOMAIN),
    ("", "Public Domain", RIGHTS_PUBLIC_DOMAIN),
    ("http://creativecommons.org/licenses/by/4.0/", None, RIGHTS_OPEN),
    ("http://creativecommons.org/licenses/by-sa/3.0/", None, RIGHTS_OPEN),
    ("http://creativecommons.org/licenses/by-nc/3.0/", None, RIGHTS_RESTRICTED),
    ("http://creativecommons.org/licenses/by-nd/4.0/", None, RIGHTS_RESTRICTED),
    ("", None, RIGHTS_UNKNOWN),
])
def test_classify_rights(url, rights, expected):
    assert ia.classify_rights(url, rights) == expected


@pytest.mark.unit
def test_length_parsing_accepts_seconds_and_clock():
    assert ia._length_s({"length": "5752.82"}) == pytest.approx(5752.82)
    assert ia._length_s({"length": "95:51"}) == pytest.approx(5751)
    assert ia._length_s({"length": "01:35:06"}) == pytest.approx(5706)


@pytest.mark.unit
def test_pick_master_prefers_indexed_high_bitrate_original(ia_notld_meta):
    master, proxy = ia.pick_master_and_proxy(ia_notld_meta["files"])
    # 1080p: m2ts (sin índice) < PS3.mp4 (2.6 Mbps) < 1080p.mkv (16 Mbps)
    assert master["name"] == "NightOfTheLivingDead_1080p.mkv"
    # El proxy es el derivado más liviano DE ESE master (misma línea de tiempo).
    assert proxy["name"] == "NightOfTheLivingDead_1080p_512kb.mp4"
    assert proxy["original"] == master["name"]


@pytest.mark.unit
def test_pick_master_ignores_gif_audio_and_subs(ia_notld_meta):
    only_junk = [f for f in ia_notld_meta["files"] if f["name"].endswith((".gif", ".srt", ".mp3"))]
    assert ia.pick_master_and_proxy(only_junk) == (None, None)


@pytest.mark.unit
def test_candidate_from_metadata(ia_notld_meta):
    cand = ia.candidate_from_metadata(ia_notld_meta)
    assert cand.provider == "archive_org"
    assert cand.external_id == "Night.Of.The.Living.Dead_1080p"
    assert cand.year == 1968
    assert cand.rights == RIGHTS_PUBLIC_DOMAIN and cand.usable
    assert cand.master_uri.endswith("/Night.Of.The.Living.Dead_1080p/NightOfTheLivingDead_1080p.mkv")
    assert cand.proxy_uri.endswith("NightOfTheLivingDead_1080p_512kb.mp4")
    assert cand.duration_ms == 5752800
    assert cand.height == 1080


@pytest.mark.unit
def test_search_query_has_collections_and_year_window():
    q = ia.build_search_query('Night of the "Living" Dead', 1968)
    assert "title:(Night of the  Living  Dead)" in q
    assert "collection:feature_films" in q and "mediatype:movies" in q
    assert "year:[1967 TO 1969]" in q


@pytest.mark.integration
def test_provider_search_with_mocked_http(mocked_http, ia_notld_meta):
    mocked_http.get(ia.SEARCH_URL, json={"response": {"numFound": 1, "docs": [
        {"identifier": "Night.Of.The.Living.Dead_1080p", "downloads": 316103}]}})
    mocked_http.get(ia.METADATA_URL.format(identifier="Night.Of.The.Living.Dead_1080p"),
                    json=ia_notld_meta)
    found = ia.ArchiveOrgProvider().search("Night of the Living Dead", 1968)
    assert len(found) == 1
    assert found[0].extra["downloads"] == 316103
    assert found[0].extra["master_file"] == "NightOfTheLivingDead_1080p.mkv"


@pytest.mark.unit
def test_partial_dvd_item_is_flagged(ia_notld_meta):
    meta = {"metadata": {**ia_notld_meta["metadata"], "runtime": "01:35:06"},
            "files": [{"name": "VTS_01_2.mp4", "source": "original", "format": "h.264",
                       "size": "900000000", "length": "2538.0", "height": "480"}]}
    cand = ia.candidate_from_metadata(meta)
    assert cand.extra["partial"] is True
    full = ia.candidate_from_metadata({**ia_notld_meta,
                                       "metadata": {**ia_notld_meta["metadata"], "runtime": "01:35:06"}})
    assert full.extra["partial"] is False


@pytest.mark.unit
def test_unindexed_mpeg_original_uses_same_timeline_h264_derivative():
    """Grave of the Vampire (IA): el original es un MPEG-PS de DVD donde ffmpeg no puede saltar."""
    files = [
        {"name": "G.avi", "source": "original", "format": "Cinepack", "size": "803519542", "length": "5380.6", "height": "384"},
        {"name": "G.mpeg", "source": "original", "format": "MPEG2", "size": "1371951104", "length": "5380.16", "height": "480"},
        {"name": "G.mp4", "source": "derivative", "format": "h.264", "size": "558133988", "length": "5380.21",
         "height": "480", "original": "G.mpeg"},
        {"name": "G_512kb.mp4", "source": "derivative", "format": "512Kb MPEG4", "size": "390849989",
         "length": "5380.04", "height": "240", "original": "G.mpeg"},
    ]
    master, proxy = ia.pick_master_and_proxy(files)
    assert master["name"] == "G.mp4" and proxy["name"] == "G_512kb.mp4"
