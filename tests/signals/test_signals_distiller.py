"""Tests del distiller: clusters, scoring, distill end-to-end."""

from __future__ import annotations

import pytest


# ── Unit: _build_clusters ──────────────────────────────────────────


@pytest.mark.integration
class TestBuildClusters:
    def test_dedup_capa1_groups_exact(self, seeded_db):
        """Misma normalized_title de N fuentes → 1 cluster con frequency N."""
        from apps.signals.signals_distiller import _build_clusters, _load_recent_signals
        rows = _load_recent_signals(seeded_db, window_days=30)
        clusters = _build_clusters(rows)
        # En el fixture, 'frieren' aparece 2-3 veces con normalized_title compartido
        # (algunos con variaciones — capa 2 los junta, capa 1 no necesariamente)
        # Verificamos que al menos hay agrupación
        assert any(c.raw_frequency > 1 for c in clusters.values())

    def test_each_cluster_has_at_least_one_signal(self, seeded_db):
        from apps.signals.signals_distiller import _build_clusters, _load_recent_signals
        rows = _load_recent_signals(seeded_db, window_days=30)
        clusters = _build_clusters(rows)
        for c in clusters.values():
            assert len(c.signal_ids) >= 1
            assert c.raw_frequency >= 1
            assert len(c.fuentes) >= 1


# ── Unit: _score_cluster ───────────────────────────────────────────


@pytest.mark.unit
class TestScoreCluster:
    def _make_cluster(self, **overrides):
        from apps.signals.signals_distiller import _Cluster
        defaults = dict(
            key="frieren beats own record at mal",
            headline="Frieren beats own record at MAL",
            domain="anime_manga",
            signal_ids=[1, 2, 3],
            fuentes={"ann_features", "reddit_r_anime", "animefeminist"},
            recency_ts=0.0,
            raw_frequency=3,
            sources_text="Frieren beats own record at MAL Sousou no Frieren analysis",
        )
        defaults.update(overrides)
        return _Cluster(**defaults)

    def test_score_positive_for_aligned_persona(self):
        from apps.signals.signals_distiller import _score_cluster
        import time
        now = time.time()
        cluster = self._make_cluster(recency_ts=now - 3600)  # 1h atrás
        score = _score_cluster(cluster, "pop_oracle", now)
        assert score > 0

    def test_score_decays_with_age(self):
        """Cluster antiguo debe scorear menos que cluster reciente."""
        from apps.signals.signals_distiller import _score_cluster
        import time
        now = time.time()
        fresh = self._make_cluster(recency_ts=now - 60)         # 1 min
        stale = self._make_cluster(recency_ts=now - 86400 * 5)  # 5 días
        assert _score_cluster(fresh, "pop_oracle", now) > _score_cluster(stale, "pop_oracle", now)

    def test_score_higher_for_correct_domain(self):
        """Cluster gaming scorea mejor para pop_oracle que para latam."""
        from apps.signals.signals_distiller import _score_cluster
        import time
        now = time.time()
        cluster = self._make_cluster(domain="gaming",
                                      recency_ts=now,
                                      sources_text="Elden Ring tier list trending viral")
        score_pop = _score_cluster(cluster, "pop_oracle", now)
        score_latam = _score_cluster(cluster, "latam", now)
        assert score_pop > score_latam

    def test_score_deterministic(self):
        """Mismas entradas → mismo score (sin aleatoriedad)."""
        from apps.signals.signals_distiller import _score_cluster
        import time
        now = time.time()
        c = self._make_cluster(recency_ts=now - 3600)
        s1 = _score_cluster(c, "deep_mind", now)
        s2 = _score_cluster(c, "deep_mind", now)
        assert s1 == s2


# ── Integration: distill end-to-end ───────────────────────────────


@pytest.mark.integration
class TestDistillE2E:
    def test_distill_produces_briefs(self, seeded_db):
        from apps.signals.signals_distiller import distill
        n = distill(seeded_db, settings=None, use_llm=False,
                    window_days=30, top_per_persona=5)
        assert n > 0

    def test_distill_creates_briefs_per_persona(self, seeded_db):
        from apps.signals.signals_distiller import distill, fetch_briefs_for_persona
        distill(seeded_db, settings=None, use_llm=False,
                window_days=30, top_per_persona=8)
        for persona in ["deep_mind", "pop_oracle", "latam"]:
            briefs = fetch_briefs_for_persona(seeded_db, persona, limit=10)
            assert len(briefs) >= 1, f"persona {persona} sin briefs"

    def test_briefs_score_ordered_desc(self, seeded_briefs_db):
        from apps.signals.signals_distiller import fetch_briefs_for_persona
        for persona in ["deep_mind", "pop_oracle", "latam"]:
            briefs = fetch_briefs_for_persona(seeded_briefs_db, persona, limit=10)
            scores = [b["score"] for b in briefs]
            assert scores == sorted(scores, reverse=True)

    def test_distill_without_llm_yields_no_angle(self, seeded_db):
        from apps.signals.signals_distiller import distill, fetch_briefs_for_persona
        distill(seeded_db, settings=None, use_llm=False, window_days=30)
        briefs = fetch_briefs_for_persona(seeded_db, "pop_oracle", limit=5)
        for b in briefs:
            assert b["suggested_angle"] is None

    def test_mark_brief_consumed(self, seeded_briefs_db):
        """consumed_at se setea → desaparece de fetch_briefs unconsumed."""
        from apps.signals.signals_distiller import (
            fetch_briefs_for_persona, mark_brief_consumed,
        )
        briefs = fetch_briefs_for_persona(seeded_briefs_db, "pop_oracle",
                                           limit=1, only_unconsumed=True)
        assert briefs
        bid = briefs[0]["id"]
        mark_brief_consumed(seeded_briefs_db, bid)
        live = fetch_briefs_for_persona(seeded_briefs_db, "pop_oracle",
                                         limit=20, only_unconsumed=True)
        assert all(b["id"] != bid for b in live)

    def test_distill_idempotent_on_same_day(self, seeded_db):
        """Re-correr distill el mismo día no debe duplicar briefs (UNIQUE)."""
        from apps.signals.signals_distiller import distill, fetch_briefs_for_persona
        distill(seeded_db, settings=None, use_llm=False)
        n_first = sum(
            len(fetch_briefs_for_persona(seeded_db, p, limit=50))
            for p in ["deep_mind", "pop_oracle", "latam"]
        )
        distill(seeded_db, settings=None, use_llm=False)
        n_second = sum(
            len(fetch_briefs_for_persona(seeded_db, p, limit=50))
            for p in ["deep_mind", "pop_oracle", "latam"]
        )
        # Misma cantidad (UNIQUE persona+cluster_key+created_at protege)
        assert n_second == n_first


# ── Unit: fuzzy merge fail-soft ───────────────────────────────────


@pytest.mark.unit
class TestFuzzyMerge:
    def test_no_rapidfuzz_returns_unchanged(self, monkeypatch):
        """Si rapidfuzz no está, _fuzzy_merge no debe crashear."""
        from apps.signals.signals_distiller import _fuzzy_merge_clusters, _Cluster
        # Simular ImportError forzando un import dentro
        import sys
        saved = sys.modules.get("rapidfuzz")
        sys.modules["rapidfuzz"] = None  # type: ignore
        try:
            clusters = {
                "a": _Cluster("a", "A", "gaming", [1], {"x"}, 0.0, 1, "a"),
                "b": _Cluster("b", "B", "gaming", [2], {"y"}, 0.0, 1, "b"),
            }
            merged = _fuzzy_merge_clusters(clusters)
            assert len(merged) == 2
        finally:
            if saved is not None:
                sys.modules["rapidfuzz"] = saved
            else:
                sys.modules.pop("rapidfuzz", None)
