"""
Trending Anime Fetcher: auto-discovers what anime is trending NOW.

Sources (all free, no API key needed):
- AniList GraphQL API (most real-time, community-driven)
- Jikan (MyAnimeList proxy)
- TMDb (filter by animation + Japan origin)

Output:
- Top N trending anime with their main characters + images
- Results cached 24h to avoid hammering APIs

Usage:
    from apps.signals.trending_anime import get_trending_character_map

    # Returns {char_name: {work, type, query}} — ready to merge with CHARACTER_WORK_MAP
    trending = get_trending_character_map(top_n=10)
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

log = logging.getLogger(__name__)

CACHE_DIR = Path("data/trending_cache")
CACHE_TTL_HOURS = 24


# ── AniList (GraphQL, no key) ───────────────────────────────────

ANILIST_URL = "https://graphql.anilist.co"


def fetch_anilist_trending(top_n: int = 20) -> list[dict]:
    """Get trending anime from AniList with main characters."""
    query = """
    query ($perPage: Int) {
      Page(perPage: $perPage) {
        media(sort: TRENDING_DESC, type: ANIME, isAdult: false) {
          id
          title { romaji english native }
          popularity
          trending
          averageScore
          format
          status
          coverImage { large }
          characters(sort: ROLE, perPage: 5) {
            nodes {
              name { full first last }
              image { large }
            }
          }
        }
      }
    }
    """

    try:
        resp = requests.post(
            ANILIST_URL,
            json={"query": query, "variables": {"perPage": top_n}},
            timeout=15,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        if resp.status_code != 200:
            log.warning(f"AniList failed: {resp.status_code} {resp.text[:200]}")
            return []

        data = resp.json().get("data", {}).get("Page", {}).get("media", [])

        results = []
        for m in data:
            title = (m.get("title") or {}).get("english") or (m.get("title") or {}).get("romaji", "")
            chars = []
            for ch in (m.get("characters") or {}).get("nodes", [])[:5]:
                name = (ch.get("name") or {}).get("full", "")
                if name:
                    chars.append({
                        "name": name,
                        "image": (ch.get("image") or {}).get("large"),
                    })
            if title:
                results.append({
                    "title": title,
                    "anilist_id": m.get("id"),
                    "popularity": m.get("popularity", 0),
                    "trending": m.get("trending", 0),
                    "score": m.get("averageScore", 0),
                    "status": m.get("status", ""),
                    "cover": (m.get("coverImage") or {}).get("large"),
                    "characters": chars,
                    "source": "anilist",
                })

        log.info(f"AniList: {len(results)} trending anime")
        return results

    except Exception as e:
        log.warning(f"AniList error: {e}")
        return []


# ── Jikan (MyAnimeList, no key) ─────────────────────────────────

JIKAN_URL = "https://api.jikan.moe/v4"


def fetch_jikan_top_airing(top_n: int = 20) -> list[dict]:
    """Get currently airing top anime from Jikan (MAL)."""
    try:
        resp = requests.get(
            f"{JIKAN_URL}/top/anime",
            params={"filter": "airing", "limit": top_n},
            timeout=15,
        )
        if resp.status_code != 200:
            log.warning(f"Jikan failed: {resp.status_code}")
            return []

        data = resp.json().get("data", [])
        results = []
        for m in data:
            results.append({
                "title": m.get("title_english") or m.get("title", ""),
                "title_jp": m.get("title_japanese", ""),
                "mal_id": m.get("mal_id"),
                "score": m.get("score", 0),
                "popularity_rank": m.get("popularity", 9999),
                "members": m.get("members", 0),
                "cover": (m.get("images") or {}).get("jpg", {}).get("large_image_url"),
                "source": "jikan",
            })

        log.info(f"Jikan: {len(results)} top airing")
        return results
    except Exception as e:
        log.warning(f"Jikan error: {e}")
        return []


def fetch_jikan_characters(mal_id: int, limit: int = 5) -> list[dict]:
    """Get main characters for a MAL anime."""
    try:
        resp = requests.get(f"{JIKAN_URL}/anime/{mal_id}/characters", timeout=15)
        if resp.status_code != 200:
            return []

        data = resp.json().get("data", [])[:limit]
        chars = []
        for c in data:
            ch = c.get("character", {})
            chars.append({
                "name": ch.get("name", ""),
                "image": (ch.get("images") or {}).get("jpg", {}).get("image_url"),
                "role": c.get("role", ""),
            })
        return chars
    except Exception:
        return []


# ── TMDb (animation + Japan) ────────────────────────────────────

def fetch_tmdb_trending_anime(top_n: int = 10) -> list[dict]:
    """Get trending Japanese animation from TMDb."""
    key = os.getenv("TMDB_API_KEY", "")
    if not key:
        return []

    try:
        resp = requests.get(
            "https://api.themoviedb.org/3/discover/tv",
            params={
                "api_key": key,
                "with_genres": "16",  # Animation
                "with_origin_country": "JP",
                "sort_by": "popularity.desc",
                "page": 1,
            },
            timeout=15,
        )
        if resp.status_code != 200:
            return []

        results = resp.json().get("results", [])[:top_n]
        out = []
        for r in results:
            out.append({
                "title": r.get("name", ""),
                "original_title": r.get("original_name", ""),
                "tmdb_id": r.get("id"),
                "popularity": r.get("popularity", 0),
                "vote_average": r.get("vote_average", 0),
                "source": "tmdb",
            })

        log.info(f"TMDb: {len(out)} trending anime")
        return out
    except Exception as e:
        log.warning(f"TMDb error: {e}")
        return []


# ── Cross-reference merge ───────────────────────────────────────

def _normalize_title(title: str) -> str:
    """Normalize titles for matching across sources."""
    t = title.lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    t = re.sub(r"\bseason\s*\d+\b", "", t)
    t = re.sub(r"\bpart\s*\d+\b", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def cross_reference_sources(top_n: int = 15) -> list[dict]:
    """
    Fetch from all 3 sources and find anime that appear in multiple.
    Stronger signal = more sources confirm it's trending.
    """
    anilist = fetch_anilist_trending(top_n=25)
    jikan = fetch_jikan_top_airing(top_n=25)
    tmdb = fetch_tmdb_trending_anime(top_n=20)

    merged = {}

    for a in anilist:
        key = _normalize_title(a["title"])
        if key:
            merged[key] = {
                "title": a["title"],
                "sources": ["anilist"],
                "anilist_id": a.get("anilist_id"),
                "trending_score": a.get("trending", 0),
                "popularity": a.get("popularity", 0),
                "characters": a.get("characters", []),
                "cover": a.get("cover"),
            }

    for j in jikan:
        key = _normalize_title(j["title"])
        if not key:
            continue
        if key in merged:
            merged[key]["sources"].append("jikan")
            merged[key]["mal_id"] = j.get("mal_id")
            merged[key]["mal_score"] = j.get("score")
            merged[key]["members"] = j.get("members", 0)
        else:
            merged[key] = {
                "title": j["title"],
                "sources": ["jikan"],
                "mal_id": j.get("mal_id"),
                "mal_score": j.get("score", 0),
                "members": j.get("members", 0),
                "characters": [],
                "cover": j.get("cover"),
            }

    for t in tmdb:
        key = _normalize_title(t["title"])
        if not key:
            continue
        if key in merged:
            merged[key]["sources"].append("tmdb")
            merged[key]["tmdb_id"] = t.get("tmdb_id")
            merged[key]["tmdb_popularity"] = t.get("popularity", 0)

    # Compute combined score: source count + normalized popularity
    for item in merged.values():
        source_bonus = len(set(item["sources"])) * 100  # +100 per source
        trending = item.get("trending_score", 0)
        popularity = item.get("popularity", 0) / 1000  # MAL can have huge numbers
        mal_members = min(item.get("members", 0) / 10000, 500)  # Cap impact
        item["composite_score"] = source_bonus + trending + popularity + mal_members

    ranked = sorted(merged.values(), key=lambda x: x["composite_score"], reverse=True)

    # Fetch characters for top items from Jikan if they don't have any yet
    for item in ranked[:top_n]:
        if not item.get("characters") and item.get("mal_id"):
            item["characters"] = fetch_jikan_characters(item["mal_id"])

    return ranked[:top_n]


# ── Character map builder ───────────────────────────────────────

def get_trending_character_map(
    top_n: int = 10,
    use_cache: bool = True,
) -> dict[str, dict]:
    """
    Get a CHARACTER_WORK_MAP-style dict from current trending anime.

    Returns:
        {"character_name_lower": {"work": "...", "type": "tv", "query": "...", "trending": True}}
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / "trending_character_map.json"

    # Check cache
    if use_cache and cache_file.exists():
        try:
            cache_data = json.loads(cache_file.read_text(encoding="utf-8"))
            cached_at = datetime.fromisoformat(cache_data["cached_at"])
            if datetime.utcnow() - cached_at < timedelta(hours=CACHE_TTL_HOURS):
                log.info(f"Using cached trending map ({len(cache_data['map'])} chars)")
                return cache_data["map"]
        except Exception:
            pass

    # Fetch fresh
    log.info("Fetching fresh trending anime data...")
    trending = cross_reference_sources(top_n=top_n)

    char_map = {}
    for anime in trending:
        title = anime["title"]
        # Add each main character
        for ch in anime.get("characters", []):
            name = ch.get("name", "")
            if not name or len(name) < 3:
                continue
            key = name.lower().strip()
            char_map[key] = {
                "work": title,
                "type": "tv",
                "query": title,
                "trending": True,
                "sources": anime.get("sources", []),
                "character_image": ch.get("image"),
                "anime_cover": anime.get("cover"),
            }

    # Cache
    cache_file.write_text(
        json.dumps({
            "cached_at": datetime.utcnow().isoformat(),
            "map": char_map,
            "trending_list": trending,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    log.info(f"Built trending map: {len(char_map)} characters from {len(trending)} anime")
    return char_map


def get_trending_titles(top_n: int = 10, use_cache: bool = True) -> list[dict]:
    """Just return the trending anime titles (without character breakdown)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / "trending_character_map.json"

    if use_cache and cache_file.exists():
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            return data.get("trending_list", [])[:top_n]
        except Exception:
            pass

    return cross_reference_sources(top_n=top_n)
