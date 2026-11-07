"""Tests de la vista conjunta — agregación de las 4 capas del embudo."""

from __future__ import annotations

import pytest


@pytest.fixture
def full_stack_db(conn):
    """DB con datos sintéticos en las 4 capas (signals, web, hooks, plataforma)."""
    from apps.signals.market_signals import Signal, _persist_many
    _persist_many(conn, [
        Signal("steam_charts", "gaming_chart", "gaming", "Elden Ring", raw_score=42),
        Signal("reddit_r_anime", "reddit_thread", "anime_manga", "Frieren wins", raw_score=4500),
    ])
    conn.executemany(
        """INSERT INTO persona_briefs (persona, cluster_key, headline, domain, score)
           VALUES (?, ?, ?, ?, ?)""",
        [("deep_mind", "frieren", "Frieren analysis", "anime_manga", 9.1),
         ("pop_oracle", "elden", "Elden hype", "gaming", 7.8)],
    )
    conn.executemany(
        """INSERT INTO plausible_pageviews
             (page, visitors, pageviews, bounce_rate, visit_duration, period_start, period_end)
           VALUES (?, ?, ?, 40.0, 80.0, '2026-05-25', '2026-06-01')""",
        [("/", 100, 180), ("/dashboard.html", 50, 90)],
    )
    conn.executemany(
        """INSERT INTO plausible_events (event_name, page, count, period_start, period_end, raw_props)
           VALUES (?, ?, ?, '2026-05-25', '2026-06-01', ?)""",
        [("cta_click", "/", 30, None),
         ("persona_click", "/persona/deep_mind", 12, '{"persona":"deep_mind"}')],
    )
    conn.executemany(
        """INSERT INTO hook_scores (video_path, persona, overall_score, passed)
           VALUES (?, ?, ?, ?)""",
        [("/v/1.mp4", "deep_mind", 0.72, 1), ("/v/2.mp4", "deep_mind", 0.40, 0)],
    )
    conn.executemany("INSERT INTO shorts (id, title) VALUES (?, ?)", [(1, "a"), (2, "b")])
    conn.executemany(
        """INSERT INTO analytics (short_id, platform, views, engagement_rate, retention_avg)
           VALUES (?, ?, ?, ?, ?)""",
        [(1, "youtube", 5000, 0.06, 38.0), (2, "tiktok", 12000, 0.09, 44.0)],
    )
    conn.commit()
    return conn


@pytest.mark.integration
class TestLayers:
    def test_web_funnel(self, full_stack_db):
        from apps.analytics.unified_analytics import web_funnel
        w = web_funnel(full_stack_db)
        assert w["visitors"] == 150
        assert w["cta_click"] == 30
        assert w["persona_click"] == 12
        assert w["cta_rate_pct"] > 0
        assert w["top_pages"][0]["page"] == "/"

    def test_external_demand(self, full_stack_db):
        from apps.analytics.unified_analytics import external_demand
        ed = external_demand(full_stack_db)
        assert ed["signals_7d"] == 2
        assert ed["briefs_unconsumed"]["deep_mind"] == 1
        assert "gaming" in ed["signals_by_domain"]

    def test_content_quality(self, full_stack_db):
        from apps.analytics.unified_analytics import content_quality
        q = content_quality(full_stack_db)
        assert q["scored"] == 2
        assert q["pass_rate_pct"] == 50.0
        assert q["by_persona"]["deep_mind"]["n"] == 2

    def test_platform_performance(self, full_stack_db):
        from apps.analytics.unified_analytics import platform_performance
        pp = platform_performance(full_stack_db)
        assert pp["by_platform"]["tiktok"]["views"] == 12000
        assert pp["by_platform"]["youtube"]["videos"] == 1
        assert pp["top_shorts"][0]["views"] == 12000


@pytest.mark.integration
class TestRollupAndBuild:
    def test_persona_rollup_crosses_layers(self, full_stack_db):
        from apps.analytics.unified_analytics import persona_rollup
        rows = {r["persona"]: r for r in persona_rollup(full_stack_db)}
        dm = rows["deep_mind"]
        assert dm["web_visitors"] == 50          # /dashboard.html ∈ deep_mind pages
        assert dm["persona_clicks"] == 12
        assert dm["briefs_unconsumed"] == 1
        assert dm["hook_pass_rate_pct"] == 50.0

    def test_build_joint_has_all_layers(self, full_stack_db):
        from apps.analytics.unified_analytics import build
        r = build(full_stack_db, source="joint")
        assert r["source"] == "joint"
        for key in ("external_demand", "web_funnel", "content_quality",
                    "platform_performance", "persona_rollup"):
            assert key in r

    def test_build_plausible_only_is_web_only(self, full_stack_db):
        from apps.analytics.unified_analytics import build
        r = build(full_stack_db, source="plausible")
        assert r["source"] == "plausible"
        assert set(r.keys()) == {"source", "web_funnel"}

    def test_render_joint(self, full_stack_db):
        from apps.analytics.unified_analytics import build, render
        text = render(build(full_stack_db, source="joint"))
        assert "CONJUNTA" in text
        assert "DEMANDA 1ª PARTE" in text
        assert "ROLLUP POR PERSONA" in text

    def test_render_plausible_only(self, full_stack_db):
        from apps.analytics.unified_analytics import build, render
        text = render(build(full_stack_db, source="plausible"))
        assert "solo Plausible" in text
        assert "ROLLUP POR PERSONA" not in text


@pytest.mark.integration
class TestEmptyDb:
    def test_build_on_empty_db_degrades_to_zeros(self, conn):
        from apps.analytics.unified_analytics import build
        r = build(conn, source="joint")
        assert r["web_funnel"]["visitors"] == 0
        assert r["content_quality"]["scored"] == 0
        assert r["platform_performance"]["by_platform"] == {}
        # rollup presente pero en ceros
        assert all(row["web_visitors"] == 0 for row in r["persona_rollup"])
