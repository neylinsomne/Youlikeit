"""Tests de la capa de Data Verification — invariantes hard/soft."""

from __future__ import annotations

import pytest


# ── ValidationReport semantics ─────────────────────────────────────


@pytest.mark.unit
class TestValidationReport:
    def test_passes_hard_when_all_hard_pass(self):
        from apps.signals.signals_validation import CheckResult, ValidationReport
        r = ValidationReport()
        r.add(CheckResult("a", "hard", True, 1, ">=0"))
        r.add(CheckResult("b", "soft", False, 0, ">=1"))
        assert r.passes_hard() is True
        assert r.passes_all() is False

    def test_passes_hard_fails_on_hard_fail(self):
        from apps.signals.signals_validation import CheckResult, ValidationReport
        r = ValidationReport()
        r.add(CheckResult("a", "hard", False, 0, ">=1"))
        assert r.passes_hard() is False

    def test_summary_renders_marks(self):
        from apps.signals.signals_validation import CheckResult, ValidationReport
        r = ValidationReport()
        r.add(CheckResult("ok_check", "hard", True, 100, ">=10"))
        r.add(CheckResult("fail_soft", "soft", False, 0, ">=1"))
        text = r.summary()
        assert "ok_check" in text
        assert "fail_soft" in text


# ── Invariantes individuales con fixtures ─────────────────────────


@pytest.mark.integration
class TestSignalsVolume:
    def test_volume_24h_passes_with_recent_signals(self, conn, monkeypatch):
        # Threshold bajo para que el fixture seeded pase
        monkeypatch.setenv("MIN_SIGNALS_24H", "1")
        from importlib import reload
        from apps.signals import signals_validation
        reload(signals_validation)

        from apps.signals.market_signals import Signal, _persist_many
        _persist_many(conn, [Signal("s1", "editorial_rss", "gaming", f"Title {i}")
                              for i in range(5)])
        res = signals_validation.check_signals_volume_24h(conn)
        assert res.passed
        assert res.severity == "hard"

    def test_volume_24h_fails_when_empty(self, conn, monkeypatch):
        monkeypatch.setenv("MIN_SIGNALS_24H", "10")
        from importlib import reload
        from apps.signals import signals_validation
        reload(signals_validation)
        res = signals_validation.check_signals_volume_24h(conn)
        assert not res.passed


@pytest.mark.integration
class TestRequiredFields:
    def test_passes_on_clean_data(self, seeded_db):
        from apps.signals.signals_validation import check_signals_have_required_fields
        res = check_signals_have_required_fields(seeded_db)
        assert res.passed

    def test_fails_when_null_title(self, conn):
        """Si insertamos directo en SQL una fila inválida, el check la detecta."""
        from apps.signals.signals_validation import check_signals_have_required_fields
        conn.execute(
            "INSERT INTO market_signals "
            "(source, source_type, domain, title, normalized_title) "
            "VALUES ('s', 'editorial_rss', 'gaming', '', '')"
        )
        conn.commit()
        res = check_signals_have_required_fields(conn)
        assert not res.passed
        assert res.severity == "hard"


@pytest.mark.integration
class TestDomainEnum:
    def test_passes_on_known_domains(self, seeded_db):
        from apps.signals.signals_validation import check_domain_enum
        res = check_domain_enum(seeded_db)
        assert res.passed

    def test_fails_on_unknown_domain(self, conn):
        from apps.signals.signals_validation import check_domain_enum
        conn.execute(
            "INSERT INTO market_signals "
            "(source, source_type, domain, title, normalized_title) "
            "VALUES ('s', 'editorial_rss', 'cooking', 'X', 'x')"
        )
        conn.commit()
        res = check_domain_enum(conn)
        assert not res.passed


@pytest.mark.integration
class TestBriefsPerPersona:
    def test_fails_when_personas_empty(self, conn, monkeypatch):
        monkeypatch.setenv("MIN_BRIEFS_PER_PERSONA", "1")
        from importlib import reload
        from apps.signals import signals_validation
        reload(signals_validation)
        res = signals_validation.check_briefs_per_persona(conn)
        assert not res.passed

    def test_passes_when_personas_have_briefs(self, seeded_briefs_db, monkeypatch):
        monkeypatch.setenv("MIN_BRIEFS_PER_PERSONA", "1")
        from importlib import reload
        from apps.signals import signals_validation
        reload(signals_validation)
        res = signals_validation.check_briefs_per_persona(seeded_briefs_db)
        assert res.passed


@pytest.mark.integration
class TestRunAll:
    def test_run_all_returns_all_checks(self, seeded_briefs_db, monkeypatch):
        # Bajar thresholds para que el fixture pequeño los cumpla
        monkeypatch.setenv("MIN_SIGNALS_24H", "1")
        monkeypatch.setenv("MIN_SIGNALS_7D", "1")
        monkeypatch.setenv("MIN_BRIEFS_PER_PERSONA", "1")
        from importlib import reload
        from apps.signals import signals_validation
        reload(signals_validation)
        rep = signals_validation.run_all_checks(seeded_briefs_db)
        # Mismo número que ALL_CHECKS
        assert len(rep.checks) == len(signals_validation.ALL_CHECKS)

    def test_run_all_serializable(self, seeded_briefs_db):
        import json
        from apps.signals.signals_validation import run_all_checks
        rep = run_all_checks(seeded_briefs_db)
        # to_dict debe ser JSON-serializable sin errores
        json.dumps(rep.to_dict())
