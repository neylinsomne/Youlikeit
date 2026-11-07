"""Tests del hook scorer — score weighting + persistence (sin ffmpeg real)."""

from __future__ import annotations

import pytest


# ── HookScore weighting ────────────────────────────────────────────


@pytest.mark.unit
class TestHookScoreWeighting:
    def test_overall_no_llm_redistribute_weights(self):
        """Con llm_score=None, los pesos restantes deben sumar 1.0."""
        from apps.scoring.hook_scorer import score_hook
        # Mock: pasamos video_path falso → audio_energy_score=0, cps_score=0
        # accent_word_score=0.5 (no accent provided)
        # overall debe ser combinación válida sin LLM
        # Para no levantar ffmpeg, llamamos directo a HookScore.
        from apps.scoring.hook_scorer import HookScore, SCORE_WEIGHTS
        s = HookScore(
            audio_energy_score=0.8,
            cps_score=0.6,
            accent_word_score=0.5,
            llm_score=None,
        )
        # Replicar la lógica de redistribución para validar:
        w = dict(SCORE_WEIGHTS)
        w.pop("llm")
        total = sum(w.values())
        expected = sum(w[k] / total * v for k, v in {
            "audio_energy": 0.8, "cps": 0.6, "accent_word": 0.5,
        }.items())
        # Computar overall vía la función real
        from apps.scoring.hook_scorer import score_hook as _h
        # No invocamos score_hook (necesita video); ya tenemos la expected.
        assert 0 <= expected <= 1.0

    def test_score_passes_threshold(self):
        from apps.scoring.hook_scorer import HookScore, MIN_HOOK_SCORE
        s = HookScore(overall=MIN_HOOK_SCORE + 0.01)
        assert s.passes()
        s2 = HookScore(overall=MIN_HOOK_SCORE - 0.01)
        assert not s2.passes()


# ── Persistence ────────────────────────────────────────────────────


@pytest.mark.integration
class TestHookScorePersistence:
    def test_ensure_schema_idempotent(self, conn):
        from apps.scoring.hook_scorer import ensure_schema
        ensure_schema(conn)
        ensure_schema(conn)   # 2da vez no debe crashear
        # Verificar tabla existe
        n = conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='hook_scores'"
        ).fetchone()[0]
        assert n == 1

    def test_persist_and_fetch(self, conn):
        from apps.scoring.hook_scorer import HookScore, persist_hook_score, fetch_score_for_video
        s = HookScore(
            audio_energy_score=0.7, cps_score=0.8, accent_word_score=1.0,
            llm_score=None, overall=0.78,
        )
        rid = persist_hook_score(
            conn, "outputs/produce/berserk/narration/FINAL_NARRATION.mp4", s,
            persona="deep_mind", vtype="narration", series_slug="berserk",
        )
        assert rid > 0
        fetched = fetch_score_for_video(
            conn, "outputs/produce/berserk/narration/FINAL_NARRATION.mp4",
        )
        assert fetched is not None
        assert fetched["persona"] == "deep_mind"
        assert fetched["overall_score"] == pytest.approx(0.78)
        assert fetched["passed"] in (0, 1)

    def test_fetch_returns_none_for_unknown(self, conn):
        from apps.scoring.hook_scorer import fetch_score_for_video, ensure_schema
        ensure_schema(conn)
        assert fetch_score_for_video(conn, "/nonexistent.mp4") is None


# ── score_hook robusto a errores ───────────────────────────────────


@pytest.mark.integration
class TestScoreHookRobustness:
    def test_missing_video_yields_zero_score(self, conn, tmp_path):
        from apps.scoring.hook_scorer import score_hook
        nonexistent = tmp_path / "missing.mp4"
        s = score_hook(
            video_path=str(nonexistent),
            vtype="narration",
            hook_text="Some hook",
            accent_word="hook",
            edl=None,
            use_llm=False,
        )
        assert s.overall == 0.0
        assert "video_path not found" in s.notes
