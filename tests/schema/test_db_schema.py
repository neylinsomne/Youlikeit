"""Regresiones del SCHEMA central (core/db.py)."""
from __future__ import annotations

import pytest


@pytest.mark.unit
def test_cross_references_exists_on_fresh_db(conn):
    """Antes solo la creaba seed_cross_refs.py → culture_feed/ab_testing fallaban en DB fresca."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(cross_references)")}
    assert {"source_work", "target_work", "reference_type", "strength",
            "description_deep_mind", "description_cinephile", "description_pop_oracle"} <= cols


@pytest.mark.unit
def test_cross_references_matches_ab_testing_queries(conn):
    conn.execute(
        "INSERT INTO cross_references (source_work, source_type, target_work, target_type, reference_type)"
        " VALUES ('Berserk', 'manga', 'Dark Souls', 'game', 'thematic')"
    )
    conn.execute("UPDATE cross_references SET strength = MIN(1.0, strength + 0.1) WHERE target_work = ?",
                 ("Dark Souls",))
    (strength,) = conn.execute("SELECT strength FROM cross_references").fetchone()
    assert strength == pytest.approx(0.8)


@pytest.mark.integration
def test_get_db_uses_wal_and_busy_timeout(tmp_path):
    from core.db import get_db
    c = get_db(tmp_path)
    assert c.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert c.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    c.close()


@pytest.mark.unit
def test_websocket_notify_from_thread_keeps_clients():
    """notify() desde un hilo sin loop no debe desconectar clientes (antes los borraba a todos)."""
    import threading

    from utils import websocket_hub as hub

    class FakeWS:
        async def send_text(self, msg):
            pass

    ws = FakeWS()
    hub._ws_clients.add(ws)
    try:
        t = threading.Thread(target=hub.notify, args=("test", "load", {"x": 1}))
        t.start()
        t.join()
        assert ws in hub._ws_clients
        assert hub.get_recent_events(1)[-1]["data"] == {"x": 1}
    finally:
        hub._ws_clients.discard(ws)
