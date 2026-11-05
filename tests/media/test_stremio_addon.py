from __future__ import annotations

import importlib.util
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from apps.media import sources
from apps.media import stremio_addon as st
from apps.media.models import RIGHTS_OWNED, RIGHTS_PUBLIC_DOMAIN, RIGHTS_UNKNOWN, MediaCandidate

BASE = "https://addon.example/cfg-SECRET123"
IA_META = "https://archive.org/metadata/Night.Of.The.Living.Dead_1080p"
IA_URL = "https://archive.org/download/Night.Of.The.Living.Dead_1080p/NightOfTheLivingDead_1080p.mkv"
MANIFEST = {"id": "org.test", "version": "1.0.0", "name": "Mi addon", "resources": ["catalog", "stream"],
            "types": ["movie"], "idPrefixes": ["ylk:"],
            "catalogs": [{"type": "movie", "id": "pd", "extra": [{"name": "search"}]}]}


@pytest.fixture(autouse=True)
def _no_addon_env(monkeypatch):
    monkeypatch.delenv("STREMIO_ADDON_URL", raising=False)
    monkeypatch.delenv("STREMIO_OWN_HOSTS", raising=False)


@pytest.mark.unit
@pytest.mark.parametrize("raw,base", [
    (f"{BASE}/manifest.json", BASE),
    (f"{BASE}/manifest.json?x=1", BASE),
    ("stremio://addon.example/manifest.json", "https://addon.example"),
    ("http://127.0.0.1:7010/", "http://127.0.0.1:7010"),
])
def test_addon_base_url(raw, base):
    assert st.addon_base_url(raw) == base


@pytest.mark.unit
@pytest.mark.parametrize("raw", ["", "   ", "ftp://x/manifest.json", "manifest.json"])
def test_addon_base_url_rejects_bad_values(raw):
    with pytest.raises(st.StremioAddonError):
        st.addon_base_url(raw)


@pytest.mark.unit
def test_only_the_host_is_exposed():
    assert st.addon_host(f"{BASE}/manifest.json") == "addon.example"
    assert st.addon_host("") is None


@pytest.mark.unit
@pytest.mark.parametrize("stream,expected", [
    ({"infoHash": "a" * 40}, ("skip", "torrent")),
    ({"url": "magnet:?xt=urn:btih:abc"}, ("skip", "torrent")),
    ({"ytId": "dQw4w9WgXcQ"}, ("skip", "sin url directa")),
    ({"externalUrl": "https://netflix.com/title/1"}, ("skip", "sin url directa")),
    ({"url": "https://abc.download.real-debrid.com/d/X/movie.mkv"}, ("skip", "debrid")),
    ({"url": "https://nas.local/torbox.app/x.mkv"}, ("unknown", "https://nas.local/torbox.app/x.mkv")),
    ({"url": IA_URL}, ("archive", "Night.Of.The.Living.Dead_1080p")),
    ({"url": "https://ia800300.us.archive.org/12/items/HorrorExpress1972/HorrorExpress.mkv"},
     ("archive", "HorrorExpress1972")),
    ({"url": "http://192.168.1.20:8096/videos/1/stream.mkv"}, ("owned", "http://192.168.1.20:8096/videos/1/stream.mkv")),
    ({"url": "https://cdn.example/movie.mp4"}, ("unknown", "https://cdn.example/movie.mp4")),
    ("not-a-dict", ("skip", "formato inválido")),
])
def test_classify_stream(stream, expected):
    assert st.classify_stream(stream, own=("192.168.1.20",)) == expected


@pytest.mark.unit
def test_debrid_is_rejected_even_if_listed_as_own():
    url = "https://x.real-debrid.com/d/1/movie.mkv"
    assert st.classify_stream({"url": url}, own=("real-debrid.com", "x.real-debrid.com")) == ("skip", "debrid")


def _addon(rsps, *, manifest=MANIFEST, metas=None, streams=None):
    rsps.get(f"{BASE}/manifest.json", json=manifest)
    rsps.get(f"{BASE}/catalog/movie/pd/search=Night%20of%20the%20Living%20Dead.json", json={"metas": metas or []})
    for id_, ss in (streams or {}).items():
        rsps.get(f"{BASE}/stream/movie/{id_}.json", json={"streams": ss})


@pytest.mark.integration
def test_search_reverifies_archive_and_marks_own_hosts(mocked_http, ia_notld_meta):
    _addon(mocked_http,
           metas=[{"id": "ylk:notld", "type": "movie", "name": "Night of the Living Dead", "releaseInfo": "1968"},
                  {"id": "ylk:remake", "type": "movie", "name": "Night of the Living Dead", "releaseInfo": "1990"}],
           streams={"ylk:notld": [{"url": IA_URL}, {"infoHash": "b" * 40},
                                  {"url": "https://x.real-debrid.com/d/1.mkv"},
                                  {"url": "http://192.168.1.20:8096/notld.mkv",
                                   "behaviorHints": {"filename": "notld.mkv", "videoSize": 1234}}]})
    mocked_http.get(IA_META, json=ia_notld_meta)

    prov = st.StremioAddonProvider(f"{BASE}/manifest.json", own=["192.168.1.20"])
    cands = prov.search("Night of the Living Dead", 1968)

    ia, own = cands
    assert (ia.provider, ia.external_id, ia.rights) == ("archive_org", "Night.Of.The.Living.Dead_1080p",
                                                         RIGHTS_PUBLIC_DOMAIN)
    assert ia.extra["via"] == "stremio:addon.example"          # derechos de IA, no del addon
    assert (own.provider, own.external_id, own.rights) == ("stremio", "movie/ylk:notld", RIGHTS_OWNED)
    assert (own.master_uri, own.size_bytes, own.year) == ("http://192.168.1.20:8096/notld.mkv", 1234, 1968)
    assert own.extra["master_file"] == "notld.mkv"
    # el remake de 1990 se filtró por año: nunca se pidieron sus streams
    assert not any("ylk:remake" in c.request.url for c in mocked_http.calls)


@pytest.mark.integration
def test_unknown_host_is_visible_but_not_usable(mocked_http):
    _addon(mocked_http, metas=[{"id": "ylk:x", "name": "Night of the Living Dead"}],
           streams={"ylk:x": [{"url": "https://cdn.example/x.mp4"}]})
    (c,) = st.StremioAddonProvider(f"{BASE}/manifest.json", own=[]).search("Night of the Living Dead")
    assert c.rights == RIGHTS_UNKNOWN and not c.usable


@pytest.mark.integration
def test_get_item_returns_only_the_addon_candidate(mocked_http):
    mocked_http.get(f"{BASE}/manifest.json", json=MANIFEST)
    mocked_http.get(f"{BASE}/stream/movie/ylk:notld.json",
                    json={"streams": [{"url": "http://127.0.0.1:7010/media/notld.mkv"}]})
    prov = st.StremioAddonProvider(f"{BASE}/manifest.json", own=["127.0.0.1"])
    c = prov.get_item("movie/ylk:notld")
    assert (c.provider, c.rights, c.master_uri) == ("stremio", RIGHTS_OWNED, "http://127.0.0.1:7010/media/notld.mkv")
    assert prov.get_item("series/ylk:notld") is None and prov.get_item("bad") is None


@pytest.mark.integration
def test_cinemeta_fallback_for_imdb_only_addons(mocked_http):
    manifest = {**MANIFEST, "resources": ["stream"], "idPrefixes": ["tt"], "catalogs": []}
    mocked_http.get(f"{BASE}/manifest.json", json=manifest)
    mocked_http.get(f"{st.CINEMETA_URL}/catalog/movie/top/search=Horror%20Express.json",
                    json={"metas": [{"id": "tt0068713", "name": "Horror Express", "releaseInfo": "1972"}]})
    mocked_http.get(f"{BASE}/stream/movie/tt0068713.json",
                    json={"streams": [{"url": "http://127.0.0.1/he.mkv"}]})
    (c,) = st.StremioAddonProvider(f"{BASE}/manifest.json", own=["127.0.0.1"]).search("Horror Express", 1972)
    assert (c.external_id, c.title, c.rights) == ("movie/tt0068713", "Horror Express", RIGHTS_OWNED)


@pytest.mark.integration
def test_errors_name_the_host_but_never_the_url_path(mocked_http):
    mocked_http.get(f"{BASE}/manifest.json", status=500)
    with pytest.raises(st.StremioAddonError) as e:
        st.StremioAddonProvider(f"{BASE}/manifest.json").manifest()
    assert "addon.example" in str(e.value) and "SECRET123" not in str(e.value)


@pytest.mark.unit
def test_default_providers_include_stremio_only_when_configured(monkeypatch):
    assert sources.default_providers() == ["local", "archive_org"]
    monkeypatch.setenv("STREMIO_ADDON_URL", f"{BASE}/manifest.json")
    assert sources.default_providers() == ["local", "archive_org", "stremio"]


@pytest.mark.unit
def test_search_all_skips_unavailable_providers_and_dedupes(monkeypatch):
    ia = MediaCandidate(provider="archive_org", external_id="X", title="X", rights=RIGHTS_PUBLIC_DOMAIN)

    class Down:
        def search(self, *a, **k):
            raise st.StremioAddonError("El addon (addon.example) no responde")

    class Same:
        def search(self, *a, **k):
            return [ia]

    provs = {"stremio": Down(), "archive_org": Same(), "local": Same()}
    monkeypatch.setattr(sources, "get_provider", lambda name, **kw: provs[name])
    errors: list[str] = []
    out = sources.search_all("X", providers=["stremio", "archive_org", "local"], errors=errors)
    assert out == [ia]
    assert errors == ["stremio: El addon (addon.example) no responde"]


# ── addon de prueba (scripts/testing/mock_stremio_addon.py) ────────────

def _load_mock():
    path = Path(__file__).resolve().parents[2] / "scripts" / "testing" / "mock_stremio_addon.py"
    spec = importlib.util.spec_from_file_location("mock_stremio_addon", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mock_addon(tmp_path):
    media = tmp_path / "movies"
    media.mkdir()
    (media / "Mi Pelicula (1975).mp4").write_bytes(bytes(range(256)) * 4)
    mod = _load_mock()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), mod.make_handler(media, 0)[0])
    port = srv.server_address[1]
    srv.RequestHandlerClass = mod.make_handler(media, port)[0]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()
    srv.server_close()


@pytest.mark.integration
def test_mock_addon_end_to_end(mock_addon, mocked_http, ia_notld_meta):
    mocked_http.add_passthru(mock_addon)
    mocked_http.get(IA_META, json=ia_notld_meta)
    prov = st.StremioAddonProvider(f"{mock_addon}/manifest.json", own=["127.0.0.1"])

    (notld,) = prov.search("night of the living", 1968)            # su torrent de ejemplo se descartó
    assert (notld.provider, notld.rights) == ("archive_org", RIGHTS_PUBLIC_DOMAIN)

    (mine,) = prov.search("mi pelicula", 1975)
    assert (mine.provider, mine.rights, mine.size_bytes) == ("stremio", RIGHTS_OWNED, 1024)
    assert prov.get_item(mine.external_id).master_uri == mine.master_uri

    # el archivo propio se sirve con Range (ffmpeg corta por rangos sin bajar todo)
    head = urllib.request.urlopen(urllib.request.Request(mine.master_uri, method="HEAD"), timeout=5)
    assert head.headers["Accept-Ranges"] == "bytes"
    part = urllib.request.urlopen(urllib.request.Request(mine.master_uri, headers={"Range": "bytes=10-19"}),
                                  timeout=5)
    assert part.status == 206 and part.read() == bytes(range(10, 20))
    assert part.headers["Content-Range"] == "bytes 10-19/1024"
