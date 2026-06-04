"""Tests del cliente Stats API — parsing, auth, cache, healthcheck."""

from __future__ import annotations

import pytest

from tests.analytics.conftest import TEST_API_KEY, TEST_BASE_URL


# ── Unit: helpers puros ───────────────────────────────────────────────


@pytest.mark.unit
class TestHelpers:
    def test_csv_from_list(self):
        from apps.analytics.plausible_client import _csv
        assert _csv(["visitors", "pageviews"]) == "visitors,pageviews"

    def test_csv_from_str_passthrough(self):
        from apps.analytics.plausible_client import _csv
        assert _csv("visitors,bounce_rate") == "visitors,bounce_rate"

    def test_params_hash_stable_and_order_independent(self):
        from apps.analytics.plausible_client import _params_hash
        a = _params_hash("aggregate", {"period": "7d", "site_id": "x"})
        b = _params_hash("aggregate", {"site_id": "x", "period": "7d"})
        assert a == b
        c = _params_hash("aggregate", {"period": "30d", "site_id": "x"})
        assert a != c


# ── Integration: fetch_* con HTTP mock ────────────────────────────────


@pytest.mark.integration
class TestFetch:
    def test_fetch_aggregate_parses_results(self, register_stats, aggregate_payload):
        from apps.analytics.plausible_client import fetch_aggregate
        register_stats("aggregate", aggregate_payload)
        out = fetch_aggregate(period="7d", base_url=TEST_BASE_URL, api_key=TEST_API_KEY)
        assert out["results"]["visitors"]["value"] == 142

    def test_fetch_breakdown_pages(self, register_stats, breakdown_pages_payload):
        from apps.analytics.plausible_client import fetch_breakdown
        register_stats("breakdown", breakdown_pages_payload)
        out = fetch_breakdown(property="event:page", period="30d",
                              base_url=TEST_BASE_URL, api_key=TEST_API_KEY)
        pages = [r["page"] for r in out["results"]]
        assert "/dashboard.html" in pages

    def test_fetch_timeseries(self, register_stats, timeseries_payload):
        from apps.analytics.plausible_client import fetch_timeseries
        register_stats("timeseries", timeseries_payload)
        out = fetch_timeseries(period="7d", base_url=TEST_BASE_URL, api_key=TEST_API_KEY)
        assert len(out["results"]) == 3
        assert out["results"][0]["date"] == "2026-05-26"

    def test_auth_header_sent(self, register_stats, aggregate_payload, mocked_http):
        from apps.analytics.plausible_client import fetch_aggregate
        register_stats("aggregate", aggregate_payload)
        fetch_aggregate(period="7d", base_url=TEST_BASE_URL, api_key=TEST_API_KEY)
        sent = mocked_http.calls[0].request.headers.get("Authorization")
        assert sent == f"Bearer {TEST_API_KEY}"

    def test_non_json_response_returns_none(self, mocked_http):
        import responses
        from apps.analytics.plausible_client import fetch_aggregate
        mocked_http.add(responses.GET, f"{TEST_BASE_URL}/api/v1/stats/aggregate",
                        body="<html>oops</html>", status=200,
                        content_type="text/html")
        out = fetch_aggregate(period="7d", base_url=TEST_BASE_URL, api_key=TEST_API_KEY)
        assert out is None


# ── Integration: config + auth errors ─────────────────────────────────


@pytest.mark.integration
class TestConfig:
    def test_missing_api_key_raises(self, no_plausible_key):
        from apps.analytics.plausible_client import fetch_aggregate, PlausibleConfigError
        with pytest.raises(PlausibleConfigError):
            fetch_aggregate(period="7d", base_url=TEST_BASE_URL)


# ── Integration: cache de 1h ──────────────────────────────────────────


@pytest.mark.integration
class TestCache:
    def test_cache_hit_avoids_second_request(self, conn, register_stats, aggregate_payload):
        from apps.analytics.plausible_client import fetch_aggregate
        register_stats("aggregate", aggregate_payload)
        a = fetch_aggregate(period="7d", conn=conn,
                            base_url=TEST_BASE_URL, api_key=TEST_API_KEY)
        b = fetch_aggregate(period="7d", conn=conn,
                            base_url=TEST_BASE_URL, api_key=TEST_API_KEY)
        assert a == b
        # Solo una llamada HTTP real: la segunda salió de cache.
        n = conn.execute("SELECT COUNT(*) FROM plausible_cache").fetchone()[0]
        assert n == 1

    def test_cache_expiry_refetches(self, conn, register_stats, aggregate_payload):
        from apps.analytics.plausible_client import fetch_aggregate
        register_stats("aggregate", aggregate_payload)
        fetch_aggregate(period="7d", conn=conn,
                        base_url=TEST_BASE_URL, api_key=TEST_API_KEY)
        # Envejecer la entrada más allá del TTL.
        conn.execute("UPDATE plausible_cache SET fetched_at = datetime('now', '-2 hour')")
        conn.commit()
        # Segundo response para el refetch.
        register_stats("aggregate", aggregate_payload)
        out = fetch_aggregate(period="7d", conn=conn, ttl=60,
                              base_url=TEST_BASE_URL, api_key=TEST_API_KEY)
        assert out["results"]["visitors"]["value"] == 142


# ── Integration: healthcheck ──────────────────────────────────────────


@pytest.mark.integration
class TestHealth:
    def test_health_ok(self, mocked_http, health_payload):
        import responses
        from apps.analytics.plausible_client import health_check
        mocked_http.add(responses.GET, f"{TEST_BASE_URL}/api/health",
                        json=health_payload, status=200)
        assert health_check(base_url=TEST_BASE_URL) is True

    def test_health_red(self, mocked_http):
        import responses
        from apps.analytics.plausible_client import health_check
        mocked_http.add(responses.GET, f"{TEST_BASE_URL}/api/health",
                        json={"clickhouse": "error", "postgres": "ok"}, status=200)
        assert health_check(base_url=TEST_BASE_URL) is False
