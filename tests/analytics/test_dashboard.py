"""Tests del dashboard CLI — paneles + render con datos sintéticos."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

# El dashboard vive en scripts/ (no es un paquete importable); lo cargamos
# por path para testear sus funciones puras.
_DASH_PATH = Path(__file__).resolve().parents[2] / "scripts" / "analytics" / "analytics_dashboard.py"


def _load_dashboard():
    spec = importlib.util.spec_from_file_location("analytics_dashboard", _DASH_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def dash():
    return _load_dashboard()


@pytest.fixture
def seeded_analytics_db(conn):
    """DB con pageviews + events sintéticos en 2 periodos."""
    conn.executemany(
        """INSERT INTO plausible_pageviews
             (page, visitors, pageviews, bounce_rate, visit_duration,
              period_start, period_end)
           VALUES (?, ?, ?, 40.0, 80.0, ?, ?)""",
        [("/", 80, 140, "2026-05-18", "2026-05-25"),
         ("/", 95, 170, "2026-05-25", "2026-06-01"),
         ("/dashboard.html", 33, 60, "2026-05-25", "2026-06-01")],
    )
    conn.executemany(
        """INSERT INTO plausible_events (event_name, page, count, period_start, period_end)
           VALUES (?, ?, ?, '2026-05-25', '2026-06-01')""",
        [("cta_click", "/", 41), ("persona_click", "/", 15)],
    )
    conn.commit()
    return conn


@pytest.mark.unit
class TestSparkline:
    def test_sparkline_basic(self, dash):
        s = dash.sparkline([1, 5, 10])
        assert len(s) == 3
        assert s[0] != s[-1]  # crece

    def test_sparkline_empty(self, dash):
        assert dash.sparkline([]) == ""


@pytest.mark.integration
class TestPanels:
    def test_panel_top_pages(self, dash, seeded_analytics_db):
        rows = dash.panel_top_pages(seeded_analytics_db)
        assert rows[0]["page"] == "/"
        assert rows[0]["visitors"] == 95  # MAX entre los 2 periodos

    def test_panel_custom_events(self, dash, seeded_analytics_db):
        rows = dash.panel_custom_events(seeded_analytics_db)
        names = {r["event_name"] for r in rows}
        assert {"cta_click", "persona_click"} <= names

    def test_panel_funnel_rate(self, dash, seeded_analytics_db):
        f = dash.panel_funnel(seeded_analytics_db)
        assert f["cta_click"] == 41
        assert f["persona_click"] == 15
        assert f["cta_rate_pct"] > 0

    def test_build_and_render(self, dash, seeded_analytics_db):
        data = dash.build(seeded_analytics_db)
        text = dash.render(data)
        assert "ANALYTICS DASHBOARD" in text
        assert "/dashboard.html" in text
