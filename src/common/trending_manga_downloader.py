"""
Trending Manga Downloader: auto-downloads manga pages for trending anime.

Flow:
1. Get trending anime list (from trending_anime.py)
2. For each anime, search on MangaDex
3. Download N pages from key chapters (first chapter + climactic middle + latest)
4. Save to data/manga_panels/[slug]/

Also supports manual download by title.

Usage:
    from common.trending_manga_downloader import download_trending_manga, download_manga_by_title

    # Auto: download pages for current trending anime
    results = download_trending_manga(top_n=5, pages_per_manga=12)

    # Manual
    pages = download_manga_by_title("Vinland Saga", pages=12)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from common.mangadex import search_manga, get_chapters, download_chapter_pages

log = logging.getLogger(__name__)

OUTPUT_BASE = Path("data/manga_panels")

# Titles to skip (not available as manga, or dubs/spin-offs we don't want)
SKIP_TITLES = {
    "classroom of the elite",  # Light novel, not manga first
}

# Title overrides for MangaDex search (some anime titles don't match manga titles)
TITLE_OVERRIDES = {
    "jujutsu kaisen season 3 the culling game": "Jujutsu Kaisen",
    "jujutsu kaisen": "Jujutsu Kaisen",
    "frieren beyond journey s end": "Sousou no Frieren",
    "frieren": "Sousou no Frieren",
    "hell s paradise season 2": "Jigokuraku",
    "hell s paradise": "Jigokuraku",
    "dorohedoro season 2": "Dorohedoro",
    "solo leveling": "Solo Leveling",
    "sentenced to be a hero": "Yuusha Shikkaku",
    "attack on titan": "Shingeki no Kyojin",
    "one piece": "One Piece",
    "vinland saga": "Vinland Saga",
    "berserk": "Berserk",
    "chainsaw man": "Chainsaw Man",
    "oshi no ko": "Oshi no Ko",
    "monster": "Monster",
    "vagabond": "Vagabond",
    "death note": "Death Note",
    "code geass": "Code Geass",
}


def _slugify(title: str) -> str:
    """Convert title to a safe directory name."""
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    return slug[:50] or "manga"


def _search_with_fallback(title: str) -> dict | None:
    """Try the override map first, then the original title."""
    key = re.sub(r"[^a-z0-9\s]+", "", title.lower()).strip()

    # Check overrides
    override = TITLE_OVERRIDES.get(key)
    if override:
        log.info(f"  Using override: '{title}' → '{override}'")
        result = search_manga(override)
        if result:
            return result

    # Try original
    return search_manga(title)


def download_manga_by_title(
    title: str,
    pages: int = 12,
    chapters_to_sample: int = 3,
    lang: str = "en",
    force: bool = False,
) -> list[str]:
    """
    Download manga pages for a specific title.

    Strategy:
    - Sample N chapters spread across the series (early, middle, late)
    - Download a few pages from each for variety

    Args:
        title: manga title to search
        pages: total pages to download across all chapters
        chapters_to_sample: how many chapters to sample from
        lang: language code (en, es)
        force: re-download even if cache exists

    Returns list of local image paths.
    """
    slug = _slugify(title)
    out_dir = OUTPUT_BASE / slug

    # Check cache
    if not force and out_dir.exists():
        existing = sorted(str(p) for p in out_dir.glob("*.[jp][pn]g"))
        if len(existing) >= pages // 2:
            log.info(f"  Cache hit: {title} ({len(existing)} pages) at {out_dir}")
            return existing[:pages]

    if _slugify(title) in SKIP_TITLES:
        log.info(f"  Skipping (not manga): {title}")
        return []

    # Search
    log.info(f"  Searching MangaDex for: {title}")
    manga = _search_with_fallback(title)
    if not manga:
        log.warning(f"  Not found on MangaDex: {title}")
        return []

    log.info(f"  Found: {manga['title']} ({manga['id']})")

    # Get chapter list — try multiple languages
    out_dir.mkdir(parents=True, exist_ok=True)
    chapters = []
    for try_lang in [lang, "en", "es", "es-la", "pt-br"]:
        chapters = get_chapters(manga["id"], lang=try_lang, limit=100, order="asc")
        if chapters:
            log.info(f"  Got {len(chapters)} chapters in {try_lang}")
            break

    if not chapters:
        log.warning(f"  No chapters found for: {title} (tried en/es/es-la/pt-br)")
        return []

    log.info(f"  Got {len(chapters)} chapters")

    # Sample chapters across the series (early, middle, late)
    if len(chapters) >= chapters_to_sample:
        step = len(chapters) // chapters_to_sample
        sample_chapters = [chapters[i * step] for i in range(chapters_to_sample)]
    else:
        sample_chapters = chapters

    # Download pages from each sampled chapter
    all_pages = []
    pages_per_chapter = max(2, pages // len(sample_chapters))

    for i, ch in enumerate(sample_chapters):
        try:
            ch_pages = download_chapter_pages(
                ch["id"],
                output_dir=str(out_dir),
                max_pages=pages_per_chapter,
            )
            all_pages.extend(ch_pages)
            log.info(f"    Chapter {ch.get('chapter', '?')}: {len(ch_pages)} pages")
        except Exception as e:
            log.warning(f"    Chapter failed: {e}")

    return all_pages[:pages]


def download_trending_manga(
    top_n: int = 5,
    pages_per_manga: int = 12,
    use_cache: bool = True,
) -> dict[str, list[str]]:
    """
    Download manga pages for the current trending anime.

    Returns: {anime_title: [page_paths]}
    """
    from common.trending_anime import get_trending_titles

    trending = get_trending_titles(top_n=top_n, use_cache=use_cache)

    results = {}
    for item in trending:
        title = item.get("title", "")
        if not title:
            continue

        log.info(f"\n── {title} ──")
        pages = download_manga_by_title(
            title=title,
            pages=pages_per_manga,
        )
        if pages:
            results[title] = pages
            log.info(f"  ✓ {len(pages)} pages saved")
        else:
            log.info(f"  ✗ skipped")

    log.info(f"\n=== Summary: {len(results)}/{len(trending)} series downloaded ===")
    return results


def get_available_series() -> dict[str, int]:
    """Return currently downloaded manga series and their page counts."""
    if not OUTPUT_BASE.exists():
        return {}

    available = {}
    for series_dir in OUTPUT_BASE.iterdir():
        if series_dir.is_dir():
            count = len(list(series_dir.glob("*.[jp][pn]g")))
            if count > 0:
                available[series_dir.name] = count

    return dict(sorted(available.items(), key=lambda x: -x[1]))


def get_pages_for_series(slug_or_title: str, max_pages: int = 20) -> list[str]:
    """Get local manga pages for a series (for use by panel_matcher)."""
    slug = _slugify(slug_or_title)
    series_dir = OUTPUT_BASE / slug

    if not series_dir.exists():
        return []

    pages = sorted(str(p) for p in series_dir.glob("*.[jp][pn]g"))
    return pages[:max_pages]
