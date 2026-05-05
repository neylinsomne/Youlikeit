"""
Cross-reference image fetcher: when narration mentions a character/work,
find and download images of that character/work.

Examples:
- "Walter White" → downloads Breaking Bad still with Walter White
- "Light Yagami" → downloads Death Note image
- "Michael Corleone" → downloads The Godfather still

Uses TMDb for movies/shows and Wikipedia for anime characters.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

import requests

log = logging.getLogger(__name__)

TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMG = "https://image.tmdb.org/t/p/w780"

# ── Curated map: trending anime + auteur cinema antiheroes ──
# NO Marvel, NO Dragon Ball, NO Hollywood blockbusters — we focus on
# complex characters with depth that the analytical audience cares about.
CHARACTER_WORK_MAP = {
    # ── Cinema: auteur / psychological / antiheroes ──
    "walter white": {"work": "Breaking Bad", "type": "tv", "query": "Breaking Bad"},
    "michael corleone": {"work": "The Godfather", "type": "movie", "query": "The Godfather"},
    "travis bickle": {"work": "Taxi Driver", "type": "movie", "query": "Taxi Driver"},
    "tyler durden": {"work": "Fight Club", "type": "movie", "query": "Fight Club"},
    "anton chigurh": {"work": "No Country for Old Men", "type": "movie", "query": "No Country for Old Men"},
    "hannibal lecter": {"work": "Silence of the Lambs", "type": "movie", "query": "Silence of the Lambs"},
    "patrick bateman": {"work": "American Psycho", "type": "movie", "query": "American Psycho"},
    "arthur fleck": {"work": "Joker", "type": "movie", "query": "Joker 2019"},
    "joker": {"work": "Joker", "type": "movie", "query": "Joker 2019"},
    "daniel plainview": {"work": "There Will Be Blood", "type": "movie", "query": "There Will Be Blood"},
    "thomas shelby": {"work": "Peaky Blinders", "type": "tv", "query": "Peaky Blinders"},
    "logan roy": {"work": "Succession", "type": "tv", "query": "Succession"},

    # ── Anime/Manga: trending + iconic seinen/psychological ──
    # Death Note (timeless)
    "light yagami": {"work": "Death Note", "type": "tv", "query": "Death Note"},
    # Code Geass
    "lelouch": {"work": "Code Geass", "type": "tv", "query": "Code Geass"},
    "lelouch lamperouge": {"work": "Code Geass", "type": "tv", "query": "Code Geass"},
    # Berserk (our core)
    "griffith": {"work": "Berserk", "type": "tv", "query": "Berserk"},
    "guts": {"work": "Berserk", "type": "tv", "query": "Berserk"},
    "casca": {"work": "Berserk", "type": "tv", "query": "Berserk"},
    # Attack on Titan
    "eren yeager": {"work": "Attack on Titan", "type": "tv", "query": "Attack on Titan"},
    "eren jaeger": {"work": "Attack on Titan", "type": "tv", "query": "Attack on Titan"},
    "eren": {"work": "Attack on Titan", "type": "tv", "query": "Attack on Titan"},
    # Vinland Saga
    "thorfinn": {"work": "Vinland Saga", "type": "tv", "query": "Vinland Saga"},
    "askeladd": {"work": "Vinland Saga", "type": "tv", "query": "Vinland Saga"},
    # Monster (psychological masterpiece)
    "johan liebert": {"work": "Monster", "type": "tv", "query": "Monster anime"},
    "kenzo tenma": {"work": "Monster", "type": "tv", "query": "Monster anime"},
    # Vagabond
    "musashi": {"work": "Vagabond", "type": "tv", "query": "Vagabond manga"},
    # Jujutsu Kaisen (trending 2024-2026)
    "gojo": {"work": "Jujutsu Kaisen", "type": "tv", "query": "Jujutsu Kaisen"},
    "satoru gojo": {"work": "Jujutsu Kaisen", "type": "tv", "query": "Jujutsu Kaisen"},
    "sukuna": {"work": "Jujutsu Kaisen", "type": "tv", "query": "Jujutsu Kaisen"},
    "yuji": {"work": "Jujutsu Kaisen", "type": "tv", "query": "Jujutsu Kaisen"},
    # Chainsaw Man (trending)
    "denji": {"work": "Chainsaw Man", "type": "tv", "query": "Chainsaw Man"},
    "makima": {"work": "Chainsaw Man", "type": "tv", "query": "Chainsaw Man"},
    # Frieren (trending 2024-2026)
    "frieren": {"work": "Frieren", "type": "tv", "query": "Frieren Beyond Journey's End"},
    # Solo Leveling (trending)
    "sung jinwoo": {"work": "Solo Leveling", "type": "tv", "query": "Solo Leveling"},
    # Oshi no Ko (trending)
    "aqua hoshino": {"work": "Oshi no Ko", "type": "tv", "query": "Oshi no Ko"},
    # Evangelion (seminal)
    "shinji ikari": {"work": "Neon Genesis Evangelion", "type": "tv", "query": "Neon Genesis Evangelion"},
    "shinji": {"work": "Neon Genesis Evangelion", "type": "tv", "query": "Neon Genesis Evangelion"},
    # Cowboy Bebop (seminal)
    "spike spiegel": {"work": "Cowboy Bebop", "type": "tv", "query": "Cowboy Bebop"},
    # FMA (seminal)
    "edward elric": {"work": "Fullmetal Alchemist", "type": "tv", "query": "Fullmetal Alchemist Brotherhood"},
    # Tokyo Ghoul (still relevant for dark themes)
    "kaneki": {"work": "Tokyo Ghoul", "type": "tv", "query": "Tokyo Ghoul"},

    # ── Auteurs (for craft analysis) ──
    "tarkovsky": {"work": "Stalker", "type": "movie", "query": "Stalker 1979"},
    "kubrick": {"work": "2001 Space Odyssey", "type": "movie", "query": "2001 Space Odyssey"},
    "nolan": {"work": "Inception", "type": "movie", "query": "Inception"},
    "miyazaki": {"work": "Spirited Away", "type": "movie", "query": "Spirited Away"},
    "miura": {"work": "Berserk", "type": "tv", "query": "Berserk"},
    "miuri": {"work": "Berserk", "type": "tv", "query": "Berserk"},
}

# ── A/B testing pool: experimental references for variety ──
# These are intentionally risky/unusual combos we test periodically
# to see if surprising cross-refs outperform safe ones.
EXPERIMENTAL_CHARACTER_MAP = {
    # Classic anime (older, might not resonate with young audience)
    "naruto": {"work": "Naruto", "type": "tv", "query": "Naruto"},
    "luffy": {"work": "One Piece", "type": "tv", "query": "One Piece"},
    # Mainstream Western (for contrast tests)
    "darth vader": {"work": "Star Wars", "type": "movie", "query": "Star Wars"},
    # Marvel (saved for A/B test of "mainstream vs niche")
    "thanos": {"work": "Avengers", "type": "movie", "query": "Avengers Infinity War"},
    # One Punch Man (already very saturated)
    "saitama": {"work": "One Punch Man", "type": "tv", "query": "One Punch Man"},
}


# ── Image cache ─────────────────────────────────────────────────

_image_cache: dict[str, str] = {}


def _get_active_map(include_trending: bool = True, include_experimental: bool = False) -> dict:
    """
    Build the active character map by merging:
    - CURATED (permanent, vetted)
    - TRENDING (auto-fetched from AniList/MAL/TMDb every 24h) — optional
    - EXPERIMENTAL (A/B testing) — optional
    """
    active = dict(CHARACTER_WORK_MAP)

    if include_trending:
        try:
            from common.trending_anime import get_trending_character_map
            trending = get_trending_character_map(top_n=10)
            # Trending ADDS without overriding curated (curated wins on conflict)
            for k, v in trending.items():
                if k not in active:
                    active[k] = v
        except Exception as e:
            log.debug(f"Trending fetch skipped: {e}")

    if include_experimental:
        for k, v in EXPERIMENTAL_CHARACTER_MAP.items():
            if k not in active:
                active[k] = {"experimental": True, **v}

    return active


def detect_references_in_text(
    text: str,
    include_experimental: bool = False,
    include_trending: bool = True,
) -> list[dict]:
    """
    Detect character/work references in a narration segment.

    Args:
        text: narration segment text
        include_experimental: if True, also match against EXPERIMENTAL_CHARACTER_MAP
                              (use only for A/B test videos, not default flow)
        include_trending: if True, also check live trending anime characters
                          (default True — auto-updates every 24h)

    Returns list of references: [{character, work, type, query}]
    """
    found = []
    text_lower = text.lower()

    active_map = _get_active_map(
        include_trending=include_trending,
        include_experimental=include_experimental,
    )

    for char, info in active_map.items():
        # Use word boundary to avoid substring false positives
        # e.g., "eren" should not match inside "Frieren"
        pattern = r"\b" + re.escape(char) + r"\b"
        if re.search(pattern, text_lower):
            found.append({
                "character": char,
                **info,
            })

    return found


def detect_references_llm(text: str) -> list[dict]:
    """
    Use LLM to detect any character/work reference (beyond the map).

    Good for catching references not in CHARACTER_WORK_MAP.
    """
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        return []

    prompt = f"""Analyze this narration segment and identify if it mentions any specific
CHARACTER from cinema, anime, manga, or TV series.

Return JSON array (no markdown). Empty array if no references:
[
  {{"character": "name", "work": "series/movie name", "type": "tv" or "movie", "query": "search term for TMDb"}}
]

Only include CHARACTERS (not directors, authors, or real people).
Only include characters from FICTIONAL works.

Segment: "{text}"
"""

    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}",
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 500},
            },
            timeout=15,
        )
        text_out = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        text_out = re.sub(r"```json?\s*", "", text_out).strip().rstrip("`")
        refs = json.loads(text_out)
        return refs if isinstance(refs, list) else []
    except Exception as e:
        log.warning(f"LLM ref detection failed: {e}")
        return []


# ── Image fetching ──────────────────────────────────────────────

def fetch_tmdb_images_for_query(query: str, media_type: str = "tv") -> list[str]:
    """Get still images / backdrops from TMDb for a query."""
    api_key = os.getenv("TMDB_API_KEY", "")
    if not api_key:
        return []

    # Search
    try:
        resp = requests.get(
            f"{TMDB_API}/search/{media_type}",
            params={"api_key": api_key, "query": query},
            timeout=10,
        )
        results = resp.json().get("results", [])
        if not results:
            # Try the other type
            other_type = "movie" if media_type == "tv" else "tv"
            resp = requests.get(
                f"{TMDB_API}/search/{other_type}",
                params={"api_key": api_key, "query": query},
                timeout=10,
            )
            results = resp.json().get("results", [])
            media_type = other_type
            if not results:
                return []

        item_id = results[0]["id"]

        # Get images
        img_resp = requests.get(
            f"{TMDB_API}/{media_type}/{item_id}/images",
            params={"api_key": api_key},
            timeout=10,
        )
        imgs_data = img_resp.json()
        backdrops = imgs_data.get("backdrops", [])
        posters = imgs_data.get("posters", [])

        # Prefer backdrops (widescreen), fall back to posters
        urls = []
        for b in backdrops[:5]:
            urls.append(f"{TMDB_IMG}{b['file_path']}")
        for p in posters[:3]:
            urls.append(f"{TMDB_IMG}{p['file_path']}")

        return urls

    except Exception as e:
        log.warning(f"TMDb image fetch failed for {query}: {e}")
        return []


def download_image(url: str, output_dir: Path, prefix: str) -> str | None:
    """Download an image to local disk. Returns local path."""
    cache_key = f"{prefix}:{url}"
    if cache_key in _image_cache:
        cached = _image_cache[cache_key]
        if Path(cached).exists():
            return cached

    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "YouLikeIt/1.0"})
        if resp.status_code != 200:
            return None

        output_dir.mkdir(parents=True, exist_ok=True)
        ext = Path(url).suffix or ".jpg"
        out_path = output_dir / f"{prefix}{ext}"
        out_path.write_bytes(resp.content)

        _image_cache[cache_key] = str(out_path)
        return str(out_path)

    except Exception as e:
        log.warning(f"Image download failed: {e}")
        return None


def get_cross_ref_image(character: str, cache_dir: str = "data/cross_ref_images") -> str | None:
    """
    Get an image for a character reference.
    Returns local path or None if nothing found.

    Priority order:
    1. Local cache (already downloaded)
    2. Trending map (if character has direct image URL from AniList)
    3. Curated/experimental map → TMDb search
    4. LLM detection → TMDb search
    """
    char_lower = character.lower().strip()
    cache_key = f"char:{char_lower}"

    if cache_key in _image_cache:
        cached = _image_cache[cache_key]
        if Path(cached).exists():
            return cached

    # Try trending map first (it has direct character images from AniList)
    active_map = _get_active_map(include_trending=True, include_experimental=False)
    info = active_map.get(char_lower)

    # Trending anime include a direct character_image URL — use that if available
    if info and info.get("character_image"):
        out_dir = Path(cache_dir)
        slug = re.sub(r"[^a-z0-9]+", "_", char_lower)[:40]
        path = download_image(info["character_image"], out_dir, f"{slug}_trending")
        if path:
            _image_cache[cache_key] = path
            log.info(f"  Fetched (AniList): {character} -> {Path(path).name}")
            return path

    if not info:
        # Try LLM
        refs = detect_references_llm(character)
        if refs:
            info = refs[0]
        else:
            log.info(f"No info for '{character}'")
            return None

    # Fetch image URLs from TMDb
    urls = fetch_tmdb_images_for_query(info["query"], info.get("type", "tv"))
    if not urls:
        return None

    out_dir = Path(cache_dir)
    slug = re.sub(r"[^a-z0-9]+", "_", char_lower)[:40]
    for i, url in enumerate(urls):
        path = download_image(url, out_dir, f"{slug}_{i}")
        if path:
            _image_cache[cache_key] = path
            log.info(f"  Fetched (TMDb): {character} -> {Path(path).name}")
            return path

    return None


# ── Main integration ────────────────────────────────────────────

def enrich_segments_with_cross_refs(
    narration_segments: list[dict],
    cache_dir: str = "data/cross_ref_images",
    include_experimental: bool = False,
    include_trending: bool = True,
) -> list[str]:
    """
    For each segment, if it mentions a known character, fetch and
    add that character's image to the available image pool.

    Args:
        narration_segments: list of segments with text
        cache_dir: where to save downloaded images
        include_experimental: include EXPERIMENTAL_CHARACTER_MAP (A/B test videos)
        include_trending: include live trending anime from AniList/MAL/TMDb (default True)

    Returns list of additional image paths (to add to panel_matcher pool).
    """
    extra_images = []
    seen_chars = set()

    for seg in narration_segments:
        text = seg.get("text", seg.get("narration_text", ""))
        refs = detect_references_in_text(
            text,
            include_experimental=include_experimental,
            include_trending=include_trending,
        )

        for ref in refs:
            char = ref["character"]
            if char in seen_chars:
                continue
            seen_chars.add(char)

            img_path = get_cross_ref_image(char, cache_dir)
            if img_path:
                extra_images.append(img_path)

    return extra_images


def tag_segments_with_references(narration_segments: list[dict]) -> list[dict]:
    """
    Add 'references' field to each segment listing detected characters + image paths.
    Does NOT modify matched_image — that's the panel_matcher's job.
    """
    for seg in narration_segments:
        text = seg.get("text", seg.get("narration_text", ""))
        refs = detect_references_in_text(text)

        if refs:
            # Fetch images for each
            for ref in refs:
                img = get_cross_ref_image(ref["character"])
                ref["image"] = img
            seg["references"] = refs

    return narration_segments
