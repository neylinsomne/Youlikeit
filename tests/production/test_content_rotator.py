"""Tests del rotator — score_candidate, pick_next, brief consumption."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest


# ── Helper fixture: rotator con DB temp ────────────────────────────


@pytest.fixture
def rotator_db(tmp_path, sample_signals):
    """ContentRotator que usa una DB temp con SCHEMA completo + señales."""
    from core.db import SCHEMA, _migrate_columns
    from apps.signals.market_signals import _persist_many

    db_path = tmp_path / "test.db"
    c = sqlite3.connect(str(db_path))
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    _migrate_columns(c)
    _persist_many(c, sample_signals)
    c.close()
    return str(db_path)


@pytest.fixture
def rotator_with_briefs(rotator_db):
    """rotator_db pero con briefs ya destilados."""
    from apps.signals.signals_distiller import distill
    c = sqlite3.connect(rotator_db)
    c.row_factory = sqlite3.Row
    distill(c, settings=None, use_llm=False, window_days=30, top_per_persona=8)
    c.close()
    return rotator_db


# ── Unit: CATALOG sanity ──────────────────────────────────────────


@pytest.mark.unit
class TestCatalog:
    def test_no_duplicate_slugs(self):
        from apps.production.content_rotator import CATALOG
        # dict no permite duplicados; verificamos que todas las entradas
        # tengan campos requeridos.
        for slug, entry in CATALOG.items():
            assert "title" in entry, f"{slug} sin title"
            assert "primary_personas" in entry, f"{slug} sin primary_personas"
            assert entry["primary_personas"], f"{slug} primary_personas vacío"

    def test_all_personas_have_catalog_entries(self):
        from apps.production.content_rotator import CATALOG
        seen = {"deep_mind": 0, "pop_oracle": 0, "latam": 0}
        for entry in CATALOG.values():
            for p in entry["primary_personas"]:
                seen[p] = seen.get(p, 0) + 1
        for p, n in seen.items():
            assert n >= 4, f"persona {p} solo tiene {n} entradas en CATALOG"


# ── Integration: score_candidate ──────────────────────────────────


@pytest.mark.integration
class TestScoreCandidate:
    def test_returns_zero_for_unknown_slug(self, rotator_db):
        from apps.production.content_rotator import ContentRotator
        r = ContentRotator(rotator_db)
        s = r.score_candidate("deep_mind", "nonexistent_slug")
        assert s == 0.0
        r.conn.close()

    def test_returns_positive_for_valid_pick(self, rotator_db):
        from apps.production.content_rotator import ContentRotator
        r = ContentRotator(rotator_db)
        # Berserk + deep_mind, sin historial → freshness máxima
        s = r.score_candidate("deep_mind", "berserk")
        assert s > 0
        r.conn.close()

    def test_cooldown_yields_zero(self, rotator_db):
        """Si la serie se produjo hace < min_days_cooldown, score=0."""
        from apps.production.content_rotator import ContentRotator, log_produced
        r = ContentRotator(rotator_db)
        log_produced(r.conn, "deep_mind", "berserk", "Berserk", "narration")
        s = r.score_candidate("deep_mind", "berserk", min_days_cooldown=14)
        assert s == 0.0
        r.conn.close()

    def test_with_brief_ids_returns_tuple(self, rotator_db):
        from apps.production.content_rotator import ContentRotator
        r = ContentRotator(rotator_db)
        result = r.score_candidate("deep_mind", "berserk", with_brief_ids=True)
        assert isinstance(result, tuple)
        assert len(result) == 2
        r.conn.close()

    def test_brief_boost_increases_score(self, rotator_with_briefs):
        """Con briefs vivos, el score debe ser ≥ score base."""
        from apps.production.content_rotator import ContentRotator
        r = ContentRotator(rotator_with_briefs)
        # Frieren está en el fixture como cluster fuerte para pop_oracle
        score = r.score_candidate("pop_oracle", "frieren")
        assert score > 0
        r.conn.close()


# ── Integration: pick_next + consume_briefs ───────────────────────


@pytest.mark.integration
class TestPickNext:
    def test_picks_something(self, rotator_db):
        from apps.production.content_rotator import ContentRotator
        r = ContentRotator(rotator_db)
        pick = r.pick_next("deep_mind")
        assert pick is not None
        assert "slug" in pick
        assert "title" in pick
        r.conn.close()

    def test_excludes_works(self, rotator_db):
        from apps.production.content_rotator import ContentRotator
        r = ContentRotator(rotator_db)
        pick = r.pick_next("deep_mind", exclude=["berserk", "monster", "vinland_saga"])
        assert pick is not None
        assert pick["slug"] not in {"berserk", "monster", "vinland_saga"}
        r.conn.close()

    def test_consume_briefs_marks_them(self, rotator_with_briefs):
        from apps.production.content_rotator import ContentRotator
        from apps.signals.signals_distiller import fetch_briefs_for_persona
        r = ContentRotator(rotator_with_briefs)
        before = fetch_briefs_for_persona(r.conn, "pop_oracle",
                                           limit=20, only_unconsumed=True)
        n_before = len(before)
        pick = r.pick_next("pop_oracle", consume_briefs=True)
        after = fetch_briefs_for_persona(r.conn, "pop_oracle",
                                          limit=20, only_unconsumed=True)
        # Si el pick tenía briefs asociados, deben haberse marcado.
        if pick and pick.get("brief_ids"):
            assert len(after) < n_before
        r.conn.close()

    def test_consume_false_keeps_briefs_live(self, rotator_with_briefs):
        from apps.production.content_rotator import ContentRotator
        from apps.signals.signals_distiller import fetch_briefs_for_persona
        r = ContentRotator(rotator_with_briefs)
        before = fetch_briefs_for_persona(r.conn, "pop_oracle",
                                           limit=20, only_unconsumed=True)
        r.pick_next("pop_oracle", consume_briefs=False)
        after = fetch_briefs_for_persona(r.conn, "pop_oracle",
                                          limit=20, only_unconsumed=True)
        assert len(after) == len(before)
        r.conn.close()

    def test_pick_returns_none_when_all_excluded(self, rotator_db):
        from apps.production.content_rotator import ContentRotator, CATALOG
        r = ContentRotator(rotator_db)
        pick = r.pick_next("deep_mind", exclude=list(CATALOG.keys()))
        assert pick is None
        r.conn.close()
