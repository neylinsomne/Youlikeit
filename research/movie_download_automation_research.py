"""
=============================================================================
MOVIE/SERIES DOWNLOAD AUTOMATION - RESEARCH & IMPLEMENTATION GUIDE
=============================================================================
For: YouTube Shorts automation pipeline (clip extraction from specific timestamps)
Date: 2026-03-19

TABLE OF CONTENTS:
  1. OPTION COMPARISON MATRIX
  2. RECOMMENDED ARCHITECTURE
  3. OPTION A: Radarr/Sonarr + qBittorrent (Full *arr Stack)
  4. OPTION B: Torrentio + Real-Debrid (Fastest, No Seeding)
  5. OPTION C: Direct Torrent Search + qBittorrent (Lightweight)
  6. HELPER: TMDB ID -> IMDB ID Conversion
  7. HELPER: aria2 as Download Manager
  8. LEGAL CONSIDERATIONS
=============================================================================
"""

# =============================================================================
# 1. OPTION COMPARISON MATRIX
# =============================================================================
"""
┌──────────────────────────┬───────────┬───────────┬──────────┬──────────┬───────────┬───────────────┐
│ Solution                 │ Python API│ Automated │ Free/Self│ TMDB     │ Docker    │ Complexity    │
│                          │           │           │ Hosted   │ Matching │           │               │
├──────────────────────────┼───────────┼───────────┼──────────┼──────────┼───────────┼───────────────┤
│ Radarr + qBittorrent     │ arrapi    │ YES ★★★   │ YES      │ Native   │ YES       │ Medium        │
│ + Prowlarr               │ + qbit-api│           │          │ TMDB ID  │           │ (3 services)  │
├──────────────────────────┼───────────┼───────────┼──────────┼──────────┼───────────┼───────────────┤
│ Torrentio + Real-Debrid  │ requests  │ YES ★★★   │ ~$4/mo   │ IMDB ID  │ N/A       │ Low           │
│ (no seeding, instant)    │ (REST)    │           │ (RD sub) │ (convert)│ (API only)│ (just HTTP)   │
├──────────────────────────┼───────────┼───────────┼──────────┼──────────┼───────────┼───────────────┤
│ Direct Search (1337x/    │ py1337x   │ YES ★★    │ YES      │ Manual   │ N/A       │ Low           │
│ YTS) + qBittorrent       │ + qbit-api│           │          │ matching │           │ (fragile)     │
├──────────────────────────┼───────────┼───────────┼──────────┼──────────┼───────────┼───────────────┤
│ Sonarr + qBittorrent     │ arrapi/   │ YES ★★★   │ YES      │ Native   │ YES       │ Medium        │
│ + Prowlarr (TV series)   │ sonarr-py │           │          │ TVDB ID  │           │ (3 services)  │
├──────────────────────────┼───────────┼───────────┼──────────┼──────────┼───────────┼───────────────┤
│ Real-Debrid + rdt-client │ requests  │ YES ★★★   │ ~$4/mo   │ Via Radarr│ YES      │ Medium        │
│ (emulates qBit for *arr) │           │           │ (RD sub) │          │           │ (best of both)│
├──────────────────────────┼───────────┼───────────┼──────────┼──────────┼───────────┼───────────────┤
│ yt-dlp                   │ yt-dlp    │ YES ★★    │ YES      │ N/A      │ N/A       │ Low           │
│ (streaming sites only)   │ (Python)  │           │          │          │           │ (limited src) │
├──────────────────────────┼───────────┼───────────┼──────────┼──────────┼───────────┼───────────────┤
│ aria2 + torrent search   │ aria2p    │ YES ★★    │ YES      │ Manual   │ YES       │ Low-Medium    │
│                          │           │           │          │ matching │           │               │
└──────────────────────────┴───────────┴───────────┴──────────┴──────────┴───────────┴───────────────┘

RECOMMENDATION RANKING:
  ★★★ #1: Torrentio + Real-Debrid  -- Fastest, simplest, instant cached downloads
  ★★★ #2: Radarr + Prowlarr + qBittorrent -- Most robust, best TMDB matching
  ★★  #3: Direct 1337x search + qBittorrent -- Free, lightweight, but fragile
"""


# =============================================================================
# 2. RECOMMENDED ARCHITECTURE (Best overall approach)
# =============================================================================
"""
ARCHITECTURE: Torrentio + Real-Debrid + aria2/requests for download

    TMDB ID ──► TMDB API ──► IMDB ID ──► Torrentio API ──► magnet hashes
                                              │
                                              ▼
                                     Real-Debrid API
                                     (check cache → add → get link)
                                              │
                                              ▼
                                     Direct HTTP download
                                     (aria2 or requests)
                                              │
                                              ▼
                                     Local file → FFmpeg clip extraction

WHY THIS APPROACH:
  - No seeding required (Real-Debrid handles that)
  - Instant downloads for cached torrents (most popular movies are cached)
  - No need to run qBittorrent, Radarr, or Prowlarr
  - Simple HTTP API calls only
  - Works headlessly
  - Fast download speeds (Real-Debrid premium servers)
"""


# =============================================================================
# 3. OPTION A: Radarr/Sonarr + Prowlarr + qBittorrent (Full *arr Stack)
# =============================================================================
"""
COMPONENTS:
  - Radarr: Movie management, monitors and triggers downloads
  - Sonarr: TV series management (same concept as Radarr)
  - Prowlarr: Indexer manager (searches torrent sites)
  - qBittorrent: Download client

DOCKER COMPOSE (save as docker-compose.yml):

version: "3"
services:
  radarr:
    image: lscr.io/linuxserver/radarr:latest
    container_name: radarr
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=UTC
    volumes:
      - ./config/radarr:/config
      - ./downloads:/downloads
      - ./movies:/movies
    ports:
      - 7878:7878
    restart: unless-stopped

  sonarr:
    image: lscr.io/linuxserver/sonarr:latest
    container_name: sonarr
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=UTC
    volumes:
      - ./config/sonarr:/config
      - ./downloads:/downloads
      - ./tv:/tv
    ports:
      - 8989:8989
    restart: unless-stopped

  prowlarr:
    image: lscr.io/linuxserver/prowlarr:latest
    container_name: prowlarr
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=UTC
    volumes:
      - ./config/prowlarr:/config
    ports:
      - 9696:9696
    restart: unless-stopped

  qbittorrent:
    image: lscr.io/linuxserver/qbittorrent:latest
    container_name: qbittorrent
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=UTC
      - WEBUI_PORT=8080
    volumes:
      - ./config/qbittorrent:/config
      - ./downloads:/downloads
    ports:
      - 8080:8080
      - 6881:6881
      - 6881:6881/udp
    restart: unless-stopped

INITIAL SETUP (one-time, via web UI):
  1. Prowlarr (localhost:9696): Add indexers (1337x, YTS, TPB, etc.)
  2. Prowlarr: Add Radarr/Sonarr as applications (auto-syncs indexers)
  3. Radarr (localhost:7878): Add qBittorrent as download client
  4. Radarr: Set quality profiles, root folder = /movies
  5. Sonarr (localhost:8989): Same setup for TV series
"""

# --- Python code for Radarr automation ---

def radarr_download_movie_example():
    """
    Add a movie to Radarr by TMDB ID and trigger automatic search+download.

    pip install arrapi
    """
    from arrapi import RadarrAPI

    # Connect to Radarr
    radarr = RadarrAPI(
        url="http://localhost:7878",
        apikey="your-radarr-api-key"  # Settings > General > API Key
    )

    # List available quality profiles and root folders (run once to see options)
    for profile in radarr.quality_profile():
        print(f"Quality Profile: {profile.name} (ID: {profile.id})")
    for folder in radarr.root_folder():
        print(f"Root Folder: {folder.path}")

    # Add a movie by TMDB ID with automatic search
    tmdb_id = 550  # Fight Club
    try:
        movie = radarr.get_movie(tmdb_id=tmdb_id)
        print(f"Movie already in Radarr: {movie.title}")
    except Exception:
        movie = radarr.add_movie(
            tmdb_id=tmdb_id,
            root_folder="/movies/",
            quality_profile="HD-1080p",
            monitor=True,
            search=True,  # <-- Triggers immediate search + download
            minimum_availability="released",
        )
        print(f"Added and searching: {movie.title}")

    # Add multiple movies at once
    tmdb_ids = [550, 680, 155, 238]  # Fight Club, Pulp Fiction, Dark Knight, Godfather
    added, existing, invalid = radarr.add_multiple_movies(
        tmdb_ids,
        root_folder="/movies/",
        quality_profile="HD-1080p",
        search=True,
    )
    print(f"Added: {len(added)}, Already existed: {len(existing)}, Invalid: {len(invalid)}")


def sonarr_download_series_example():
    """
    Add a TV series to Sonarr by TVDB ID and trigger automatic search+download.

    pip install arrapi
    """
    from arrapi import SonarrAPI

    sonarr = SonarrAPI(
        url="http://localhost:8989",
        apikey="your-sonarr-api-key"
    )

    # Add a series (e.g., Breaking Bad TVDB ID: 81189)
    try:
        series = sonarr.get_series(tvdb_id=81189)
        print(f"Series already in Sonarr: {series.title}")
    except Exception:
        series = sonarr.add_series(
            tvdb_id=81189,
            root_folder="/tv/",
            quality_profile="HD-1080p",
            language_profile="English",
            monitor="all",
            search=True,
            season_folder=True,
        )
        print(f"Added and searching: {series.title}")


def qbittorrent_monitor_example():
    """
    Monitor qBittorrent downloads and wait for completion.

    pip install qbittorrent-api
    """
    import qbittorrentapi
    import time

    qbt = qbittorrentapi.Client(
        host="localhost",
        port=8080,
        username="admin",
        password="adminadmin",
    )
    qbt.auth_log_in()

    # Monitor all active downloads
    while True:
        torrents = qbt.torrents_info(status_filter="downloading")
        if not torrents:
            print("All downloads complete!")
            break

        for t in torrents:
            progress = t.progress * 100
            speed_mb = t.dlspeed / (1024 * 1024)
            print(f"  {t.name}: {progress:.1f}% @ {speed_mb:.1f} MB/s")

        time.sleep(10)

    # List completed downloads with file paths
    for t in qbt.torrents_info(status_filter="completed"):
        print(f"Completed: {t.name}")
        print(f"  Path: {t.content_path}")


# =============================================================================
# 4. OPTION B: Torrentio + Real-Debrid (RECOMMENDED - Fastest, No Seeding)
# =============================================================================
"""
COMPONENTS:
  - Torrentio API: Free, public REST API for torrent stream discovery
  - Real-Debrid API: ~$4/month, cached torrent -> direct HTTP link
  - TMDB API: Convert TMDB ID -> IMDB ID (free, needs API key)

NO DOCKER NEEDED - just HTTP API calls.

COST: Real-Debrid Premium ~$4/month (or ~$16 for 180 days)
       TMDB API key: Free
"""

import requests
import re
import time
from typing import Optional
from dataclasses import dataclass


@dataclass
class TorrentStream:
    """Parsed torrent stream from Torrentio."""
    title: str
    info_hash: str
    size_gb: float
    seeders: int
    source: str
    quality: str


# --- Step 1: TMDB ID -> IMDB ID ---

def tmdb_to_imdb(tmdb_id: int, tmdb_api_key: str) -> str:
    """
    Convert a TMDB movie ID to an IMDB ID.

    pip install tmdbv3api   (or just use requests directly)

    Get a free API key at: https://www.themoviedb.org/settings/api
    """
    url = f"https://api.themoviedb.org/3/movie/{tmdb_id}?api_key={tmdb_api_key}"
    resp = requests.get(url)
    resp.raise_for_status()
    data = resp.json()
    imdb_id = data.get("imdb_id")
    if not imdb_id:
        raise ValueError(f"No IMDB ID found for TMDB ID {tmdb_id}")
    return imdb_id  # e.g., "tt0137523"


def tmdb_to_imdb_series(tmdb_series_id: int, tmdb_api_key: str) -> str:
    """Convert a TMDB TV series ID to an IMDB ID."""
    url = f"https://api.themoviedb.org/3/tv/{tmdb_series_id}/external_ids?api_key={tmdb_api_key}"
    resp = requests.get(url)
    resp.raise_for_status()
    data = resp.json()
    imdb_id = data.get("imdb_id")
    if not imdb_id:
        raise ValueError(f"No IMDB ID found for TMDB series ID {tmdb_series_id}")
    return imdb_id


# --- Step 2: Query Torrentio for magnet hashes ---

def search_torrentio_movie(imdb_id: str) -> list[TorrentStream]:
    """
    Query the Torrentio Stremio addon API for available torrent streams.

    Torrentio is a FREE public API - no auth needed.

    URL format:
      https://torrentio.strem.fun/{config}/stream/movie/{imdb_id}.json
      https://torrentio.strem.fun/{config}/stream/series/{imdb_id}:{season}:{episode}.json

    Config options (pipe-separated in URL path):
      sort=qualitysize          -- sort by quality then size
      qualityfilter=480p,scr,cam -- exclude low quality
      providers=yts,eztv,rarbg,1337x,thepiratebay,kickasstorrents,torrentgalaxy
    """
    config = "sort=qualitysize|qualityfilter=480p,scr,cam"
    url = f"https://torrentio.strem.fun/{config}/stream/movie/{imdb_id}.json"

    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    streams = []
    for stream in data.get("streams", []):
        title = stream.get("title", "")
        info_hash = stream.get("infoHash", "")

        if not info_hash:
            continue

        # Parse metadata from the formatted title string
        # Format: "Title\n💾 2.3 GB ⚙️ SourceName 👤 123"
        size_match = re.search(r'(\d+\.?\d*)\s*(GB|MB)', title)
        size_gb = 0.0
        if size_match:
            size_val = float(size_match.group(1))
            if size_match.group(2) == "MB":
                size_gb = size_val / 1024
            else:
                size_gb = size_val

        seeders_match = re.search(r'👤\s*(\d+)', title)
        seeders = int(seeders_match.group(1)) if seeders_match else 0

        source_match = re.search(r'⚙️\s*(\S+)', title)
        source = source_match.group(1) if source_match else "unknown"

        # Detect quality from title
        quality = "unknown"
        for q in ["2160p", "1080p", "720p", "480p"]:
            if q in title:
                quality = q
                break

        streams.append(TorrentStream(
            title=title.split('\n')[0].strip(),
            info_hash=info_hash,
            size_gb=size_gb,
            seeders=seeders,
            source=source,
            quality=quality,
        ))

    return streams


def search_torrentio_series(imdb_id: str, season: int, episode: int) -> list[TorrentStream]:
    """Query Torrentio for a specific TV episode."""
    config = "sort=qualitysize|qualityfilter=480p,scr,cam"
    url = f"https://torrentio.strem.fun/{config}/stream/series/{imdb_id}:{season}:{episode}.json"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    streams = []
    for stream in data.get("streams", []):
        info_hash = stream.get("infoHash", "")
        title = stream.get("title", "")
        if info_hash:
            streams.append(TorrentStream(
                title=title.split('\n')[0].strip(),
                info_hash=info_hash,
                size_gb=0,
                seeders=0,
                source="torrentio",
                quality="unknown",
            ))
    return streams


# --- Step 3: Real-Debrid - Check cache & get download link ---

class RealDebridClient:
    """
    Real-Debrid API client for converting torrent hashes to direct download links.

    Sign up: https://real-debrid.com/
    Get API token: https://real-debrid.com/apitoken
    Cost: ~$4/month or ~$16/180 days

    pip install requests  (that's all you need)
    """

    BASE_URL = "https://api.real-debrid.com/rest/1.0"

    def __init__(self, api_token: str):
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_token}"
        })

    def check_instant_availability(self, info_hashes: list[str]) -> dict:
        """
        Check if torrents are cached on Real-Debrid (instant download).
        Pass up to 100 hashes at once.

        Returns dict mapping hash -> list of available file groups.
        An empty list means NOT cached.
        """
        hash_path = "/".join(info_hashes)
        url = f"{self.BASE_URL}/torrents/instantAvailability/{hash_path}"
        resp = self.session.get(url)
        resp.raise_for_status()
        return resp.json()

    def add_magnet(self, info_hash: str) -> str:
        """
        Add a magnet link to Real-Debrid. Returns the torrent ID.
        """
        magnet = f"magnet:?xt=urn:btih:{info_hash}"
        resp = self.session.post(
            f"{self.BASE_URL}/torrents/addMagnet",
            data={"magnet": magnet}
        )
        resp.raise_for_status()
        return resp.json()["id"]

    def get_torrent_info(self, torrent_id: str) -> dict:
        """Get info about a torrent, including available files."""
        resp = self.session.get(f"{self.BASE_URL}/torrents/info/{torrent_id}")
        resp.raise_for_status()
        return resp.json()

    def select_files(self, torrent_id: str, file_ids: str = "all"):
        """
        Select which files to download from the torrent.
        file_ids: comma-separated file IDs, or "all"
        """
        resp = self.session.post(
            f"{self.BASE_URL}/torrents/selectFiles/{torrent_id}",
            data={"files": file_ids}
        )
        resp.raise_for_status()

    def wait_for_download_link(self, torrent_id: str, timeout: int = 120) -> list[str]:
        """
        Wait for Real-Debrid to process the torrent and return download links.
        For cached torrents, this is nearly instant.
        """
        start = time.time()
        while time.time() - start < timeout:
            info = self.get_torrent_info(torrent_id)
            status = info.get("status")

            if status == "downloaded":
                return info.get("links", [])
            elif status in ("magnet_error", "error", "virus", "dead"):
                raise Exception(f"Torrent failed with status: {status}")

            time.sleep(2)

        raise TimeoutError(f"Torrent not ready within {timeout}s")

    def unrestrict_link(self, link: str) -> str:
        """
        Convert a Real-Debrid hoster link to a direct download URL.
        This is the final step - returns a direct HTTP link you can download.
        """
        resp = self.session.post(
            f"{self.BASE_URL}/unrestrict/link",
            data={"link": link}
        )
        resp.raise_for_status()
        data = resp.json()
        return data["download"]


# --- Full Pipeline: TMDB ID -> Downloaded File ---

def download_movie_pipeline(
    tmdb_id: int,
    tmdb_api_key: str,
    rd_api_token: str,
    output_dir: str = "./downloads",
    prefer_quality: str = "1080p",
    max_size_gb: float = 5.0,
) -> str:
    """
    COMPLETE PIPELINE: Given a TMDB movie ID, automatically find and download the movie file.

    Returns the path to the downloaded file.

    Requirements:
        pip install requests

    Args:
        tmdb_id: The Movie Database ID (e.g., 550 for Fight Club)
        tmdb_api_key: Free API key from themoviedb.org
        rd_api_token: Real-Debrid API token (~$4/month)
        output_dir: Where to save the downloaded file
        prefer_quality: Preferred quality (2160p, 1080p, 720p)
        max_size_gb: Maximum file size to download
    """
    import os

    print(f"[1/6] Converting TMDB ID {tmdb_id} to IMDB ID...")
    imdb_id = tmdb_to_imdb(tmdb_id, tmdb_api_key)
    print(f"       IMDB ID: {imdb_id}")

    print(f"[2/6] Searching Torrentio for streams...")
    streams = search_torrentio_movie(imdb_id)
    print(f"       Found {len(streams)} streams")

    if not streams:
        raise Exception(f"No torrent streams found for {imdb_id}")

    # Filter and sort: prefer target quality, reasonable size, most seeders
    filtered = [s for s in streams if s.size_gb <= max_size_gb or s.size_gb == 0]
    quality_priority = {"2160p": 0, "1080p": 1, "720p": 2, "480p": 3, "unknown": 4}
    target_priority = quality_priority.get(prefer_quality, 1)

    filtered.sort(key=lambda s: (
        abs(quality_priority.get(s.quality, 4) - target_priority),
        -s.seeders,
    ))

    if not filtered:
        raise Exception("No streams match size/quality criteria")

    print(f"[3/6] Checking Real-Debrid cache for top candidates...")
    rd = RealDebridClient(rd_api_token)

    # Check top 10 candidates for cache availability
    top_hashes = [s.info_hash for s in filtered[:10]]
    availability = rd.check_instant_availability(top_hashes)

    # Find first cached stream
    selected_stream = None
    for stream in filtered[:10]:
        hash_lower = stream.info_hash.lower()
        cached_data = availability.get(hash_lower, {})
        # Real-Debrid returns dict with "rd" key containing cached file lists
        if cached_data and isinstance(cached_data, dict) and cached_data.get("rd"):
            selected_stream = stream
            print(f"       CACHED: {stream.title} ({stream.quality}, {stream.size_gb:.1f}GB)")
            break

    # Fallback: use best stream even if not cached (will take longer)
    if not selected_stream:
        selected_stream = filtered[0]
        print(f"       Not cached, using best available: {selected_stream.title}")

    print(f"[4/6] Adding to Real-Debrid...")
    torrent_id = rd.add_magnet(selected_stream.info_hash)

    # Select the largest video file (the actual movie)
    info = rd.get_torrent_info(torrent_id)
    video_extensions = {".mkv", ".mp4", ".avi", ".mov", ".wmv"}
    video_files = []
    for f in info.get("files", []):
        ext = os.path.splitext(f["path"])[1].lower()
        if ext in video_extensions:
            video_files.append(f)

    if video_files:
        # Select only the largest video file
        largest = max(video_files, key=lambda f: f["bytes"])
        rd.select_files(torrent_id, str(largest["id"]))
        print(f"       Selected: {os.path.basename(largest['path'])}")
    else:
        rd.select_files(torrent_id, "all")

    print(f"[5/6] Waiting for Real-Debrid to process...")
    links = rd.wait_for_download_link(torrent_id)

    if not links:
        raise Exception("No download links returned")

    # Unrestrict the first link to get direct download URL
    download_url = rd.unrestrict_link(links[0])
    print(f"       Direct download URL ready")

    print(f"[6/6] Downloading file...")
    os.makedirs(output_dir, exist_ok=True)

    # Stream download with progress
    resp = requests.get(download_url, stream=True)
    resp.raise_for_status()

    # Get filename from Content-Disposition or URL
    cd = resp.headers.get("Content-Disposition", "")
    if "filename=" in cd:
        filename = re.findall('filename="?([^"]+)"?', cd)[0]
    else:
        filename = download_url.split("/")[-1].split("?")[0]

    filepath = os.path.join(output_dir, filename)
    total = int(resp.headers.get("content-length", 0))

    downloaded = 0
    with open(filepath, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192 * 1024):  # 8MB chunks
            f.write(chunk)
            downloaded += len(chunk)
            if total:
                pct = (downloaded / total) * 100
                mb = downloaded / (1024 * 1024)
                print(f"\r       {pct:.1f}% ({mb:.0f} MB)", end="", flush=True)

    print(f"\n       Saved to: {filepath}")
    return filepath


# =============================================================================
# 5. OPTION C: Direct Torrent Search + qBittorrent (Free, Lightweight)
# =============================================================================
"""
COMPONENTS:
  - py1337x: Python scraper for 1337x torrent site
  - Torrent-Api-py: Multi-site torrent search API (self-hosted)
  - qbittorrent-api: Python client for qBittorrent

NO EXTERNAL SERVICES NEEDED. Fully free and self-hosted.
Downside: No automatic TMDB matching, title search can be imprecise.
"""

def direct_search_and_download(
    movie_title: str,
    year: int,
    qbt_host: str = "localhost",
    qbt_port: int = 8080,
    qbt_user: str = "admin",
    qbt_pass: str = "adminadmin",
    save_path: str = "/downloads/movies/",
):
    """
    Search 1337x for a movie and add the best result to qBittorrent.

    pip install 1337x qbittorrent-api
    """
    import py1337x
    import qbittorrentapi

    # Search for the movie on 1337x
    torrents_api = py1337x.Py1337x()
    query = f"{movie_title} {year} 1080p"

    print(f"Searching 1337x for: {query}")
    results = torrents_api.search(
        query,
        category=py1337x.category.MOVIES,
        sort_by=py1337x.sort.SEEDERS,
    )

    if not results or not results.items:
        raise Exception(f"No results found for: {query}")

    # Pick the top result (most seeders)
    best = results.items[0]
    print(f"Best result: {best.name} (Seeders: {best.seeders})")

    # Get the magnet link
    info = torrents_api.info(torrent_id=best.torrent_id)
    magnet = info.magnetLink  # or info.to_dict()["magnetLink"]
    print(f"Magnet link retrieved")

    # Add to qBittorrent
    qbt = qbittorrentapi.Client(
        host=qbt_host,
        port=qbt_port,
        username=qbt_user,
        password=qbt_pass,
    )
    qbt.auth_log_in()

    result = qbt.torrents_add(
        urls=magnet,
        save_path=save_path,
        category="movies",
    )

    if result == "Ok.":
        print("Torrent added to qBittorrent successfully!")
    else:
        print(f"Failed to add torrent: {result}")


def torrent_api_py_search(query: str, site: str = "1337x") -> list[dict]:
    """
    Search using the self-hosted Torrent-Api-py service.

    Setup:
        git clone https://github.com/Ryuk-me/Torrent-Api-py
        cd Torrent-Api-py
        docker-compose up -d

    Or:
        pip install -r requirements.txt
        python main.py  # Runs on http://localhost:8009

    Supports: 1337x, Piratebay, Nyaasi, Torlock, Torrent Galaxy,
              Kickass, Bitsearch, MagnetDL, YTS, Limetorrent,
              TorrentFunk, Glodls, TorrentProject, YourBittorrent
    """
    base_url = "http://localhost:8009"

    # Search a specific site
    resp = requests.get(
        f"{base_url}/api/v1/search",
        params={"site": site, "query": query, "limit": 10}
    )
    resp.raise_for_status()
    return resp.json().get("data", [])


# =============================================================================
# 6. HELPER: yt-dlp (for streaming sites, NOT torrents)
# =============================================================================
"""
yt-dlp can download from 1000+ streaming sites but CANNOT download from:
  - Netflix, Disney+, Amazon Prime, HBO Max (DRM protected)
  - Most paid streaming services

It CAN download from:
  - YouTube, Vimeo, Dailymotion
  - Twitch, TikTok, Twitter, Instagram, Reddit
  - Many regional and free streaming sites

VERDICT: Not suitable for downloading copyrighted movies/series.
         Useful only if your source content is on YouTube/free platforms.
"""

def ytdlp_download_example():
    """
    pip install yt-dlp
    """
    import yt_dlp

    # Download a video with best quality
    ydl_opts = {
        'format': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]',
        'outtmpl': './downloads/%(title)s.%(ext)s',
        'merge_output_format': 'mp4',
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download(['https://www.youtube.com/watch?v=VIDEO_ID'])


# =============================================================================
# 7. HELPER: aria2 as Download Manager (alternative to requests for large files)
# =============================================================================
"""
aria2 is a lightweight multi-protocol download utility.
Advantages over plain requests:
  - Multi-connection download (much faster)
  - Resume interrupted downloads
  - RPC interface for monitoring
  - Supports HTTP, FTP, BitTorrent, Metalink

Start aria2c daemon:
    aria2c --enable-rpc --rpc-listen-all=true --rpc-allow-origin-all --max-connection-per-server=16

Docker:
    docker run -d --name aria2 -p 6800:6800 -v ./downloads:/downloads p3terx/aria2-pro
"""

def aria2_download_example():
    """
    Use aria2 for faster downloads with multi-connection support.

    pip install aria2p
    """
    import aria2p

    # Connect to aria2c RPC
    aria2 = aria2p.API(
        aria2p.Client(
            host="http://localhost",
            port=6800,
            secret=""  # RPC secret if configured
        )
    )

    # Add a direct HTTP download (e.g., from Real-Debrid unrestricted link)
    download = aria2.add_uris(
        ["https://example.com/movie-file.mkv"],
        options={
            "dir": "/downloads/movies/",
            "max-connection-per-server": "16",
            "split": "16",
        }
    )
    print(f"Download started: {download.name}")
    print(f"GID: {download.gid}")

    # Monitor progress
    while not download.is_complete:
        download = aria2.get_download(download.gid)
        if download.total_length > 0:
            pct = download.completed_length / download.total_length * 100
            speed_mb = download.download_speed / (1024 * 1024)
            print(f"\r  {pct:.1f}% @ {speed_mb:.1f} MB/s", end="")
        time.sleep(2)

    print(f"\nCompleted: {download.name}")
    return download.files[0].path


# =============================================================================
# BONUS: rdt-client (Real-Debrid Client that emulates qBittorrent for *arr stack)
# =============================================================================
"""
rdt-client is the BRIDGE between the *arr stack and Real-Debrid.
It emulates the qBittorrent API, so Radarr/Sonarr think they're talking to qBittorrent,
but downloads actually go through Real-Debrid.

BEST OF BOTH WORLDS:
  - Radarr handles TMDB matching, quality profiles, organization
  - Real-Debrid handles fast cached downloads (no seeding)

Docker setup:
    docker run -d \\
      --name rdtclient \\
      -p 6500:6500 \\
      -v ./config/rdt:/data/db \\
      -v ./downloads:/data/downloads \\
      rogerfar/rdtclient:latest

Then in Radarr/Sonarr:
  - Add Download Client > qBittorrent
  - Host: rdtclient container IP
  - Port: 6500
  - Username/Password: your rdt-client credentials
  - Category: radarr (or sonarr)

rdt-client also supports: AllDebrid, Premiumize, TorBox, DebridLink
"""


# =============================================================================
# 8. LEGAL CONSIDERATIONS
# =============================================================================
"""
IMPORTANT LEGAL DISCLAIMER:

1. TORRENTING ITSELF IS LEGAL
   - BitTorrent is a protocol, not inherently illegal
   - Many legitimate uses (Linux ISOs, open-source software, public domain films)

2. DOWNLOADING COPYRIGHTED CONTENT WITHOUT AUTHORIZATION IS ILLEGAL
   - In most countries, downloading copyrighted movies/series without a license
     constitutes copyright infringement
   - This applies regardless of whether it's for "personal use" or "fair use"
   - Fair use is evaluated case-by-case and is NOT a blanket defense

3. CONSEQUENCES
   - ISPs can detect torrent traffic and send warning letters
   - Copyright holders use sophisticated tracking to identify downloaders by IP
   - Settlement demands typically range from $2,000 to $10,000+
   - Real-Debrid/debrid services reduce exposure (no seeding/uploading)
     but downloading still constitutes infringement

4. FOR VIDEO EDITING / YOUTUBE SHORTS
   - Creating derivative works (clips, edits) from copyrighted material
     may fall under fair use IF it is transformative, but this is NOT guaranteed
   - YouTube's Content ID system will likely flag clips from popular movies
   - Even short clips can trigger copyright strikes
   - Commercial use (monetized YouTube channel) weakens fair use arguments

5. LEGAL ALTERNATIVES FOR VIDEO EDITING
   - License clips through stock footage services
   - Use public domain films (pre-1928 in the US)
   - Contact studios/distributors for clip licensing
   - Use films under Creative Commons licenses
   - Some studios provide press kits with approved clips

6. RISK MITIGATION (NOT LEGAL ADVICE)
   - Use a VPN to mask IP address
   - Debrid services (Real-Debrid) download on their servers, reducing exposure
   - Avoid seeding/uploading (debrid services handle this)
   - Keep downloads for personal reference only
   - Consult a lawyer for your specific use case

THIS CODE IS PROVIDED FOR EDUCATIONAL AND RESEARCH PURPOSES ONLY.
THE AUTHOR DOES NOT CONDONE OR ENCOURAGE COPYRIGHT INFRINGEMENT.
"""


# =============================================================================
# QUICK START - Copy-paste ready pipeline
# =============================================================================

if __name__ == "__main__":
    """
    QUICK START GUIDE:

    1. Get a free TMDB API key:
       https://www.themoviedb.org/settings/api

    2. Get a Real-Debrid account + API token (~$4/month):
       https://real-debrid.com/apitoken

    3. Install dependencies:
       pip install requests

    4. Run this script with your credentials:
    """

    # --- Configuration ---
    TMDB_API_KEY = "your-tmdb-api-key-here"
    RD_API_TOKEN = "your-real-debrid-token-here"

    # --- Example: Download Fight Club ---
    # filepath = download_movie_pipeline(
    #     tmdb_id=550,              # Fight Club
    #     tmdb_api_key=TMDB_API_KEY,
    #     rd_api_token=RD_API_TOKEN,
    #     output_dir="./downloads",
    #     prefer_quality="1080p",
    #     max_size_gb=5.0,
    # )
    # print(f"Movie saved to: {filepath}")

    # --- Example: Quick test of Torrentio API (no auth needed) ---
    print("Testing Torrentio API (no auth required)...")
    test_streams = search_torrentio_movie("tt0137523")  # Fight Club
    for s in test_streams[:5]:
        print(f"  [{s.quality}] {s.title} | {s.size_gb:.1f}GB | Seeds: {s.seeders} | {s.source}")
