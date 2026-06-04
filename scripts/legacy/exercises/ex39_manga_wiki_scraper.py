"""ex39 - Scrape Fandom wikis for iconic manga panels and chapter references.

ETL Pattern:
  Extract:  Fandom Wiki API (free, no key) for chapter summaries + panel images
  Transform: Identify iconic moments, extract image URLs, match with quotes
  Load:     Download panel images + update manga_quotes with chapter/page refs

Sources (all free):
  - Fandom Wikia API (*.fandom.com/api.php) — chapter pages, images
  - Wiki pages have structured chapter summaries with iconic moment descriptions

Supported wikis:
  - onepiece.fandom.com
  - naruto.fandom.com
  - berserk.fandom.com
  - hunterxhunter.fandom.com
  - chainsawman.fandom.com
  - bleach.fandom.com
  - attackontitan.fandom.com
  - myheroacademia.fandom.com
  - jujutsukaisen.fandom.com
  - demonslayer.fandom.com
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from core.config import Settings
from core.db import get_db
from utils.http_client import api_get, download_file

log = logging.getLogger(__name__)

# Map series titles to their Fandom wiki subdomains
WIKI_MAP = {
    "one piece": "onepiece",
    "naruto": "naruto",
    "berserk": "berserk",
    "hunter x hunter": "hunterxhunter",
    "chainsaw man": "chainsawman",
    "bleach": "bleach",
    "attack on titan": "attackontitan",
    "my hero academia": "myheroacademia",
    "jujutsu kaisen": "jujutsukaisen",
    "demon slayer": "kimetsu-no-yaiba",
    "dragon ball": "dragonball",
    "death note": "deathnote",
    "fullmetal alchemist": "fma",
    "one-punch man": "onepunchman",
    "spy x family": "spy-x-family",
    "blue lock": "bluelock",
    "kingdom": "kingdom-manga",
    "tokyo ghoul": "tokyoghoul",
    "vinland saga": "vinlandsaga",
    "mob psycho 100": "mob-psycho-100",
}


def _wiki_api(subdomain: str, params: dict) -> dict | None:
    """Call Fandom Wiki API with automatic retry + rate limit."""
    url = f"https://{subdomain}.fandom.com/api.php"
    params.setdefault("format", "json")
    return api_get(url, params=params, service="fandom")


def _find_wiki_subdomain(series_title: str) -> str | None:
    """Find the Fandom wiki subdomain for a series."""
    title_lower = series_title.lower().strip()
    for key, subdomain in WIKI_MAP.items():
        if key in title_lower or title_lower in key:
            return subdomain
    # Try searching directly
    slug = re.sub(r"[^a-z0-9]", "", title_lower)
    return slug if slug else None


def _get_chapter_list(subdomain: str, limit: int = 50) -> list[dict]:
    """Get list of chapter pages from the wiki."""
    data = _wiki_api(subdomain, {
        "action": "query",
        "list": "categorymembers",
        "cmtitle": "Category:Chapters",
        "cmlimit": str(limit),
        "cmtype": "page",
    })
    if not data or "query" not in data:
        # Try alternative category names
        for cat in ["Category:Manga Chapters", "Category:Story Arcs", "Category:Episodes"]:
            data = _wiki_api(subdomain, {
                "action": "query",
                "list": "categorymembers",
                "cmtitle": cat,
                "cmlimit": str(limit),
                "cmtype": "page",
            })
            if data and "query" in data and data["query"].get("categorymembers"):
                break

    if not data or "query" not in data:
        return []

    return [
        {"page_id": m["pageid"], "title": m["title"]}
        for m in data["query"].get("categorymembers", [])
    ]


def _get_page_content(subdomain: str, page_title: str) -> str:
    """Get the text content of a wiki page."""
    data = _wiki_api(subdomain, {
        "action": "parse",
        "page": page_title,
        "prop": "wikitext",
    })
    if not data or "parse" not in data:
        return ""
    return data["parse"].get("wikitext", {}).get("*", "")


def _get_page_images(subdomain: str, page_title: str) -> list[dict]:
    """Get images from a wiki page."""
    data = _wiki_api(subdomain, {
        "action": "parse",
        "page": page_title,
        "prop": "images",
    })
    if not data or "parse" not in data:
        return []

    images = []
    for img_name in data["parse"].get("images", []):
        if any(ext in img_name.lower() for ext in [".jpg", ".png", ".webp"]):
            # Get actual image URL
            img_data = _wiki_api(subdomain, {
                "action": "query",
                "titles": f"File:{img_name}",
                "prop": "imageinfo",
                "iiprop": "url|size",
            })
            if img_data and "query" in img_data:
                for page in img_data["query"].get("pages", {}).values():
                    for ii in page.get("imageinfo", []):
                        images.append({
                            "name": img_name,
                            "url": ii.get("url", ""),
                            "width": ii.get("width", 0),
                            "height": ii.get("height", 0),
                        })
    return images


def _extract_iconic_moments(wikitext: str) -> list[str]:
    """Extract notable/iconic moment descriptions from wiki page text."""
    moments = []

    # Look for notable quotes in the wikitext
    quote_patterns = [
        r'"([^"]{20,200})"',  # Quoted text
        r"'''([^']{10,200})'''",  # Bold text (often important)
    ]
    for pattern in quote_patterns:
        for match in re.finditer(pattern, wikitext):
            text = match.group(1).strip()
            if len(text) > 15 and not text.startswith("http"):
                moments.append(text)

    return moments[:10]  # Cap at 10 per page


def _download_image(url: str, output_path: str) -> bool:
    """Download an image from URL with retry."""
    return download_file(url, output_path, service="fandom")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(
    settings: Settings,
    series_title: str = "",
    max_chapters: int = 10,
    download_images: bool = True,
) -> str:
    """Scrape Fandom wiki for iconic manga panels.

    Args:
        series_title: Manga/anime title to scrape
        max_chapters: Max chapters to scan
        download_images: Download panel images to data/manga_panels/
    """
    if not series_title:
        log.error("No series title. Use --series-title 'One Piece'")
        return ""

    data_dir = Path(settings.data_dir)
    conn = get_db(data_dir)

    subdomain = _find_wiki_subdomain(series_title)
    if not subdomain:
        log.error(f"No wiki found for: {series_title}")
        return ""

    log.info(f"Scraping {subdomain}.fandom.com for: {series_title}")

    # Get chapters
    chapters = _get_chapter_list(subdomain, max_chapters)
    log.info(f"Found {len(chapters)} chapter pages")

    if not chapters:
        # Try searching for the series page directly
        log.info("No chapters found, trying series main page")
        content = _get_page_content(subdomain, series_title)
        if content:
            chapters = [{"page_id": 0, "title": series_title}]

    panels_dir = data_dir / "manga_panels" / subdomain
    panels_dir.mkdir(parents=True, exist_ok=True)

    all_moments = []
    all_images = []

    for chapter in chapters[:max_chapters]:
        log.info(f"  Scanning: {chapter['title']}")

        # Get page content for iconic moments
        content = _get_page_content(subdomain, chapter["title"])
        moments = _extract_iconic_moments(content)
        for m in moments:
            all_moments.append({
                "chapter": chapter["title"],
                "text": m,
            })

        # Get images
        if download_images:
            images = _get_page_images(subdomain, chapter["title"])
            # Filter: manga panels tend to be taller than wide, >300px
            panel_images = [
                img for img in images
                if img.get("height", 0) > 300
                and img.get("url")
                and "icon" not in img["name"].lower()
                and "logo" not in img["name"].lower()
            ]

            for img in panel_images[:3]:  # Max 3 images per chapter
                img_path = panels_dir / img["name"].replace(":", "_")
                if not img_path.exists():
                    if _download_image(img["url"], str(img_path)):
                        log.info(f"    Downloaded: {img['name']}")
                        all_images.append({
                            "chapter": chapter["title"],
                            "path": str(img_path),
                            "url": img["url"],
                        })
                else:
                    all_images.append({
                        "chapter": chapter["title"],
                        "path": str(img_path),
                        "url": img["url"],
                    })

    # Try to match moments with existing manga_quotes
    matched = 0
    try:
        from rapidfuzz import fuzz
        cur = conn.execute(
            """SELECT mq.id, mq.text FROM manga_quotes mq
               JOIN manga_series ms ON mq.series_id = ms.id
               WHERE ms.title LIKE ?""",
            (f"%{series_title}%",),
        )
        quotes = cur.fetchall()
        for moment in all_moments:
            for q in quotes:
                score = fuzz.partial_ratio(moment["text"].lower(), q["text"].lower())
                if score >= 70:
                    moment["matched_quote_id"] = q["id"]
                    moment["match_score"] = score
                    matched += 1
                    break
    except Exception:
        pass

    # Report
    report_dir = Path(settings.output_dir) / "logs"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"ex39_wiki_{subdomain}_{datetime.now():%Y%m%d_%H%M%S}.txt"

    lines = [
        "ex39 - Fandom Wiki Scraper Report",
        "=" * 50,
        f"Series: {series_title}",
        f"Wiki: {subdomain}.fandom.com",
        f"Chapters scanned: {min(len(chapters), max_chapters)}",
        f"Iconic moments found: {len(all_moments)}",
        f"Panel images downloaded: {len(all_images)}",
        f"Matched to existing quotes: {matched}",
        "",
        "Iconic moments:",
    ]
    for m in all_moments[:20]:
        match_info = f" [MATCH {m['match_score']}%]" if "match_score" in m else ""
        lines.append(f"  [{m['chapter']}]{match_info} {m['text'][:80]}")

    if all_images:
        lines.extend(["", "Downloaded panels:"])
        for img in all_images[:10]:
            lines.append(f"  [{img['chapter']}] {Path(img['path']).name}")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    log.info(f"Report: {report_path}")
    log.info(f"Panels saved to: {panels_dir}")

    return str(report_path)
