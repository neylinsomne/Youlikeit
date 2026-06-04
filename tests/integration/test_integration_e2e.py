"""End-to-end del flujo de información completo.

Esto es **lo más cercano a "ver que funcione todo"**: parte de cero, ingiere
señales sintéticas, destila, resuelve briefs, el rotator hace pick, los briefs
quedan consumidos, validation pasa.

Si este test pasa, la arquitectura del flujo de información está sana de punta
a punta. Si falla, el output dice exactamente qué eslabón se rompió.
"""

from __future__ import annotations

import pytest


@pytest.mark.e2e
@pytest.mark.integration
class TestFullInfoFlow:

    def test_full_pipeline_synthetic(self, conn, sample_signals, monkeypatch):
        """Smoke E2E sin red, sin LLM, sin video — solo el data flow."""

        # ─ Bajar thresholds para que el fixture pequeño pase validación ─
        monkeypatch.setenv("MIN_SIGNALS_24H", "1")
        monkeypatch.setenv("MIN_SIGNALS_7D", "1")
        monkeypatch.setenv("MIN_BRIEFS_PER_PERSONA", "1")
        from importlib import reload
        from apps.signals import signals_validation
        reload(signals_validation)

        # ─ FASE 1: ingesta sintética ─
        from apps.signals.market_signals import _persist_many
        n_inserted = _persist_many(conn, sample_signals)
        assert n_inserted == len(sample_signals), "todos los samples deben insertarse"

        # ─ FASE 2: destilar (sin LLM) ─
        from apps.signals.signals_distiller import distill, fetch_briefs_for_persona
        n_briefs = distill(conn, settings=None, use_llm=False,
                            window_days=30, top_per_persona=8)
        assert n_briefs > 0, "el distiller no produjo ningún brief"

        # Cada persona debe tener al menos 1 brief
        per_persona = {
            p: fetch_briefs_for_persona(conn, p, limit=10)
            for p in ["deep_mind", "pop_oracle", "latam"]
        }
        for p, briefs in per_persona.items():
            assert len(briefs) >= 1, f"persona {p} quedó sin briefs"

        # ─ FASE 3: resolver briefs y barrer unresolved ─
        from apps.signals.brief_resolver import sweep_unresolved, list_unresolved
        from apps.production.content_rotator import CATALOG
        sweep_report = sweep_unresolved(conn, CATALOG)
        assert isinstance(sweep_report, dict)
        # El fixture incluye 'Dandadan' que no está en CATALOG → unresolved
        unresolved = list_unresolved(conn)
        headlines = [r["headline"].lower() for r in unresolved]
        assert any("dandadan" in h for h in headlines), (
            f"esperaba 'Dandadan' en unresolved. Got: {headlines}"
        )

        # ─ FASE 4: rotator hace pick por persona ─
        from apps.production.content_rotator import ContentRotator
        # ContentRotator necesita ruta a DB; usamos el conn ya existente.
        # Workaround: monkey-patch su __init__ para reusar nuestro conn.
        r = ContentRotator.__new__(ContentRotator)
        r.conn = conn
        from apps.production.content_rotator import init_rotation_db
        init_rotation_db(r.conn)

        picks = []
        for p in ["deep_mind", "pop_oracle", "latam"]:
            pick = r.pick_next(p, consume_briefs=True)
            assert pick is not None, f"rotator no pudo elegir para {p}"
            picks.append(pick)

        # Series elegidas diferentes (diversidad cross-persona)
        slugs = [p["slug"] for p in picks]
        assert len(set(slugs)) >= 2, f"poco diverso: {slugs}"

        # ─ FASE 5: invariantes pasan ─
        rep = signals_validation.run_all_checks(conn)
        if not rep.passes_hard():
            failures = "\n".join(
                f"  ✗ {c.name}: actual={c.actual}, expected={c.expected}, notes={c.notes}"
                for c in rep.hard_failures()
            )
            pytest.fail(f"Validación HARD falló al final del E2E:\n{failures}")


@pytest.mark.e2e
class TestRotatorBriefAwareness:

    def test_rotator_prefers_slug_with_brief(self, conn, sample_signals):
        """Slug con brief debe scorear mejor que slug sin brief (todo lo demás igual)."""
        from apps.signals.market_signals import _persist_many
        from apps.signals.signals_distiller import distill
        from apps.production.content_rotator import ContentRotator, init_rotation_db

        _persist_many(conn, sample_signals)
        distill(conn, settings=None, use_llm=False, window_days=30, top_per_persona=8)

        r = ContentRotator.__new__(ContentRotator)
        r.conn = conn
        init_rotation_db(r.conn)

        # 'frieren' está fuertemente representado en los samples para pop_oracle
        score_frieren = r.score_candidate("pop_oracle", "frieren")
        # 'stardew_valley' no aparece en los samples → boost = 0
        score_stardew = r.score_candidate("pop_oracle", "stardew_valley")
        assert score_frieren > score_stardew, (
            f"Frieren ({score_frieren:.2f}) debería ganar a Stardew ({score_stardew:.2f}) "
            "porque tiene briefs vivos"
        )
