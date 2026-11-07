from __future__ import annotations

import pytest

from apps.media.models import MediaCandidate
from apps.studio.serializers import moments_by_ids


@pytest.mark.integration
def test_overview_counts_storage_credentials_without_secrets(client, world, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_very_secret_value")
    monkeypatch.delenv("GROQ_LLM_MODEL", raising=False)
    monkeypatch.setenv("WEB_BASE_URL", "https://web.example")
    body = client.get("/api/overview").json()
    assert body["counts"]["works"] == 4 and body["counts"]["assets"] == 4 and body["counts"]["moments"] == 4
    assert body["counts"]["moments_labeled"] == 4 and body["counts"]["assets_indexed"] == 0
    assert set(body["counts"]["lessons"]) == {"draft", "rendering", "rendered", "approved", "rejected", "published"}
    assert {"segments", "analysis", "work", "db_mb"} <= set(body["storage"])
    creds = {c["name"]: c["status"] for c in body["credentials"]}
    assert creds["Groq"] == "OK" and creds["Puente TikTok (web)"] == "MISSING"
    assert set(creds.values()) <= {"OK", "MISSING"}
    assert body["settings"]["groq_model"] == "openai/gpt-oss-120b"
    assert body["settings"]["web_base_url"] == "https://web.example" and body["jobs"] == []
    assert "gsk_very_secret_value" not in client.get("/api/overview").text


@pytest.mark.integration
def test_works_and_assets_shapes(client, world, db):
    works = client.get("/api/works").json()["items"]
    assert [w["year"] for w in works] == [1962, 1968, 1972, 1980]
    assert set(works[0]) == {"id", "kind", "title", "year", "assets"} and works[0]["assets"] == 1
    db.execute("UPDATE media_assets SET fps = 23.976, transcribed_at = CURRENT_TIMESTAMP, "
               "shots_at = CURRENT_TIMESTAMP WHERE id = ?", (world["assets"]["Horror Express"],))
    db.commit()
    wid = next(w["id"] for w in works if w["title"] == "Horror Express")
    items = client.get(f"/api/assets?work_id={wid}").json()["items"]
    assert len(items) == 1
    a = items[0]
    assert set(a) == {"id", "work_id", "work_title", "work_year", "provider", "external_id", "rights", "duration_ms",
                      "height", "fps", "accept_ranges", "steps", "moments", "moments_labeled"}
    assert a["steps"] == {"probe": True, "proxy": False, "analyze": True, "asr": True, "shots": True}
    assert (a["moments"], a["moments_labeled"]) == (1, 1)
    assert client.get("/api/overview").json()["counts"]["assets_indexed"] == 1


@pytest.mark.integration
def test_media_search_maps_candidates_and_errors(client, monkeypatch):
    import apps.media.sources as sources
    seen = {}

    def fake_search(title, year=None, *, providers=None, only_usable=True, limit=10, errors=None):
        seen.update(title=title, year=year, providers=providers, only_usable=only_usable)
        errors.append("local: MOVIES_DIR no disponible")
        return [MediaCandidate(provider="archive_org", external_id="HorrorExpress1972", title="Horror Express",
                               year=1972, rights="public_domain", height=720, duration_ms=5_265_024,
                               extra={"master_file": "HE.mkv", "proxy_file": "HE_512kb.mp4"})]

    monkeypatch.setattr(sources, "search_all", fake_search)
    r = client.post("/api/media/search", json={"title": "Horror Express", "year": 1972, "providers": ["archive_org"]})
    assert r.status_code == 200
    assert r.json()["items"][0] == {
        "provider": "archive_org", "external_id": "HorrorExpress1972", "title": "Horror Express", "year": 1972,
        "rights": "public_domain", "license_url": None, "height": 720, "duration_ms": 5_265_024, "partial": False,
        "master_file": "HE.mkv", "proxy_file": "HE_512kb.mp4", "usable": True, "via": None}
    assert r.json()["warnings"] == ["local: MOVIES_DIR no disponible"]
    assert seen == {"title": "Horror Express", "year": 1972, "providers": ["archive_org"], "only_usable": True}
    assert client.post("/api/media/search", json={"title": "x", "providers": ["torrent"]}).status_code == 422
    assert client.post("/api/media/search", json={}).status_code == 422

    def down(*a, **k):
        raise ConnectionError("archive.org down")

    monkeypatch.setattr(sources, "search_all", down)
    assert client.post("/api/media/search", json={"title": "x"}).status_code == 502


@pytest.mark.integration
def test_media_ingest_registers_usable_and_refuses_restricted(client, monkeypatch):
    import apps.media.sources as sources
    items = {"good": MediaCandidate(provider="archive_org", external_id="good", title="Good Film", year=1960,
                                    master_uri="https://ia/good.mkv", rights="public_domain"),
             "nc": MediaCandidate(provider="archive_org", external_id="nc", title="NC Film", year=1990,
                                  master_uri="https://ia/nc.mkv", rights="restricted")}

    class Prov:
        def get_item(self, identifier):
            return items.get(identifier)

    monkeypatch.setattr(sources, "get_provider", lambda name, **kw: Prov())
    r = client.post("/api/media/ingest", json={"provider": "archive_org", "external_id": "good", "title": "Good"})
    assert r.status_code == 200
    asset = r.json()
    assert asset["work_title"] == "Good" and asset["rights"] == "public_domain" and asset["moments"] == 0
    assert client.post("/api/media/ingest", json={"provider": "archive_org", "external_id": "nc"}).status_code == 409
    assert client.post("/api/media/ingest", json={"provider": "archive_org", "external_id": "zz"}).status_code == 404


@pytest.mark.integration
def test_vocab_shape(client):
    v = client.get("/api/vocab").json()
    assert set(v) == {"trope", "beat", "emotion", "role", "theme"}
    fear = next(e for e in v["emotion"] if e["id"] == "fear")
    assert fear == {"id": "fear", "es": "Miedo", "en": "Fear", "desc_es": None, "desc_en": None}


@pytest.mark.integration
def test_moments_list_filters_and_pagination(client, world, db):
    page = client.get("/api/moments?per_page=2").json()
    assert (page["page"], page["per_page"], page["total"]) == (1, 2, 4) and len(page["items"]) == 2
    assert page["items"][0]["importance"] >= page["items"][1]["importance"]
    m = page["items"][0]
    assert set(m) >= {"id", "asset_id", "work_id", "work_title", "work_year", "start_ms", "end_ms", "text",
                      "summary_es", "importance", "signal_score", "position", "status", "why", "anchors", "labels",
                      "preview_url"}
    assert list(m["why"]) == ["quote_anchor", "loudness"]                       # >0 y de mayor a menor
    assert m["anchors"] == {"quote": "They're coming for you"} and m["labels"][0]["source"] == "llm:test"
    assert client.get("/api/moments?page=2&per_page=2").json()["items"][0]["id"] not in {i["id"] for i in page["items"]}
    assert client.get("/api/moments?dimension=emotion&value=fear&min_conf=0.95").json()["total"] == 0
    assert client.get("/api/moments?dimension=emotion&value=fear").json()["total"] == 4
    assert client.get("/api/moments?q=Carnival").json()["total"] == 1
    assert client.get("/api/moments?q=100%25").json()["total"] == 0
    aid = world["assets"]["Horror Express"]
    assert client.get(f"/api/moments?asset_id={aid}").json()["total"] == 1
    assert client.get("/api/moments?per_page=500").status_code == 422
    assert client.get("/api/moments?dimension=genre").status_code == 422
    assert client.get("/api/moments?status=weird").status_code == 422


@pytest.mark.integration
def test_moments_find_contract(client, world):
    r = client.get("/api/moments/find?spec=emotion:fear&limit=6&min_works=3&per_work=1&min_confidence=0.5")
    body = r.json()
    assert r.status_code == 200 and body["dimension"] == "emotion" and body["value"] == "fear"
    assert body["distinct_works"] == 3 and "warning" not in body
    assert "Restricted Film" not in [i["work_title"] for i in body["items"]]
    assert {"score", "confidence", "preview_url", "labels"} <= set(body["items"][0])
    assert "warning" in client.get("/api/moments/find?spec=emotion:fear&min_works=5").json()
    assert client.get("/api/moments/find?spec=emotion:nope").status_code == 422
    assert client.get("/api/moments/find").status_code == 422


@pytest.mark.integration
def test_patch_moment_reject_and_manual_labels(client, world, db):
    mid = world["moments"]["Horror Express"]
    assert client.get("/api/moments/99999").status_code == 404
    r = client.patch(f"/api/moments/{mid}", json={"status": "rejected",
                                                  "add_labels": [{"dimension": "trope", "value": "mentor_betrayal"}],
                                                  "remove_labels": [{"dimension": "emotion", "value": "fear"}]})
    assert r.status_code == 200
    m = r.json()
    assert m["status"] == "rejected"
    assert m["labels"] == [{"dimension": "trope", "value": "mentor_betrayal", "confidence": 1.0, "source": "manual"}]
    # restaurar un momento con etiqueta manual lo deja 'labeled': como 'candidate' la próxima
    # detección lo borraría junto con sus etiquetas
    assert client.patch(f"/api/moments/{mid}", json={"status": "candidate"}).json()["status"] == "labeled"
    assert client.patch(f"/api/moments/{mid}", json={"status": "labeled"}).status_code == 422
    bad = client.patch(f"/api/moments/{mid}", json={"add_labels": [{"dimension": "trope", "value": "made_up"}]})
    assert bad.status_code == 422
    assert client.patch("/api/moments/99999", json={"status": "rejected"}).status_code == 404
    assert moments_by_ids(db, [mid])[0]["status"] == "labeled"


@pytest.mark.integration
def test_restore_and_manual_labels_protect_moments_from_redetection(client, world, db):
    mid = world["moments"]["Horror Express"]
    db.execute("UPDATE moments SET status = 'candidate', labeled_by = NULL WHERE id = ?", (mid,))
    db.execute("DELETE FROM moment_labels WHERE moment_id = ? AND source = 'manual'", (mid,))
    db.commit()
    client.patch(f"/api/moments/{mid}", json={"status": "rejected"})
    assert client.patch(f"/api/moments/{mid}", json={"status": "candidate"}).json()["status"] == "candidate"
    r = client.patch(f"/api/moments/{mid}", json={"add_labels": [{"dimension": "emotion", "value": "dread"}]})
    assert r.json()["status"] == "labeled"                       # etiquetar a mano lo protege
    db.execute("UPDATE moments SET status = 'rejected' WHERE id = ?", (mid,))
    db.execute("UPDATE moments SET labeled_by = 'llm:groq' WHERE id = ?", (mid,))
    db.execute("DELETE FROM moment_labels WHERE moment_id = ? AND source = 'manual'", (mid,))
    db.commit()
    assert client.patch(f"/api/moments/{mid}", json={"status": "candidate"}).json()["status"] == "labeled"


@pytest.mark.integration
def test_moment_preview_endpoint(client, world, monkeypatch, tmp_path):
    import apps.supercut.preview as preview
    clip = tmp_path / "p.mp4"
    clip.write_bytes(b"\x00" * 300)
    monkeypatch.setattr(preview, "moment_preview", lambda conn, mid: clip)
    r = client.get(f"/api/moments/{world['moments']['Horror Express']}/preview", headers={"Range": "bytes=0-9"})
    assert r.status_code == 206 and r.headers["content-type"] == "video/mp4" and len(r.content) == 10

    def missing(conn, mid):
        raise preview.MomentNotFound("no")

    monkeypatch.setattr(preview, "moment_preview", missing)
    assert client.get("/api/moments/5/preview").status_code == 404


@pytest.mark.integration
def test_media_providers_reports_config_without_secrets(client, monkeypatch, tmp_path):
    monkeypatch.setenv("MOVIES_DIR", str(tmp_path))
    monkeypatch.delenv("STREMIO_ADDON_URL", raising=False)
    items = {p["name"]: p for p in client.get("/api/media/providers").json()["items"]}
    assert [*items] == ["local", "archive_org", "stremio"]
    assert items["local"]["available"] and items["archive_org"]["available"]
    assert not items["stremio"]["available"] and "STREMIO_ADDON_URL" in items["stremio"]["detail"]

    monkeypatch.setenv("STREMIO_ADDON_URL", "https://addon.example/cfg-SECRET123/manifest.json")
    monkeypatch.setenv("MOVIES_DIR", str(tmp_path / "unplugged"))
    r = client.get("/api/media/providers")
    items = {p["name"]: p for p in r.json()["items"]}
    assert items["stremio"] == {"name": "stremio", "available": True, "detail": "addon.example"}
    assert not items["local"]["available"] and "SECRET123" not in r.text


@pytest.mark.integration
def test_media_ingest_from_stremio_addon(client, monkeypatch):
    import apps.media.sources as sources
    own = MediaCandidate(provider="stremio", external_id="movie/ylk:mine", title="ylk:mine",
                         master_uri="http://127.0.0.1:7010/media/mine.mkv", rights="owned")

    class Prov:
        def get_item(self, external_id):
            return own if external_id == "movie/ylk:mine" else None

    monkeypatch.setattr(sources, "get_provider", lambda name, **kw: Prov())
    r = client.post("/api/media/ingest", json={"provider": "stremio", "external_id": "movie/ylk:mine",
                                               "title": "Mi Película", "year": 1975})
    assert r.status_code == 200 and r.json()["provider"] == "stremio"
    assert r.json()["work_title"] == "Mi Película"

    def down(name, **kw):
        from apps.media.stremio_addon import StremioAddonError
        raise StremioAddonError("STREMIO_ADDON_URL vacío")

    monkeypatch.setattr(sources, "get_provider", down)
    r = client.post("/api/media/ingest", json={"provider": "stremio", "external_id": "movie/ylk:mine"})
    assert r.status_code == 409 and "STREMIO_ADDON_URL" in r.json()["detail"]
