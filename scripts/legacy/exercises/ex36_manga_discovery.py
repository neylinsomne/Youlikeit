"""ex36 - Discover trending manga/anime and extract iconic quotes.

ETL Pattern:
  Extract:  Jikan API (MyAnimeList) + AniList GraphQL (both free, no key)
  Transform: Rank by popularity + score + trending status, extract quotes
  Load:     Insert into manga_series + manga_quotes tables

Sources (all free, no API key):
  - Jikan v4 (api.jikan.moe) — MAL data: top anime/manga, seasonal, search
  - AniList GraphQL (graphql.anilist.co) — trending, popularity, recommendations
  - Animechan (animechan.io) — anime/manga quotes
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from core.config import Settings
from core.db import get_db
from utils.http_client import api_get, api_post

log = logging.getLogger(__name__)

JIKAN_BASE = "https://api.jikan.moe/v4"
ANILIST_URL = "https://graphql.anilist.co"
ANIMECHAN_BASE = "https://api.animechan.io/v1"


# ---------------------------------------------------------------------------
# Extract
# ---------------------------------------------------------------------------

def _jikan_get(endpoint: str, params: dict | None = None) -> dict | None:
    """Call Jikan API with automatic rate limit + retry."""
    return api_get(f"{JIKAN_BASE}/{endpoint}", params=params, service="jikan")


def _anilist_query(query: str, variables: dict | None = None) -> dict | None:
    """Call AniList GraphQL API with automatic retry."""
    return api_post(
        ANILIST_URL,
        json={"query": query, "variables": variables or {}},
        service="anilist",
    )


def _extract_trending_anime(max_items: int = 25) -> list[dict]:
    """Get trending anime from Jikan (top airing + top upcoming)."""
    results = []

    # Top airing anime
    data = _jikan_get("top/anime", {"filter": "airing", "limit": max_items})
    if data and "data" in data:
        for item in data["data"][:max_items]:
            results.append(_normalize_jikan_entry(item, "anime"))

    # Top upcoming
    data = _jikan_get("top/anime", {"filter": "upcoming", "limit": 10})
    if data and "data" in data:
        for item in data["data"][:10]:
            entry = _normalize_jikan_entry(item, "anime")
            entry["is_upcoming"] = True
            results.append(entry)

    return results


def _extract_trending_manga(max_items: int = 25) -> list[dict]:
    """Get trending manga from Jikan."""
    results = []

    data = _jikan_get("top/manga", {"filter": "publishing", "limit": max_items})
    if data and "data" in data:
        for item in data["data"][:max_items]:
            results.append(_normalize_jikan_entry(item, "manga"))

    return results


def _extract_anilist_trending(media_type: str = "ANIME", max_items: int = 25) -> list[dict]:
    """Get trending from AniList GraphQL."""
    query = """
    query ($page: Int, $perPage: Int, $type: MediaType) {
        Page(page: $page, perPage: $perPage) {
            media(type: $type, sort: TRENDING_DESC) {
                id
                idMal
                title { romaji english native }
                description
                genres
                averageScore
                popularity
                trending
                status
                episodes
                chapters
                coverImage { large }
                startDate { year month }
                format
                source
            }
        }
    }
    """
    data = _anilist_query(query, {
        "page": 1,
        "perPage": max_items,
        "type": media_type,
    })
    if not data or "data" not in data:
        return []

    results = []
    for item in data["data"]["Page"]["media"]:
        title_en = item["title"].get("english") or item["title"].get("romaji", "")
        title_jp = item["title"].get("native", "")
        year = item.get("startDate", {}).get("year")
        results.append({
            "mal_id": item.get("idMal"),
            "anilist_id": item["id"],
            "title": title_en,
            "title_jp": title_jp,
            "media_type": media_type.lower(),
            "year": year,
            "genres": item.get("genres", []),
            "score": (item.get("averageScore") or 0) / 10,  # Normalize to 0-10
            "popularity": item.get("popularity", 0),
            "trending_score": item.get("trending", 0),
            "status": (item.get("status") or "").lower(),
            "episodes": item.get("episodes"),
            "chapters": item.get("chapters"),
            "cover_url": (item.get("coverImage") or {}).get("large", ""),
            "description": item.get("description", ""),
            "format": (item.get("format") or "").lower(),
            "source": (item.get("source") or "").lower(),
            "is_upcoming": False,
        })
    return results


def _extract_quotes_for_anime(title: str, mal_id: int | None = None) -> list[dict]:
    """Get quotes for an anime from Animechan."""
    quotes = []
    try:
        data = api_get(f"{ANIMECHAN_BASE}/quotes", params={"anime": title}, service="animechan")
        if data:
            items = data.get("data", []) if isinstance(data, dict) else data
            if isinstance(items, list):
                for q in items:
                    text = q.get("content", q.get("quote", ""))
                    char = q.get("character", {})
                    char_name = char.get("name", "") if isinstance(char, dict) else str(char)
                    if text:
                        quotes.append({
                            "text": text,
                            "character": char_name,
                            "source": "animechan",
                        })
    except Exception as e:
        log.debug(f"Animechan error for {title}: {e}")

    # Fallback: Jikan character quotes if we have mal_id
    if not quotes and mal_id:
        data = _jikan_get(f"anime/{mal_id}/characters")
        if data and "data" in data:
            for char in data["data"][:5]:
                char_name = char.get("character", {}).get("name", "")
                if char_name:
                    quotes.append({
                        "text": "",  # Will be filled by LLM later
                        "character": char_name,
                        "source": "jikan_character",
                    })

    return quotes


def _normalize_jikan_entry(item: dict, media_type: str) -> dict:
    """Normalize a Jikan API response entry."""
    return {
        "mal_id": item.get("mal_id"),
        "anilist_id": None,
        "title": item.get("title_english") or item.get("title", ""),
        "title_jp": item.get("title_japanese", ""),
        "media_type": media_type,
        "year": item.get("year"),
        "genres": [g.get("name", "") for g in item.get("genres", [])],
        "score": item.get("score") or 0,
        "popularity": item.get("members", 0),
        "trending_score": item.get("favorites", 0),
        "status": (item.get("status") or "").lower(),
        "episodes": item.get("episodes"),
        "chapters": item.get("chapters"),
        "cover_url": (item.get("images", {}).get("jpg", {}).get("large_image_url", "")),
        "description": item.get("synopsis", ""),
        "format": (item.get("type") or "").lower(),
        "source": (item.get("source") or "").lower(),
        "is_upcoming": False,
    }


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------

def _rank_and_deduplicate(entries: list[dict]) -> list[dict]:
    """Merge duplicates (by mal_id or title) and rank by composite score."""
    seen = {}
    for entry in entries:
        key = entry.get("mal_id") or entry["title"].lower()
        if key in seen:
            existing = seen[key]
            # Merge: keep higher score, combine trending
            if entry["score"] > existing["score"]:
                existing["score"] = entry["score"]
            if entry.get("anilist_id") and not existing.get("anilist_id"):
                existing["anilist_id"] = entry["anilist_id"]
            existing["trending_score"] = max(
                existing.get("trending_score", 0),
                entry.get("trending_score", 0),
            )
        else:
            seen[key] = entry

    ranked = list(seen.values())
    # Composite score: (score * 100) + log(popularity) + trending * 10
    import math
    for entry in ranked:
        pop = max(entry.get("popularity", 1), 1)
        entry["composite_score"] = (
            (entry.get("score", 0) * 100) +
            math.log10(pop) * 20 +
            (entry.get("trending_score", 0) * 0.1)
        )
    ranked.sort(key=lambda x: x["composite_score"], reverse=True)
    return ranked


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def _ensure_manga_tables(conn):
    """Create manga-specific tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS manga_series (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mal_id INTEGER,
            anilist_id INTEGER,
            title TEXT NOT NULL,
            title_jp TEXT,
            media_type TEXT DEFAULT 'anime',  -- anime, manga, manhwa, light_novel
            year INTEGER,
            genres TEXT,                       -- JSON array
            score REAL DEFAULT 0,
            popularity INTEGER DEFAULT 0,
            trending_score INTEGER DEFAULT 0,
            status TEXT,
            episodes INTEGER,
            chapters INTEGER,
            cover_url TEXT,
            description TEXT,
            format TEXT,                       -- tv, movie, ova, ona, manga, manhwa
            source_material TEXT,              -- manga, light_novel, original, game
            composite_score REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(mal_id, media_type)
        );

        CREATE TABLE IF NOT EXISTS manga_quotes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            series_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            character_name TEXT,
            episode INTEGER,
            chapter INTEGER,
            source TEXT,                       -- animechan, manual, llm_generated
            category TEXT,                     -- villain, motivational, comedy, dramatic, romantic, philosophical
            emotion TEXT,
            viral_score INTEGER,
            used_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (series_id) REFERENCES manga_series(id)
        );

        CREATE INDEX IF NOT EXISTS idx_manga_mal ON manga_series(mal_id);
        CREATE INDEX IF NOT EXISTS idx_manga_anilist ON manga_series(anilist_id);
        CREATE INDEX IF NOT EXISTS idx_manga_type ON manga_series(media_type);
        CREATE INDEX IF NOT EXISTS idx_manga_quotes_series ON manga_quotes(series_id);
    """)


def _insert_series(conn, entry: dict) -> int:
    """Insert or update a manga/anime series. Returns id."""
    cur = conn.execute(
        "SELECT id FROM manga_series WHERE mal_id = ? AND media_type = ?",
        (entry.get("mal_id"), entry.get("media_type", "anime")),
    )
    row = cur.fetchone()
    if row:
        conn.execute(
            """UPDATE manga_series SET score = ?, popularity = ?, trending_score = ?,
               composite_score = ?, status = ? WHERE id = ?""",
            (entry["score"], entry["popularity"], entry.get("trending_score", 0),
             entry.get("composite_score", 0), entry.get("status"), row["id"]),
        )
        conn.commit()
        return row["id"]

    cur = conn.execute(
        """INSERT INTO manga_series
           (mal_id, anilist_id, title, title_jp, media_type, year, genres, score,
            popularity, trending_score, status, episodes, chapters, cover_url,
            description, format, source_material, composite_score)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            entry.get("mal_id"), entry.get("anilist_id"),
            entry["title"], entry.get("title_jp", ""),
            entry.get("media_type", "anime"), entry.get("year"),
            json.dumps(entry.get("genres", [])),
            entry.get("score", 0), entry.get("popularity", 0),
            entry.get("trending_score", 0), entry.get("status"),
            entry.get("episodes"), entry.get("chapters"),
            entry.get("cover_url", ""), entry.get("description", ""),
            entry.get("format", ""), entry.get("source", ""),
            entry.get("composite_score", 0),
        ),
    )
    conn.commit()
    return cur.lastrowid


def _insert_quote(conn, series_id: int, quote: dict) -> int | None:
    """Insert a quote if not duplicate."""
    if not quote.get("text"):
        return None
    cur = conn.execute(
        "SELECT id FROM manga_quotes WHERE series_id = ? AND text = ?",
        (series_id, quote["text"]),
    )
    if cur.fetchone():
        return None

    cur = conn.execute(
        """INSERT INTO manga_quotes (series_id, text, character_name, source)
           VALUES (?, ?, ?, ?)""",
        (series_id, quote["text"], quote.get("character", ""), quote.get("source", "animechan")),
    )
    conn.commit()
    return cur.lastrowid


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(settings: Settings, mode: str = "trending", max_items: int = 25,
        media_type: str = "all", with_quotes: bool = True) -> str:
    """Discover trending manga/anime and extract quotes.

    Args:
        mode: trending, top, seasonal, search
        max_items: max series to discover
        media_type: anime, manga, all
        with_quotes: also fetch quotes for discovered series
    """
    data_dir = Path(settings.data_dir)
    conn = get_db(data_dir)
    _ensure_manga_tables(conn)

    all_entries: list[dict] = []
    log.info(f"Discovering {media_type} ({mode}) — max {max_items}")

    # --- Extract ---
    if media_type in ("anime", "all"):
        if mode == "trending":
            all_entries.extend(_extract_trending_anime(max_items))
            all_entries.extend(_extract_anilist_trending("ANIME", max_items))
        elif mode == "top":
            data = _jikan_get("top/anime", {"limit": max_items})
            if data and "data" in data:
                all_entries.extend([_normalize_jikan_entry(i, "anime") for i in data["data"]])
        elif mode == "seasonal":
            now = datetime.now()
            season_map = {1: "winter", 4: "spring", 7: "summer", 10: "fall"}
            season = season_map.get(((now.month - 1) // 3) * 3 + 1, "winter")
            data = _jikan_get(f"seasons/{now.year}/{season}")
            if data and "data" in data:
                all_entries.extend([_normalize_jikan_entry(i, "anime") for i in data["data"][:max_items]])

    if media_type in ("manga", "all"):
        if mode == "trending":
            all_entries.extend(_extract_trending_manga(max_items))
            all_entries.extend(_extract_anilist_trending("MANGA", max_items))
        elif mode == "top":
            data = _jikan_get("top/manga", {"limit": max_items})
            if data and "data" in data:
                all_entries.extend([_normalize_jikan_entry(i, "manga") for i in data["data"]])

    # --- Transform ---
    ranked = _rank_and_deduplicate(all_entries)
    log.info(f"Found {len(all_entries)} raw → {len(ranked)} unique entries")

    # --- Load ---
    new_series = 0
    new_quotes = 0
    for entry in ranked[:max_items]:
        series_id = _insert_series(conn, entry)
        if series_id:
            new_series += 1

        if with_quotes and entry.get("title"):
            quotes = _extract_quotes_for_anime(entry["title"], entry.get("mal_id"))
            for q in quotes:
                qid = _insert_quote(conn, series_id, q)
                if qid:
                    new_quotes += 1

    # --- Report ---
    report_dir = Path(settings.output_dir) / "logs"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"ex36_manga_discovery_{datetime.now():%Y%m%d_%H%M%S}.txt"

    lines = [
        "ex36 - Manga/Anime Discovery Report",
        "=" * 50,
        f"Mode: {mode} | Type: {media_type}",
        f"Raw entries: {len(all_entries)} | Unique: {len(ranked)}",
        f"Series saved: {new_series} | Quotes saved: {new_quotes}",
        "",
        "Top 15 by composite score:",
    ]
    for i, entry in enumerate(ranked[:15], 1):
        genres = ", ".join(entry.get("genres", [])[:3])
        lines.append(
            f"  {i:2d}. [{entry['score']:.1f}/10] {entry['title']} "
            f"({entry['media_type']}) [{genres}] pop={entry['popularity']:,}"
        )

    report_text = "\n".join(lines)
    report_path.write_text(report_text, encoding="utf-8")
    log.info(f"Discovery report: {report_path}")

    # Summary stats
    cur = conn.execute("SELECT COUNT(*) as n FROM manga_series")
    total_series = cur.fetchone()["n"]
    cur = conn.execute("SELECT COUNT(*) as n FROM manga_quotes")
    total_quotes = cur.fetchone()["n"]
    log.info(f"DB totals: {total_series} series, {total_quotes} quotes")

    return str(report_path)
