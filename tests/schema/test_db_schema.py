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
