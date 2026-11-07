"""MangaDex API client - download manga pages in English/Spanish.

MangaDex API (api.mangadex.org) is free, no API key required.
It has manga chapters with full page images in multiple languages.

Usage:
    from integrations.mangadex import search_manga, get_chapters, download_chapter_pages

    manga_id = search_manga("Berserk")
    chapters = get_chapters(manga_id, lang="en", limit=5)
    pages = download_chapter_pages(chapters[0]["id"], output_dir="data/manga_panels/berserk")
"""

import logging
import time
from pathlib import Path

from utils.http_client import api_get, download_file

log = logging.getLogger(__name__)

BASE = "https://api.mangadex.org"

# Rate limit: MangaDex allows 5 req/s
_last_request = 0.0


def _rate_limit():
    """MangaDex at-home/server endpoint is stricter than main API.
    Use 1.5s between requests to stay under detection threshold.
    """
    global _last_request
    now = time.time()
    elapsed = now - _last_request
    if elapsed < 1.5:
        time.sleep(1.5 - elapsed)
    _last_request = time.time()


def search_manga(title: str) -> dict | None:
    """Search MangaDex for a manga by title.

    Returns {id, title, description, year, status, content_rating} or None.
    """
    _rate_limit()
    data = api_get(f"{BASE}/manga", params={
        "title": title,
        "limit": 5,
        "includes[]": "cover_art",
        "order[relevance]": "desc",
    })
    if not data or "data" not in data:
        return None

    for manga in data["data"]:
        attrs = manga["attributes"]
        titles = attrs.get("title", {})
        # Get English title, fallback to first available
        en_title = titles.get("en") or titles.get("ja-ro") or next(iter(titles.values()), "")

        return {
            "id": manga["id"],
            "title": en_title,
            "description": (attrs.get("description", {}).get("en") or "")[:200],
            "year": attrs.get("year"),
            "status": attrs.get("status"),
            "content_rating": attrs.get("contentRating"),
        }

    return None


def get_chapters(
    manga_id: str,
    lang: str = "en",
    limit: int = 10,
    offset: int = 0,
    order: str = "asc",
) -> list[dict]:
    """Get chapters for a manga in a specific language.

    Args:
        manga_id: MangaDex manga UUID
        lang: Language code - 'en' for English, 'es' or 'es-la' for Spanish
        limit: Max chapters to return
        offset: Pagination offset
        order: 'asc' or 'desc' by chapter number

    Returns list of {id, chapter, title, pages, volume, lang}.
    """
    _rate_limit()
    params = {
        "manga": manga_id,
        "translatedLanguage[]": lang,
        "limit": limit,
        "offset": offset,
        "order[chapter]": order,
        "includes[]": "scanlation_group",
    }

    data = api_get(f"{BASE}/chapter", params=params)
    if not data or "data" not in data:
        # Try Spanish Latin America if Spanish fails
        if lang == "es":
            return get_chapters(manga_id, lang="es-la", limit=limit, offset=offset, order=order)
        return []

    chapters = []
    for ch in data["data"]:
        attrs = ch["attributes"]
        chapters.append({
            "id": ch["id"],
            "chapter": attrs.get("chapter", "0"),
            "title": attrs.get("title") or f"Chapter {attrs.get('chapter', '?')}",
            "pages": attrs.get("pages", 0),
            "volume": attrs.get("volume"),
            "lang": attrs.get("translatedLanguage", lang),
        })

    log.info(f"MangaDex: {len(chapters)} chapters in '{lang}' for manga {manga_id}")
    return chapters


def download_chapter_pages(
    chapter_id: str,
    output_dir: str,
    quality: str = "data",
    max_pages: int = 0,
) -> list[str]:
    """Download all page images for a chapter.

    Args:
        chapter_id: MangaDex chapter UUID
        output_dir: Directory to save images
        quality: 'data' for full quality, 'data-saver' for compressed
        max_pages: Limit pages (0 = all)

    Returns list of downloaded file paths.
    """
    # Retry loop: MangaDex sometimes returns 404 transiently on at-home/server
    data = None
    for attempt in range(3):
        _rate_limit()
        data = api_get(f"{BASE}/at-home/server/{chapter_id}")
        if data and "chapter" in data:
            break
        if attempt < 2:
            wait = (attempt + 1) * 3
            log.info(f"  Retry {attempt + 1}/3 after {wait}s for chapter {chapter_id[:8]}...")
            time.sleep(wait)

    if not data or "chapter" not in data:
        log.error(f"Failed to get pages for chapter {chapter_id}")
        return []

    base_url = data["baseUrl"]
    chapter_hash = data["chapter"]["hash"]
    filenames = data["chapter"].get(quality, data["chapter"].get("data", []))

    if max_pages > 0:
        filenames = filenames[:max_pages]

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    downloaded = []
    for i, filename in enumerate(filenames):
        url = f"{base_url}/{quality}/{chapter_hash}/{filename}"
        ext = Path(filename).suffix or ".jpg"
        local_path = out_path / f"page_{i:03d}{ext}"

        if local_path.exists() and local_path.stat().st_size > 1000:
            downloaded.append(str(local_path))
            continue

        _rate_limit()
        result = download_file(url, str(local_path))
        if result:
            downloaded.append(str(local_path))
            log.info(f"  Page {i+1}/{len(filenames)}: {local_path.name}")
        else:
            log.warning(f"  Failed to download page {i+1}: {filename}")

    log.info(f"Downloaded {len(downloaded)}/{len(filenames)} pages to {output_dir}")
    return downloaded


def get_popular_chapters(manga_id: str, lang: str = "en", count: int = 5) -> list[dict]:
    """Get chapters likely to have iconic panels.

    Strategy: get the first few chapters (intros are iconic) and some from
    the middle/end (climax chapters). Also prioritize chapters with more pages
    (big fight scenes, reveals).
    """
    # First chapters (introduction, world-building)
    first = get_chapters(manga_id, lang=lang, limit=3, offset=0, order="asc")

    # Count total chapters to find middle/end
    _rate_limit()
    data = api_get(f"{BASE}/chapter", params={
        "manga": manga_id,
        "translatedLanguage[]": lang,
        "limit": 1,
        "offset": 0,
    })
    total = data.get("total", 0) if data else 0

    middle = []
    end = []
    if total > 10:
        mid_offset = total // 2
        middle = get_chapters(manga_id, lang=lang, limit=2, offset=mid_offset, order="asc")
    if total > 20:
        end_offset = max(0, total - 5)
        end = get_chapters(manga_id, lang=lang, limit=2, offset=end_offset, order="asc")

    # Combine and deduplicate
    all_chapters = first + middle + end
    seen = set()
    unique = []
    for ch in all_chapters:
        if ch["id"] not in seen:
            seen.add(ch["id"])
            unique.append(ch)

    return unique[:count]
