"""
Subdivx.com client: the best source for Spanish subtitles (Latin America).

Unlike OpenSubtitles (20/day limit), Subdivx is free and has massive
coverage for novelas, series latinas, and dubbed content.

Usage:
    from integrations.subdivx_client import search_subtitles, download_subtitle

    results = search_subtitles("Betty la fea")
    srt_path = download_subtitle(results[0], output_dir="data/raw/srt")
"""

from __future__ import annotations

import io
import logging
import os
import re
import zipfile
from pathlib import Path

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://www.subdivx.com"
SEARCH_URL = f"{BASE_URL}/inc/ajax.php"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": BASE_URL,
}


def search_subtitles(query: str, max_results: int = 10) -> list[dict]:
    """
    Search Subdivx for Spanish subtitles.

    Returns list of results with download links.
    """
    try:
        # Subdivx uses a search page with results
        resp = requests.get(
            f"{BASE_URL}/inc/ajax.php",
            params={
                "tabla": "resultados",
                "buscar": query,
            },
            headers=HEADERS,
            timeout=15,
        )

        if resp.status_code != 200:
            # Fallback: direct search page scrape
            resp = requests.get(
                f"{BASE_URL}/index.php",
                params={"buscar": query, "acession": 1, "oxession": 1},
                headers=HEADERS,
                timeout=15,
            )

        if resp.status_code != 200:
            log.warning(f"Subdivx search failed: {resp.status_code}")
            return []

        return _parse_search_results(resp.text, max_results)

    except Exception as e:
        log.warning(f"Subdivx search error: {e}")
        return []


def _parse_search_results(html: str, max_results: int) -> list[dict]:
    """Parse Subdivx search results from HTML."""
    results = []

    # Pattern for subtitle entries
    # Subdivx has a structure with title, description, download link
    title_pattern = re.compile(
        r'<a[^>]*class="titulo_menu_izq"[^>]*href="([^"]*)"[^>]*>([^<]*)</a>',
        re.IGNORECASE,
    )
    desc_pattern = re.compile(
        r'<div[^>]*id="buscador_detalle_sub"[^>]*>(.*?)</div>',
        re.IGNORECASE | re.DOTALL,
    )
    download_pattern = re.compile(
        r'href="(https?://[^"]*subdivx[^"]*baession[^"]*)"',
        re.IGNORECASE,
    )

    # Simpler pattern — try matching download links and nearby text
    all_links = re.findall(r'href="([^"]*)"', html)
    all_text_blocks = re.findall(r'>([^<]{10,200})<', html)

    # Find download links
    download_links = [
        link for link in all_links
        if "baession" in link or "sub" in link.lower()
    ]

    # Also try direct download pattern
    direct_dl = re.findall(
        r'(https?://(?:www\.)?subdivx\.com/[^\s"\'<>]*(?:id=|sub/)\d+)',
        html,
    )
    download_links.extend(direct_dl)

    # Build results from what we found
    for i, dl_link in enumerate(download_links[:max_results]):
        title = all_text_blocks[i] if i < len(all_text_blocks) else f"Result {i+1}"
        results.append({
            "title": title.strip()[:200],
            "download_url": dl_link if dl_link.startswith("http") else f"{BASE_URL}/{dl_link.lstrip('/')}",
            "source": "subdivx",
            "lang": "es",
            "index": i,
        })

    # If no structured results, try a broader pattern
    if not results:
        # Look for any ZIP/RAR download links
        archive_links = re.findall(
            r'href="([^"]*(?:\.zip|\.rar|descargar|download)[^"]*)"',
            html,
            re.IGNORECASE,
        )
        for i, link in enumerate(archive_links[:max_results]):
            url = link if link.startswith("http") else f"{BASE_URL}/{link.lstrip('/')}"
            results.append({
                "title": f"Subtitle pack {i+1}",
                "download_url": url,
                "source": "subdivx",
                "lang": "es",
                "index": i,
            })

    log.info(f"Subdivx: found {len(results)} results for query")
    return results


def download_subtitle(
    result: dict,
    output_dir: str = "data/raw/srt",
    filename_prefix: str = "",
) -> str | None:
    """
    Download and extract subtitle file from Subdivx.

    Returns path to the .srt file, or None if failed.
    """
    url = result.get("download_url", "")
    if not url:
        return None

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        resp = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
        if resp.status_code != 200:
            log.warning(f"Subdivx download failed: {resp.status_code}")
            return None

        content_type = resp.headers.get("Content-Type", "").lower()

        # Handle ZIP files
        if "zip" in content_type or resp.content[:4] == b"PK\x03\x04":
            return _extract_srt_from_zip(resp.content, out_dir, filename_prefix)

        # Handle direct SRT content
        if "text" in content_type or resp.content[:20].decode("utf-8", errors="ignore").strip().isdigit():
            srt_name = f"{filename_prefix or 'subdivx'}_es.srt"
            srt_path = out_dir / srt_name
            srt_path.write_bytes(resp.content)
            log.info(f"Subdivx: saved {srt_path}")
            return str(srt_path)

        log.warning(f"Subdivx: unexpected content type: {content_type}")
        return None

    except Exception as e:
        log.warning(f"Subdivx download error: {e}")
        return None


def _extract_srt_from_zip(zip_bytes: bytes, output_dir: Path, prefix: str) -> str | None:
    """Extract .srt file from a ZIP archive."""
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            srt_files = [f for f in zf.namelist() if f.lower().endswith(".srt")]
            if not srt_files:
                # Try .sub or .txt
                srt_files = [f for f in zf.namelist()
                             if f.lower().endswith((".sub", ".txt")) and "readme" not in f.lower()]

            if not srt_files:
                log.warning("No subtitle file found in ZIP")
                return None

            # Take the largest SRT (most likely the full movie, not extras)
            srt_files.sort(key=lambda f: zf.getinfo(f).file_size, reverse=True)
            srt_name = srt_files[0]

            content = zf.read(srt_name)
            out_name = f"{prefix or 'subdivx'}_es.srt"
            out_path = output_dir / out_name
            out_path.write_bytes(content)

            log.info(f"Subdivx: extracted {srt_name} -> {out_path}")
            return str(out_path)

    except zipfile.BadZipFile:
        log.warning("Subdivx: downloaded file is not a valid ZIP")
        return None
    except Exception as e:
        log.warning(f"Subdivx: ZIP extraction error: {e}")
        return None


def search_and_download(
    query: str,
    output_dir: str = "data/raw/srt",
    filename_prefix: str = "",
) -> str | None:
    """Search + download first result in one call. Convenience function."""
    results = search_subtitles(query, max_results=3)
    if not results:
        return None

    for result in results:
        path = download_subtitle(result, output_dir, filename_prefix or query.replace(" ", "_"))
        if path:
            return path

    return None
