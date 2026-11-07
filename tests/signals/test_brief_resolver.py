"""Tests de la capa puente texto-libre → CATALOG slug."""

from __future__ import annotations

import pytest


# ── Unit: normalización ───────────────────────────────────────────


@pytest.mark.unit
class TestNormalize:
    def test_norm_lowercase(self):
        from apps.signals.brief_resolver import _norm
        assert _norm("HOLA Mundo") == "hola mundo"

    def test_norm_strips_punct(self):
        from apps.signals.brief_resolver import _norm
        assert _norm("Frieren: Beyond Journey's End!") == "frieren beyond journey s end"

    def test_norm_collapses_ws(self):
        from apps.signals.brief_resolver import _norm
        assert _norm("  hola   \t  mundo \n") == "hola mundo"

    def test_norm_empty(self):
        from apps.signals.brief_resolver import _norm
        assert _norm("") == ""
        assert _norm(None) == ""

    def test_norm_idempotent(self):
        from apps.signals.brief_resolver import _norm
        once = _norm("Berserk: Golden Age!")
        twice = _norm(once)
        assert once == twice


# ── Unit: validate_alias_map / alias_map_stats ────────────────────


@pytest.mark.unit
class TestAliasMapIntegrity:
    def test_no_orphans_in_real_alias_map(self):
        """Invariante crítico: ningún alias apunta fuera del CATALOG real.

        Este test fallaría inmediatamente si alguien renombra un slug y
        olvida actualizar el alias map.
        """
        from apps.signals.brief_resolver import validate_alias_map
        from apps.production.content_rotator import CATALOG
        errors = validate_alias_map(CATALOG)
        assert not errors, (
            "ALIAS_MAP tiene aliases huérfanos:\n  - " + "\n  - ".join(errors)
        )

    def test_catalog_coverage_threshold(self):
        """Al menos 80% de los slugs del CATALOG tienen ≥1 alias."""
        from apps.signals.brief_resolver import alias_map_stats
        from apps.production.content_rotator import CATALOG
        stats = alias_map_stats(CATALOG)
        assert stats["coverage_pct"] >= 80.0, (
            f"Cobertura {stats['coverage_pct']}% < 80%. "
            f"Slugs sin alias: {stats['uncovered_slugs']}"
        )

    def test_validate_detects_orphan(self):
        """validate_alias_map debe reportar aliases con slug inexistente."""
        from apps.signals.brief_resolver import validate_alias_map
        fake_catalog = {"berserk": {}}
        # Pasar un catálogo sin la mayoría de slugs → errores garantizados
        errors = validate_alias_map(fake_catalog)
        assert len(errors) > 0


# ── Unit: resolve_brief — capas ───────────────────────────────────


@pytest.fixture
def mini_catalog():
    return {
        "berserk":     {"title": "Berserk: The Golden Age Arc", "primary_personas": ["deep_mind"]},
        "vinland_saga": {"title": "Vinland Saga", "primary_personas": ["deep_mind"]},
        "frieren":     {"title": "Frieren: Beyond Journey's End", "primary_personas": ["pop_oracle"]},
        "elden_ring":  {"title": "Elden Ring", "primary_personas": ["pop_oracle"]},
    }


@pytest.mark.unit
class TestResolveBriefLayers:
    def test_alias_layer_wins(self, mini_catalog):
        """Capa 1 (alias map) tiene precedencia sobre capa 2 (fuzzy)."""
        from apps.signals.brief_resolver import resolve_brief
        brief = {"headline": "Guts vs Griffith — the eclipse"}
        slug, layer = resolve_brief(brief, mini_catalog)
        assert slug == "berserk"
        assert layer == "alias"

    def test_alias_layer_protagonist_match(self, mini_catalog):
        """Aliases por personaje matchean correctamente."""
        from apps.signals.brief_resolver import resolve_brief
        slug, layer = resolve_brief(
            {"headline": "Thorfinn finally finds peace in season 3"},
            mini_catalog,
        )
        assert slug == "vinland_saga"
        assert layer == "alias"

    def test_fuzzy_layer_when_no_alias(self, mini_catalog):
        """Cuando no hay alias, capa 2 fuzzy debe matchear título completo."""
        from apps.signals.brief_resolver import resolve_brief
        # "Vinland Saga season 3" no está en alias pero es alto fuzzy con el title
        slug, layer = resolve_brief(
            {"headline": "Vinland Saga season 3 finally confirmed"},
            mini_catalog,
        )
        # Capa 1 puede pegarle por alias "vinland saga"; ambas opciones son OK.
        # Lo crítico: debe resolver, no quedar unresolved.
        assert slug == "vinland_saga"
        assert layer in ("alias", "fuzzy")

    def test_unresolved_when_no_match(self, mini_catalog):
        """Briefs sin ningún match deben retornar unresolved."""
        from apps.signals.brief_resolver import resolve_brief
        slug, layer = resolve_brief(
            {"headline": "Random news about a show nobody knows"},
            mini_catalog,
        )
        assert slug is None
        assert layer == "unresolved"

    def test_empty_brief_returns_empty(self, mini_catalog):
        """headline vacío → ('empty')."""
        from apps.signals.brief_resolver import resolve_brief
        slug, layer = resolve_brief({"headline": ""}, mini_catalog)
        assert slug is None
        assert layer == "empty"

    def test_uses_cluster_key_if_no_headline(self, mini_catalog):
        """Fallback a cluster_key si no hay headline."""
        from apps.signals.brief_resolver import resolve_brief
        slug, _ = resolve_brief(
            {"headline": "", "cluster_key": "frieren beats record"},
            mini_catalog,
        )
        assert slug == "frieren"

    @pytest.mark.parametrize("headline,expected_slug", [
        ("Sukuna defeats Gojo in the latest chapter", "jujutsu_kaisen"),
        ("Eren Yeager turns into the founding titan", "attack_on_titan"),
        ("Walter White's cancer return rumored",       "breaking_bad"),
        ("Aurelio Casillas regresa a la pantalla",     "el_senor_de_los_cielos"),
        ("Malenia, Blade of Miquella tier list",        "elden_ring"),
        ("Pyramid Head redesign in SH2 remake",         "silent_hill_2"),
        ("Hornet returns in Silksong gameplay",         "hollow_knight_silksong"),
    ])
    def test_real_world_brief_resolution(self, headline, expected_slug):
        """Smoke contra el CATALOG real con briefs verosímiles."""
        from apps.signals.brief_resolver import resolve_brief
        from apps.production.content_rotator import CATALOG
        slug, layer = resolve_brief({"headline": headline}, CATALOG)
        assert slug == expected_slug, f"layer={layer}, got {slug}"


# ── Integration: boost + consumición ──────────────────────────────


@pytest.mark.integration
class TestBoostIntegration:
    def test_boost_zero_without_briefs(self, conn):
        """Sin briefs en DB → boost = 0."""
        from apps.signals.brief_resolver import suggest_boost_for_slug
        from apps.production.content_rotator import CATALOG
        boost, ids = suggest_boost_for_slug(conn, "frieren", "pop_oracle", CATALOG)
        assert boost == 0.0
        assert ids == []

    def test_boost_positive_when_brief_resolves(self, seeded_briefs_db):
        """Si hay un brief que resuelve a 'frieren', boost > 0."""
        from apps.signals.brief_resolver import suggest_boost_for_slug
        from apps.production.content_rotator import CATALOG
        boost, ids = suggest_boost_for_slug(
            seeded_briefs_db, "frieren", "pop_oracle", CATALOG,
        )
        assert boost > 0.0
        assert len(ids) >= 1

    def test_boost_saturates_at_one(self, seeded_briefs_db):
        """Boost ∈ [0, 1] aún con muchos briefs encadenados."""
        from apps.signals.brief_resolver import suggest_boost_for_slug
        from apps.production.content_rotator import CATALOG
        boost, _ = suggest_boost_for_slug(
            seeded_briefs_db, "frieren", "pop_oracle", CATALOG,
            max_briefs=20, decay_per_brief=1.0,
        )
        assert 0.0 <= boost <= 1.0


# ── Integration: unresolved queue ─────────────────────────────────


@pytest.mark.integration
class TestUnresolvedQueue:
    def test_enqueue_idempotent(self, conn):
        """Encolar el mismo brief 2 veces no duplica."""
        from apps.signals.brief_resolver import enqueue_unresolved, list_unresolved
        brief = {"id": 1, "headline": "Dandadan goes viral",
                 "domain": "anime_manga", "score": 3.5,
                 "suggested_angle": "rev"}
        assert enqueue_unresolved(conn, brief, "pop_oracle")
        enqueue_unresolved(conn, brief, "pop_oracle")  # 2da vez = no-op
        rows = list_unresolved(conn, only_unreviewed=True)
        assert len(rows) == 1

    def test_mark_decision_filters(self, conn):
        """Tras marcar reviewed, list_unresolved(only_unreviewed=True) lo excluye."""
        from apps.signals.brief_resolver import (
            enqueue_unresolved, list_unresolved, mark_unresolved_decision,
        )
        brief = {"id": 42, "headline": "Test show", "domain": "movies_tv",
                 "score": 5.0, "suggested_angle": None}
        enqueue_unresolved(conn, brief, "deep_mind")
        rows = list_unresolved(conn)
        qid = rows[0]["id"]
        mark_unresolved_decision(conn, qid, decision="discarded", notes="not for us")
        assert list_unresolved(conn, only_unreviewed=True) == []
        assert len(list_unresolved(conn, only_unreviewed=False)) == 1

    def test_sweep_finds_unmatched(self, seeded_briefs_db):
        """sweep_unresolved encola briefs que no matchean al CATALOG."""
        from apps.signals.brief_resolver import sweep_unresolved, list_unresolved
        from apps.production.content_rotator import CATALOG
        report = sweep_unresolved(seeded_briefs_db, CATALOG)
        assert isinstance(report, dict)
        # El fixture incluye un cluster "Dandadan" que no está en CATALOG.
        rows = list_unresolved(seeded_briefs_db)
        headlines = [r["headline"].lower() for r in rows]
        assert any("dandadan" in h for h in headlines), (
            f"Esperaba ver 'dandadan' en unresolved. Got: {headlines}"
        )

    def test_mark_invalid_decision_rejected(self, conn):
        """mark_unresolved_decision rechaza valores fuera del enum."""
        from apps.signals.brief_resolver import mark_unresolved_decision
        with pytest.raises(AssertionError):
            mark_unresolved_decision(conn, 1, decision="bogus")
