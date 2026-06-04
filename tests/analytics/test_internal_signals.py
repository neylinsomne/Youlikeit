"""Tests del bridge Plausible → market_signals (dominio internal)."""

from __future__ import annotations

import pytest


@pytest.mark.integration
class TestPersist:
    def test_persist_pageviews_writes_rows(self, conn, breakdown_pages_payload):
        from apps.analytics.internal_signals import persist_pageviews
        n = persist_pageviews(conn, breakdown_pages_payload["results"],
                              "2026-05-25", "2026-06-01")
        assert n == 3
        total = conn.execute("SELECT COUNT(*) FROM plausible_pageviews").fetchone()[0]
        assert total == 3

    def test_persist_pageviews_idempotent(self, conn, breakdown_pages_payload):
        from apps.analytics.internal_signals import persist_pageviews
        persist_pageviews(conn, breakdown_pages_payload["results"], "2026-05-25", "2026-06-01")
        persist_pageviews(conn, breakdown_pages_payload["results"], "2026-05-25", "2026-06-01")
        total = conn.execute("SELECT COUNT(*) FROM plausible_pageviews").fetchone()[0]
        assert total == 3  # UNIQUE(page, period_start, period_end)

    def test_persist_events_writes_rows(self, conn, breakdown_goals_payload):
        from apps.analytics.internal_signals import persist_events
        n = persist_events(conn, breakdown_goals_payload["results"],
                           "2026-05-25", "2026-06-01")
        assert n == 2
        names = {r[0] for r in conn.execute("SELECT event_name FROM plausible_events")}
        assert names == {"cta_click", "persona_click"}


@pytest.mark.integration
class TestBridge:
    def test_signals_from_plausible_builds_internal_signal(self, conn):
        from apps.analytics.internal_signals import signals_from_plausible
        conn.execute(
            """INSERT INTO plausible_pageviews
                 (page, visitors, pageviews, bounce_rate, visit_duration,
                  period_start, period_end)
               VALUES ('/dashboard.html', 50, 90, 40.0, 80.0, '2026-05-25', '2026-06-01')"""
        )
        conn.commit()
        sigs = signals_from_plausible(conn, "deep_mind")
        assert len(sigs) >= 1
        s = sigs[0]
        assert s.domain == "internal"
        assert s.source == "plausible_internal"
        assert s.source_type == "own_engagement"
        assert s.raw_score == 50.0
        assert s.raw_meta["page"] == "/dashboard.html"

    def test_signals_delta_pct_when_two_periods(self, conn):
        from apps.analytics.internal_signals import signals_from_plausible
        conn.executemany(
            """INSERT INTO plausible_pageviews
                 (page, visitors, pageviews, bounce_rate, visit_duration,
                  period_start, period_end)
               VALUES ('/dashboard.html', ?, 0, 0, 0, ?, ?)""",
            [(100, "2026-05-25", "2026-06-01"),   # latest
             (50,  "2026-05-18", "2026-05-25")],  # previous
        )
        conn.commit()
        sigs = signals_from_plausible(conn, "deep_mind")
        s = next(s for s in sigs if s.raw_meta["page"] == "/dashboard.html")
        assert s.raw_meta["delta_pct"] == 100.0   # 50 → 100 = +100%

    def test_unknown_persona_returns_empty(self, conn):
        from apps.analytics.internal_signals import signals_from_plausible
        assert signals_from_plausible(conn, "nonexistent_persona") == []

    def test_below_min_visitors_skipped(self, conn):
        from apps.analytics.internal_signals import signals_from_plausible
        conn.execute(
            """INSERT INTO plausible_pageviews
                 (page, visitors, pageviews, bounce_rate, visit_duration,
                  period_start, period_end)
               VALUES ('/dashboard.html', 0, 0, 0, 0, '2026-05-25', '2026-06-01')"""
        )
        conn.commit()
        assert signals_from_plausible(conn, "deep_mind", min_visitors=1) == []

    def test_persist_signals_to_market(self, conn):
        from apps.analytics.internal_signals import signals_from_plausible, persist_signals_to_market
        conn.execute(
            """INSERT INTO plausible_pageviews
                 (page, visitors, pageviews, bounce_rate, visit_duration,
                  period_start, period_end)
               VALUES ('/', 77, 100, 30.0, 90.0, '2026-05-25', '2026-06-01')"""
        )
        conn.commit()
        sigs = signals_from_plausible(conn, "pop_oracle")
        n = persist_signals_to_market(conn, sigs)
        assert n >= 1
        row = conn.execute(
            "SELECT domain, source FROM market_signals WHERE source = 'plausible_internal'"
        ).fetchone()
        assert row["domain"] == "internal"
