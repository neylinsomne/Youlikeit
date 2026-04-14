"""
Fandom Wiki Scraper: extract iconic scene images from anime/manga fandom wikis.

Why this is better than APIs:
- Fandom uses MediaWiki API (free, no key, well-documented, stable for 15+ years)
- Each series has a dedicated wiki maintained by fans (berserk.fandom, jujutsu-kaisen.fandom)
- Episode pages have named image galleries: "Sukuna punishes Mahito", "Junpei's death"
- Character pages have full image galleries per character
- Chapter pages link to specific manga panels discussed
- NO rate limits like the Reddit API, NO licensing issues like MangaDex
- 1920x1080 quality images hosted on static.wikia.nocookie.net (CDN)

Example flow:
    # For JJK Ep13
    images = get_episode_images("jujutsu-kaisen", "Episode 13")
    # Returns [{title, url, width, height}]
    # "File:Mahito traps Nanami in his Domain (Anime).png" → direct CDN URL

Wiki names (subdomain):
    berserk, jujutsu-kaisen, onepiece, attackontitan, vinlandsaga,
    monster, deathnote, chainsaw-man, naruto, fullmetal-alchemist,
    oshinoko, frieren
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from urllib.parse import quote

import requests

log = logging.getLogger(__name__)

UA = "Mozilla/5.0 (compatible; YouLikeItBot/1.0; +https://youlikeit.com)"
CACHE_DIR = Path("data/fandom_stills")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Series slug → Fandom wiki subdomain
WIKI_SUBDOMAINS = {
    "berserk": "berserk",
    "jujutsu_kaisen": "jujutsu-kaisen",
    "one_piece": "onepiece",
    "attack_on_titan": "attackontitan",
    "vinland_saga": "vinlandsaga",
    "monster": "monster",
    "death_note": "deathnote",
    "chainsaw_man": "chainsaw-man",
    "naruto": "naruto",
    "fullmetal_alchemist": "fma",
    "oshi_no_ko": "oshinoko",
    "frieren": "frieren",
    "bleach": "bleach",
    "hunter_x_hunter": "hunterxhunter",
    "neon_genesis_evangelion": "evangelion",
    "cowboy_bebop": "cowboybebop",
    "tokyo_ghoul": "tokyoghoul",
    "code_geass": "codegeass",
    "vagabond": "vagabond",
    "solo_leveling": "sololeveling",
}

# Rate limit per domain (Fandom is generous but respect 1s between calls)
_last_request: dict[str, float] = {}


def _rate_limit(subdomain: str, min_interval_s: float = 1.0):
    now = time.time()
    last = _last_request.get(subdomain, 0)
    elapsed = now - last
    if elapsed < min_interval_s:
        time.sleep(min_interval_s - elapsed)
    _last_request[subdomain] = time.time()


def _api_call(subdomain: str, params: dict) -> dict:
    """Call MediaWiki API for a Fandom wiki subdomain."""
    _rate_limit(subdomain)
    try:
        resp = requests.get(
            f"https://{subdomain}.fandom.com/api.php",
            params={"format": "json", **params},
            headers={"User-Agent": UA},
            timeout=15,
        )
        if resp.status_code != 200:
            log.debug(f"Fandom API {subdomain} returned {resp.status_code}")
            return {}
        return resp.json()
    except Exception as e:
        log.debug(f"Fandom API {subdomain} error: {e}")
        return {}


# ── Page discovery ──────────────────────────────────────────────

def search_pages(series_slug: str, query: str, limit: int = 10) -> list[dict]:
    """Search for pages on a series wiki (episodes, characters, chapters)."""
    subdomain = WIKI_SUBDOMAINS.get(series_slug, series_slug)
    data = _api_call(subdomain, {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": limit,
    })
    return data.get("query", {}).get("search", [])


def get_page_images(series_slug: str, page_title: str, limit: int = 30) -> list[str]:
    """
    Get all image file titles referenced on a wiki page.

    Returns list of file titles like: "File:Sukuna punishes Mahito.png"
    """
    subdomain = WIKI_SUBDOMAINS.get(series_slug, series_slug)
    data = _api_call(subdomain, {
        "action": "query",
        "titles": page_title,
        "prop": "images",
        "imlimit": limit,
    })
    pages = data.get("query", {}).get("pages", {})
    titles = []
    for _pid, page in pages.items():
        for img in page.get("images", []):
            title = img.get("title", "")
            # Filter out generic wiki UI images (icons, logos)
            if any(skip in title.lower() for skip in [
                "wiki-wordmark", "site-favicon", "wiki-background",
                ".svg", "external link", "question mark", "spoiler",
                "site-logo", "logo.png", "favicon",
            ]):
                continue
            if title:
                titles.append(title)
    return titles


def get_image_url(series_slug: str, file_title: str) -> dict | None:
    """Resolve a File: title to its actual CDN URL + dimensions."""
    subdomain = WIKI_SUBDOMAINS.get(series_slug, series_slug)
    data = _api_call(subdomain, {
        "action": "query",
        "titles": file_title,
        "prop": "imageinfo",
        "iiprop": "url|size|mime",
    })
    pages = data.get("query", {}).get("pages", {})
    for _pid, page in pages.items():
        infos = page.get("imageinfo", [])
        if infos:
            info = infos[0]
            return {
                "url": info.get("url"),
                "width": info.get("width", 0),
                "height": info.get("height", 0),
                "mime": info.get("mime", ""),
                "size": info.get("size", 0),
                "title": file_title,
            }
    return None


# ── High-level functions ────────────────────────────────────────

def get_episode_images(
    series_slug: str,
    episode_number: int,
    season: int = 1,
    max_images: int = 8,
) -> list[dict]:
    """
    Get iconic scene images for a specific episode.

    Strategy:
    1. Try "Episode N" (most common)
    2. Try "Episode N (YYYY Anime)" for older series with multiple adaptations
    3. Take images from the page, resolve to URLs
    """
    subdomain = WIKI_SUBDOMAINS.get(series_slug, series_slug)

    candidates = [
        f"Episode {episode_number}",
        f"Episode {episode_number} (Anime)",
        f"Episode {episode_number} (2020 Anime)",
        f"Episode {episode_number} (2023 Anime)",
        f"Season {season} Episode {episode_number}",
    ]

    file_titles = []
    for page_title in candidates:
        file_titles = get_page_images(series_slug, page_title, limit=max_images * 2)
        if file_titles:
            log.info(f"  {subdomain} page '{page_title}': {len(file_titles)} images")
            break

    if not file_titles:
        # Fallback: search
        results = search_pages(series_slug, f"Episode {episode_number}", limit=3)
        for r in results:
            file_titles = get_page_images(series_slug, r["title"], limit=max_images * 2)
            if file_titles:
                break

    # Resolve to URLs
    images = []
    for title in file_titles[:max_images]:
        info = get_image_url(series_slug, title)
        if info and info.get("url"):
            # Skip .gif (too big + animated) and tiny images
            if info.get("mime") == "image/gif":
                continue
            if info.get("width", 0) < 200 or info.get("height", 0) < 200:
                continue
            images.append(info)

    return images


def get_character_images(
    series_slug: str,
    character_name: str,
    max_images: int = 5,
) -> list[dict]:
    """Get character portraits/scenes from their wiki page."""
    file_titles = get_page_images(series_slug, character_name, limit=max_images * 2)

    if not file_titles:
        results = search_pages(series_slug, character_name, limit=3)
        for r in results:
            file_titles = get_page_images(series_slug, r["title"], limit=max_images * 2)
            if file_titles:
                break

    images = []
    for title in file_titles[:max_images]:
        info = get_image_url(series_slug, title)
        if info and info.get("url") and info.get("mime") != "image/gif":
            if info.get("width", 0) >= 200:
                images.append(info)
    return images


def get_chapter_images(
    series_slug: str,
    chapter_number: int,
    max_images: int = 5,
) -> list[dict]:
    """Get manga chapter images/panels from wiki."""
    candidates = [
        f"Chapter {chapter_number}",
        f"Chapter {chapter_number} (Manga)",
    ]

    file_titles = []
    for page_title in candidates:
        file_titles = get_page_images(series_slug, page_title, limit=max_images * 2)
        if file_titles:
            break

    images = []
    for title in file_titles[:max_images]:
        info = get_image_url(series_slug, title)
        if info and info.get("url"):
            images.append(info)
    return images


# ── Download ────────────────────────────────────────────────────

def download_image(url: str, out_dir: Path, prefix: str) -> str | None:
    """Download a Fandom CDN image to local disk."""
    try:
        # Strip Fandom revision params for cleaner filename
        clean_url = url.split("/revision/")[0] if "/revision/" in url else url
        ext = Path(clean_url).suffix or ".jpg"
        if "?" in ext:
            ext = ext.split("?")[0]
        if ext.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
            ext = ".jpg"

        out_path = out_dir / f"{prefix}{ext}"
        if out_path.exists() and out_path.stat().st_size > 1000:
            return str(out_path)

        resp = requests.get(url, timeout=20, headers={"User-Agent": UA})
        if resp.status_code != 200 or len(resp.content) < 1000:
            return None

        out_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(resp.content)
        return str(out_path)
    except Exception as e:
        log.debug(f"Fandom download failed: {e}")
        return None


def download_episode_iconic_scenes(
    series_slug: str,
    episode_number: int,
    season: int = 1,
    max_images: int = 5,
) -> list[str]:
    """Download iconic scene images for an episode to local disk."""
    images = get_episode_images(series_slug, episode_number, season, max_images)
    if not images:
        return []

    out_dir = CACHE_DIR / series_slug
    paths = []
    for i, img in enumerate(images):
        prefix = f"{series_slug}_s{season}e{episode_number}_{i:02d}"
        path = download_image(img["url"], out_dir, prefix)
        if path:
            paths.append(path)
            log.info(f"  Fandom: {img['title'][:60]} -> {Path(path).name}")

    return paths


def download_character_scenes(
    series_slug: str,
    character_name: str,
    max_images: int = 3,
) -> list[str]:
    """Download character scene images."""
    images = get_character_images(series_slug, character_name, max_images)
    if not images:
        return []

    out_dir = CACHE_DIR / series_slug / "characters"
    slug = re.sub(r"[^a-z0-9]+", "_", character_name.lower()).strip("_")
    paths = []
    for i, img in enumerate(images):
        prefix = f"{slug}_{i:02d}"
        path = download_image(img["url"], out_dir, prefix)
        if path:
            paths.append(path)
    return paths


# ── Convenience integration ─────────────────────────────────────

def enrich_thematic_moments_with_fandom(
    conn,
    series_slug: str,
    min_images_per_moment: int = 2,
) -> int:
    """
    For each scene_moment in the DB, try to scrape additional iconic
    images from the series Fandom wiki. Downloads and caches them.

    Returns number of moments enriched.
    """
    if series_slug not in WIKI_SUBDOMAINS:
        log.info(f"  No Fandom wiki mapped for {series_slug}")
        return 0

    rows = conn.execute(
        """SELECT id, season_number, episode_number, moment_description
           FROM scene_moments WHERE series_slug = ?""",
        (series_slug,),
    ).fetchall()

    enriched = 0
    for r in rows:
        ep = r["episode_number"]
        season = r["season_number"] or 1
        if not ep:
            continue

        paths = download_episode_iconic_scenes(
            series_slug, ep, season, max_images=min_images_per_moment,
        )
        if paths:
            enriched += 1

    log.info(f"  Fandom enriched {enriched}/{len(rows)} moments for {series_slug}")
    return enriched
