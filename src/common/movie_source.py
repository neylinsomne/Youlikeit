"""
Movie source: descarga automática de películas para el pipeline.

Flujo 100% gratis:
  1. TMDB ID → IMDB ID (TMDB API, gratis)
  2. IMDB ID → Torrentio (público, gratis) → magnets
  3. Magnet → qBittorrent (Docker, gratis) → descarga a E:/movies/
  4. ex11 corta el clip exacto con FFmpeg + timestamps del .srt

qBittorrent corre en Docker con Web UI en http://localhost:8090
Las películas se guardan en MOVIES_DIR (default: E:/movies/).

Uso:
  from common.movie_source import download_movie, find_local_movie

  # Descarga la película (si no está ya)
  path = download_movie(tmdb_id=1084242, title="Zootopia 2")

  # Busca archivo local
  path = find_local_movie("Zootopia 2", year=2025)
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

import requests


# ---------------------------------------------------------------------------
# TMDB ID → IMDB ID
# ---------------------------------------------------------------------------

_IMDB_CACHE: dict[int, str] = {}


def _tmdb_to_imdb(tmdb_id: int) -> str | None:
    """Convert TMDB ID to IMDB ID."""
    if tmdb_id in _IMDB_CACHE:
        return _IMDB_CACHE[tmdb_id]

    api_key = os.getenv("TMDB_API_KEY", "")
    if not api_key:
        return None

    # Try external_ids endpoint first, then movie details
    for endpoint in [
        f"https://api.themoviedb.org/3/movie/{tmdb_id}/external_ids",
        f"https://api.themoviedb.org/3/movie/{tmdb_id}",
    ]:
        try:
            resp = requests.get(endpoint, params={"api_key": api_key}, timeout=10)
            if resp.status_code == 200:
                imdb_id = resp.json().get("imdb_id", "")
                if imdb_id:
                    _IMDB_CACHE[tmdb_id] = imdb_id
                    return imdb_id
        except Exception:
            pass
    return None


# ---------------------------------------------------------------------------
# Torrentio: find torrents by IMDB ID (free, public)
# ---------------------------------------------------------------------------

def _get_torrentio_magnets(imdb_id: str) -> list[dict]:
    """Get magnet links from Torrentio sorted by quality preference."""
    try:
        resp = requests.get(
            f"https://torrentio.strem.fun/stream/movie/{imdb_id}.json",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        if resp.status_code != 200:
            return []

        results = []
        for s in resp.json().get("streams", []):
            title = s.get("title", "")
            info_hash = s.get("infoHash", "")
            if not info_hash:
                continue

            # Parse quality
            quality = "unknown"
            for q in ["2160p", "1080p", "720p", "480p"]:
                if q in title:
                    quality = q
                    break

            # Parse size
            size_match = re.search(r"([\d.]+)\s*GB", title, re.IGNORECASE)
            size_gb = float(size_match.group(1)) if size_match else 0

            magnet = f"magnet:?xt=urn:btih:{info_hash}"

            # Add trackers for better connectivity
            trackers = [
                "udp://tracker.opentrackr.org:1337/announce",
                "udp://open.stealth.si:80/announce",
                "udp://tracker.openbittorrent.com:6969/announce",
            ]
            for t in trackers:
                magnet += f"&tr={t}"

            results.append({
                "magnet": magnet,
                "hash": info_hash,
                "title": title,
                "quality": quality,
                "size_gb": size_gb,
            })

        # Prefer 720p (good quality, fast download, ~1-2GB)
        quality_order = {"720p": 0, "1080p": 1, "480p": 2, "2160p": 3, "unknown": 4}
        results.sort(key=lambda x: (quality_order.get(x["quality"], 5), x["size_gb"]))
        return results

    except Exception:
        return []


# ---------------------------------------------------------------------------
# qBittorrent API (Docker container)
# ---------------------------------------------------------------------------

def _qbit_url() -> str:
    return os.getenv("QBIT_URL", "http://localhost:8090")


def _qbit_login() -> str | None:
    """Login to qBittorrent and return session cookie."""
    url = _qbit_url()
    username = os.getenv("QBIT_USER", "admin")
    password = os.getenv("QBIT_PASS", "adminadmin")

    try:
        resp = requests.post(
            f"{url}/api/v2/auth/login",
            data={"username": username, "password": password},
            timeout=10,
        )
        if resp.status_code == 200 and resp.text == "Ok.":
            return resp.cookies.get("SID", "")
    except Exception:
        pass
    return None


def _qbit_add_torrent(magnet: str, save_path: str = "", category: str = "movies") -> bool:
    """Add a magnet link to qBittorrent."""
    sid = _qbit_login()
    if sid is None:
        return False

    url = _qbit_url()
    data = {
        "urls": magnet,
        "category": category,
    }
    if save_path:
        data["savepath"] = save_path

    try:
        resp = requests.post(
            f"{url}/api/v2/torrents/add",
            data=data,
            cookies={"SID": sid},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception:
        return False


def _qbit_get_torrent_status(info_hash: str) -> dict | None:
    """Get torrent status from qBittorrent."""
    sid = _qbit_login()
    if sid is None:
        return None

    try:
        resp = requests.get(
            f"{_qbit_url()}/api/v2/torrents/info",
            params={"hashes": info_hash.lower()},
            cookies={"SID": sid},
            timeout=10,
        )
        if resp.status_code == 200:
            torrents = resp.json()
            if torrents:
                t = torrents[0]
                return {
                    "state": t.get("state", ""),
                    "progress": t.get("progress", 0),
                    "size": t.get("size", 0),
                    "dlspeed": t.get("dlspeed", 0),
                    "eta": t.get("eta", 0),
                    "save_path": t.get("save_path", ""),
                    "content_path": t.get("content_path", ""),
                    "name": t.get("name", ""),
                }
    except Exception:
        pass
    return None


def _qbit_is_available() -> bool:
    """Check if qBittorrent is running (try login, not just ping)."""
    return _qbit_login() is not None


# ---------------------------------------------------------------------------
# Local movie file search
# ---------------------------------------------------------------------------

def find_local_movie(title: str, year: int = 0) -> Path | None:
    """Search MOVIES_DIR for a movie file by title (fuzzy match)."""
    movies_dir = os.getenv("MOVIES_DIR", "")
    if not movies_dir:
        return None

    movies_path = Path(movies_dir)
    if not movies_path.exists():
        return None

    title_lower = title.lower().strip()
    title_clean = re.sub(r"[^a-z0-9\s]", "", title_lower).strip()
    title_words = set(title_clean.split())

    video_exts = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v"}
    best_match = None
    best_score = 0

    for video_file in movies_path.rglob("*"):
        if video_file.suffix.lower() not in video_exts:
            continue
        if not video_file.is_file():
            continue

        fname = video_file.stem.lower()
        fname_clean = re.sub(r"[^a-z0-9\s]", " ", fname).strip()
        fname_words = set(fname_clean.split())

        common = title_words & fname_words
        if not common:
            continue

        score = len(common) / max(len(title_words), 1)
        if year and str(year) in fname:
            score += 0.3
        if title_clean in fname_clean:
            score += 0.5

        if score > best_score:
            best_score = score
            best_match = video_file

    return best_match if best_match and best_score >= 0.5 else None


# ---------------------------------------------------------------------------
# Main: download movie
# ---------------------------------------------------------------------------

def download_movie(
    tmdb_id: int,
    title: str,
    year: int = 0,
    log=None,
    wait: bool = False,
    max_wait_min: int = 30,
) -> Path | None:
    """
    Ensure a movie is available locally.

    1. Check if already downloaded in MOVIES_DIR
    2. If not, find magnet via Torrentio and send to qBittorrent
    3. Optionally wait for download to complete

    Args:
        tmdb_id: TMDB movie ID
        title: Movie title
        year: Release year
        wait: If True, block until download completes
        max_wait_min: Max minutes to wait

    Returns:
        Path to the movie file, or None
    """
    # Already have it?
    local = find_local_movie(title, year=year)
    if local:
        if log:
            log.info("  Movie found locally: %s", local.name)
        return local

    # Need qBittorrent
    if not _qbit_is_available():
        if log:
            log.warning("  qBittorrent not available at %s. Run: docker compose up -d qbittorrent", _qbit_url())
        return None

    # Get IMDB ID
    imdb_id = _tmdb_to_imdb(tmdb_id)
    if not imdb_id:
        if log:
            log.warning("  No IMDB ID found for TMDB:%d (%s)", tmdb_id, title)
        return None

    if log:
        log.info("  Searching torrents for %s (%s)...", title, imdb_id)

    # Get magnets
    magnets = _get_torrentio_magnets(imdb_id)
    if not magnets:
        if log:
            log.warning("  No torrents found for %s", title)
        return None

    best = magnets[0]
    if log:
        log.info("  Found: %s (%s, %.1fGB). Adding to qBittorrent...",
                 best["quality"], best["hash"][:12], best["size_gb"])

    # Add to qBittorrent
    ok = _qbit_add_torrent(best["magnet"])
    if not ok:
        if log:
            log.error("  Failed to add torrent to qBittorrent")
        return None

    if log:
        log.info("  Torrent added. Download started.")
        log.info("  Monitor at: %s", _qbit_url())

    if not wait:
        if log:
            log.info("  Not waiting for download. Run ex11 again when movie is ready.")
        return None

    # Wait for download
    if log:
        log.info("  Waiting for download (max %d min)...", max_wait_min)

    deadline = time.time() + max_wait_min * 60
    last_progress = 0.0
    stall_count = 0
    max_stalls = 6  # 3 minutes with zero progress = stalled

    while time.time() < deadline:
        status = _qbit_get_torrent_status(best["hash"])
        if not status:
            time.sleep(10)
            continue

        progress = status["progress"]
        speed_mb = status["dlspeed"] / (1024 * 1024)
        eta_min = status["eta"] / 60 if status["eta"] > 0 else 0
        state = status.get("state", "")

        if progress >= 1.0:
            if log:
                log.info("  Download complete: %s", status.get("name", ""))
            local = find_local_movie(title, year=year)
            return local

        # Stall detection
        if progress == last_progress and speed_mb < 0.01:
            stall_count += 1
            if stall_count >= max_stalls:
                if log:
                    log.error("  Download stalled (%d checks with no progress). "
                              "State: %s. Check qBittorrent at %s",
                              stall_count, state, _qbit_url())
                return None
        else:
            stall_count = 0
        last_progress = progress

        if log and int(progress * 100) % 10 == 0:
            log.info("  Progress: %.0f%% (%.1f MB/s, ETA: %.0f min, state=%s)",
                     progress * 100, speed_mb, eta_min, state)

        time.sleep(30)

    if log:
        log.warning("  Download timeout after %d min", max_wait_min)
    return None
