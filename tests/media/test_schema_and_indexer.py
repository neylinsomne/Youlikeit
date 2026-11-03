from __future__ import annotations

from pathlib import Path

import pytest

from apps.media import indexer, schema
from apps.media.models import RIGHTS_PUBLIC_DOMAIN, MediaCandidate


def _cand(**kw) -> MediaCandidate:
    base = dict(provider="archive_org", external_id="notld", title="Night of the Living Dead",
                year=1968, master_uri="https://ia/x/master.mkv", proxy_uri="https://ia/x/proxy.mp4",
                rights=RIGHTS_PUBLIC_DOMAIN)
    base.update(kw)
    return MediaCandidate(**base)


@pytest.mark.unit
def test_ensure_schema_is_idempotent(media_conn):
    schema.ensure_schema(media_conn)
    schema.ensure_schema(media_conn)
    tables = {r[0] for r in media_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"works", "media_assets", "shots", "transcript_segments", "transcript_words"} <= tables


@pytest.mark.unit
def test_registered_in_central_db_schema_ensurers():
    from core.db import _DOMAIN_SCHEMA_ENSURERS
    assert ("apps.media.schema", "ensure_schema") in _DOMAIN_SCHEMA_ENSURERS


@pytest.mark.unit
def test_upsert_work_without_year_does_not_duplicate(media_conn):
    a = schema.upsert_work(media_conn, title="Carnival of Souls", year=None)
    b = schema.upsert_work(media_conn, title="carnival of souls ", year=None)
    assert a == b
    assert media_conn.execute("SELECT COUNT(*) FROM works").fetchone()[0] == 1


@pytest.mark.unit
def test_register_candidate_is_idempotent(media_conn):
    a1 = indexer.register_candidate(media_conn, _cand())
    a2 = indexer.register_candidate(media_conn, _cand(height=1080))
    assert a1 == a2
    row = schema.get_asset(media_conn, a1)
    assert row["work_title"] == "Night of the Living Dead" and row["height"] == 1080
    assert row["rights"] == RIGHTS_PUBLIC_DOMAIN


@pytest.mark.unit
def test_update_asset_rejects_unknown_fields(media_conn):
    aid = indexer.register_candidate(media_conn, _cand())
    with pytest.raises(ValueError):
        schema.update_asset(media_conn, aid, master_uri="hack")


def _fake_media(monkeypatch, tmp_path, calls):
    proxy = tmp_path / "proxy.mp4"
    proxy.write_bytes(b"p")
    monkeypatch.setattr(indexer.ff, "probe", lambda uri: {})
    monkeypatch.setattr(indexer.ff, "summarize_probe", lambda info: {
        "duration_ms": 10_000, "start_ms": 0, "size_bytes": 123, "width": 1440, "height": 1080,
        "fps": 23.976, "vcodec": "h264", "has_audio": True})
    monkeypatch.setattr(indexer, "check_accept_ranges", lambda uri: True)
    monkeypatch.setattr(indexer, "_has_scenedetect", lambda: False)      # → una sola pasada
    monkeypatch.setattr(indexer.analysis, "ensure_local_proxy", lambda *a, **k: proxy)

    def fake_single_pass(src, wav, **kw):
        calls["analyze"] += 1
        Path(wav).parent.mkdir(parents=True, exist_ok=True)
        Path(wav).write_bytes(b"wav")
        return Path(wav), [4000]

    def fake_asr(audio, **kw):
        calls["asr"] += 1
        assert kw["duration_ms"] == 10_000
        return [{"start_ms": 0, "end_ms": 900, "text": "hola", "lang": "es",
                 "words": [{"start_ms": 0, "end_ms": 900, "word": "hola", "prob": 0.9}]}], "es"

    monkeypatch.setattr(indexer.analysis, "single_pass", fake_single_pass)
    monkeypatch.setattr(indexer.transcribe, "resolve_backend", lambda b=None: b or "local")
    monkeypatch.setattr(indexer.transcribe, "transcribe", fake_asr)


@pytest.mark.integration
def test_index_asset_runs_steps_once_then_skips(media_conn, tmp_path, monkeypatch):
    calls = {"analyze": 0, "asr": 0}
    _fake_media(monkeypatch, tmp_path, calls)
    aid = indexer.register_candidate(media_conn, _cand())

    rep = indexer.index_asset(media_conn, aid, work_dir=tmp_path)
    assert rep["asr"] == {"segments": 1, "words": 1, "lang": "es", "backend": "local"}
    assert rep["analyze"] == {"shots": 2, "shot_backend": "scdet", "single_pass": True}
    assert rep["probe"]["accept_ranges"] is True
    assert set(rep["seconds"]) == {"probe", "proxy", "analyze", "asr"}

    indexer.index_asset(media_conn, aid, work_dir=tmp_path)      # segunda vez: no repite
    assert calls == {"analyze": 1, "asr": 1}
    steps = [r["step"] for r in media_conn.execute("SELECT step FROM media_index_runs WHERE status='ok'")]
    assert steps == ["probe", "proxy", "analyze", "asr"]


@pytest.mark.integration
def test_stage_errors_are_logged_and_raised(media_conn, tmp_path, monkeypatch):
    aid = indexer.register_candidate(media_conn, _cand())
    monkeypatch.setattr(indexer.ff, "probe", lambda uri: (_ for _ in ()).throw(RuntimeError("404")))
    with pytest.raises(RuntimeError):
        indexer.prepare_asset(media_conn, aid, work_dir=tmp_path)
    row = media_conn.execute("SELECT step, status, detail_json FROM media_index_runs").fetchone()
    assert (row["step"], row["status"]) == ("probe", "error") and "404" in row["detail_json"]


@pytest.mark.integration
def test_index_many_pipelines_and_isolates_failures(tmp_path, monkeypatch):
    import sqlite3
    db = tmp_path / "media.db"

    def factory():
        c = sqlite3.connect(db, timeout=10)
        c.row_factory = sqlite3.Row
        schema.ensure_schema(c)
        return c

    calls = {"analyze": 0, "asr": 0}
    _fake_media(monkeypatch, tmp_path, calls)
    conn = factory()
    ok1 = indexer.register_candidate(conn, _cand(external_id="a", master_uri="https://ia/a.mkv"))
    bad = indexer.register_candidate(conn, _cand(external_id="b", master_uri="https://ia/b.mkv"))
    ok2 = indexer.register_candidate(conn, _cand(external_id="c", master_uri="https://ia/c.mkv"))
    conn.close()

    real_prepare = indexer.prepare_asset

    def flaky_prepare(c, aid, **kw):
        if aid == bad:
            raise OSError("descarga cortada")
        return real_prepare(c, aid, **kw)

    monkeypatch.setattr(indexer, "prepare_asset", flaky_prepare)
    reports = indexer.index_many(factory, [ok1, bad, ok2], work_dir=tmp_path)
    assert [r["asset_id"] for r in reports] == [ok1, bad, ok2]
    assert "error" in reports[1] and "descarga cortada" in reports[1]["error"]
    assert reports[0]["asr"]["segments"] == 1 and reports[2]["asr"]["segments"] == 1
    assert calls == {"analyze": 2, "asr": 2}
