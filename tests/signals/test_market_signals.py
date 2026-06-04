"""Tests de la capa de ingesta — normalización, persistencia, parsers."""

from __future__ import annotations

import pytest


# ── Unit: normalize_title ─────────────────────────────────────────


@pytest.mark.unit
class TestNormalizeTitle:
    @pytest.mark.parametrize("raw,expected", [
        ("Elden Ring",                          "elden ring"),
        ("Frieren: Beyond Journey's End",       "frieren beyond journey s end"),
        ("HOLA   MUNDO",                        "hola mundo"),
        ("",                                    ""),
        ("---",                                 ""),
    ])
    def test_known_inputs(self, raw, expected):
        from apps.signals.market_signals import normalize_title
        assert normalize_title(raw) == expected

    def test_idempotent(self):
        from apps.signals.market_signals import normalize_title
        a = normalize_title("S.T.A.L.K.E.R. 2")
        assert normalize_title(a) == a

    def test_handles_unicode(self):
        from apps.signals.market_signals import normalize_title
        # Conservar caracteres alfanuméricos unicode
        n = normalize_title("Pasión de Gavilanes")
        assert "pasi" in n
        assert "gavilanes" in n


# ── Unit: Signal dataclass ────────────────────────────────────────


@pytest.mark.unit
class TestSignalDataclass:
    def test_default_values(self):
        from apps.signals.market_signals import Signal
        s = Signal("steam_charts", "gaming_chart", "gaming", "Elden Ring")
        assert s.url == ""
        assert s.raw_score == 0.0
        assert s.raw_meta == {}

    def test_meta_independence(self):
        """Mutar el raw_meta de una instancia no afecta otra (default_factory)."""
        from apps.signals.market_signals import Signal
        a = Signal("x", "y", "z", "t1")
        b = Signal("x", "y", "z", "t2")
        a.raw_meta["k"] = 1
        assert "k" not in b.raw_meta


# ── Integration: persistencia ─────────────────────────────────────


@pytest.mark.integration
class TestPersistence:
    def test_persist_signal_inserts_one(self, conn):
        from apps.signals.market_signals import Signal, _persist_signal
        sig = Signal("steam_charts", "gaming_chart", "gaming",
                     "Elden Ring", url="https://x", raw_score=10)
        assert _persist_signal(conn, sig)
        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM market_signals").fetchone()[0]
        assert n == 1

    def test_persist_signal_idempotent_on_unique(self, conn):
        """UNIQUE(source, normalized_title) → no duplica."""
        from apps.signals.market_signals import Signal, _persist_signal
        sig = Signal("steam_charts", "gaming_chart", "gaming", "Elden Ring")
        _persist_signal(conn, sig)
        _persist_signal(conn, sig)
        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM market_signals").fetchone()[0]
        assert n == 1

    def test_persist_empty_title_rejected(self, conn):
        from apps.signals.market_signals import Signal, _persist_signal
        sig = Signal("steam_charts", "gaming_chart", "gaming", "   ")
        assert _persist_signal(conn, sig) is False

    def test_persist_many_returns_new_count(self, conn, sample_signals):
        from apps.signals.market_signals import _persist_many
        n = _persist_many(conn, sample_signals)
        assert n == len(sample_signals)
        # Re-inserción no añade nuevas
        n2 = _persist_many(conn, sample_signals)
        assert n2 == 0


# ── Integration: RSS parser con HTTP mock ─────────────────────────


SAMPLE_RSS = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Sample Feed</title>
    <item>
      <title>First entry — breaking news</title>
      <link>https://example.com/1</link>
      <description><![CDATA[<p>Body 1</p>]]></description>
    </item>
    <item>
      <title>Second entry</title>
      <link>https://example.com/2</link>
      <description>Plain text 2</description>
    </item>
  </channel>
</rss>"""


@pytest.mark.integration
class TestRSSParser:
    def test_parse_rss_extracts_items(self, mocked_http):
        import responses
        from apps.signals.market_signals import _parse_rss

        mocked_http.add(
            responses.GET, "https://feed.example/rss",
            body=SAMPLE_RSS,
            status=200,
            content_type="application/rss+xml",
        )
        signals = _parse_rss(
            "https://feed.example/rss",
            source="test_src", source_type="editorial_rss",
            domain="movies_tv", max_items=10,
        )
        assert len(signals) == 2
        assert signals[0].title.startswith("First entry")
        assert signals[0].source == "test_src"
        assert signals[0].domain == "movies_tv"
        # raw_score decreciente: item 0 > item 1
        assert signals[0].raw_score > signals[1].raw_score
        # Description tags HTML deben venir stripped
        assert "<p>" not in signals[0].summary

    def test_parse_rss_handles_500(self, mocked_http):
        import responses
        from apps.signals.market_signals import _parse_rss
        mocked_http.add(
            responses.GET, "https://feed.example/down",
            status=500, body="server error",
        )
        signals = _parse_rss(
            "https://feed.example/down",
            source="t", source_type="editorial_rss",
            domain="gaming", max_items=10,
        )
        assert signals == []

    def test_parse_rss_handles_malformed_xml(self, mocked_http):
        import responses
        from apps.signals.market_signals import _parse_rss
        mocked_http.add(
            responses.GET, "https://feed.example/bad",
            body="<not><well>formed",
            status=200,
        )
        signals = _parse_rss(
            "https://feed.example/bad",
            source="t", source_type="editorial_rss",
            domain="gaming", max_items=10,
        )
        assert signals == []


# ── Integration: Reddit JSON parser ───────────────────────────────


SAMPLE_REDDIT_JSON = {
    "data": {
        "children": [
            {"data": {
                "title": "Elden Ring DLC was peak",
                "permalink": "/r/Games/1",
                "selftext": "Body",
                "ups": 5000,
                "num_comments": 200,
                "stickied": False,
                "link_flair_text": "Discussion",
                "created_utc": 1717000000,
            }},
            {"data": {
                "title": "Mod announcement (pinned)",
                "permalink": "/r/Games/2",
                "ups": 100,
                "num_comments": 10,
                "stickied": True,    # debe descartarse
                "selftext": "",
            }},
        ]
    }
}


@pytest.mark.integration
class TestRedditFetcher:
    def test_skips_stickied(self, mocked_http):
        import responses
        from apps.signals.market_signals import fetch_reddit_hot
        mocked_http.add(
            responses.GET,
            "https://www.reddit.com/r/Games/hot.json",
            json=SAMPLE_REDDIT_JSON,
            status=200,
        )
        sigs = fetch_reddit_hot("Games", limit=25)
        assert len(sigs) == 1
        assert sigs[0].source == "reddit_r_Games"
        assert sigs[0].domain == "gaming"
        assert sigs[0].raw_score > 0

    def test_empty_response_yields_empty(self, mocked_http):
        import responses
        from apps.signals.market_signals import fetch_reddit_hot
        mocked_http.add(
            responses.GET,
            "https://www.reddit.com/r/anime/hot.json",
            json={"data": {"children": []}}, status=200,
        )
        assert fetch_reddit_hot("anime") == []


# ── Integration: refresh_source / refresh_all_sources ─────────────


@pytest.mark.integration
class TestOrchestration:
    def test_refresh_unknown_source_returns_zero(self, conn):
        from apps.signals.market_signals import refresh_source
        assert refresh_source(conn, "nonexistent_source_xyz") == 0

    def test_refresh_all_with_empty_filter(self, conn, monkeypatch):
        """Filtro de dominio inexistente → 0 inserts, no crashea."""
        from apps.signals.market_signals import refresh_all_sources
        report = refresh_all_sources(conn, domains=["nonexistent_domain"])
        assert report["total_new"] == 0

    def test_prune_old_signals(self, conn, sample_signals):
        """Backdating: insertar señales y dejarlas viejas → prune las borra."""
        from apps.signals.market_signals import _persist_many, prune_old_signals
        _persist_many(conn, sample_signals)
        # Forzar fetched_at al pasado
        conn.execute(
            "UPDATE market_signals SET fetched_at = datetime('now', '-60 day')"
        )
        conn.commit()
        n = prune_old_signals(conn, retention_days=30)
        assert n == len(sample_signals)
        remaining = conn.execute("SELECT COUNT(*) FROM market_signals").fetchone()[0]
        assert remaining == 0
