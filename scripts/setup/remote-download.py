"""
Remote movie download via SSH + qBittorrent on a remote machine.
Downloads torrents on the remote PC, then pulls the files via SCP/SFTP.

Usage:
    python scripts/remote-download.py --setup     # First time: install qBittorrent on remote
    python scripts/remote-download.py --download "Fight Club"  # Download a movie
    python scripts/remote-download.py --status    # Check download progress
    python scripts/remote-download.py --pull       # Pull completed downloads to local

Requires:
    - SSH access to remote machine (key-based auth recommended)
    - WireGuard or direct network access
    - Remote machine has internet (ISP that doesn't block torrents)
"""
import os
import sys
import json
import time
import subprocess
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# ── Config from .env ──────────────────────────────────────────
REMOTE_HOST = os.getenv("REMOTE_HOST", "")           # WireGuard IP
REMOTE_USER = os.getenv("REMOTE_USER", "")           # SSH user
REMOTE_PORT = int(os.getenv("REMOTE_SSH_PORT", "22"))
REMOTE_MOVIES_DIR = os.getenv("REMOTE_MOVIES_DIR", "/home/movies")
REMOTE_QBIT_PORT = int(os.getenv("REMOTE_QBIT_PORT", "8090"))
LOCAL_MOVIES_DIR = os.getenv("MOVIES_DIR", "E:/movies")
MAX_BANDWIDTH = os.getenv("REMOTE_MAX_BANDWIDTH", "5M")  # 5MB/s limit


def ssh_cmd(cmd: str, timeout: int = 30) -> str:
    """Execute command on remote machine via SSH."""
    full = ["ssh", "-o", "StrictHostKeyChecking=no",
            "-p", str(REMOTE_PORT),
            f"{REMOTE_USER}@{REMOTE_HOST}", cmd]
    result = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        log.error(f"SSH failed: {result.stderr[:200]}")
    return result.stdout.strip()


def setup_remote():
    """Install qBittorrent-nox on the remote machine (Linux)."""
    log.info(f"Setting up qBittorrent on {REMOTE_HOST}...")

    # Detect OS
    os_info = ssh_cmd("cat /etc/os-release 2>/dev/null || ver 2>/dev/null || echo unknown")

    if "ubuntu" in os_info.lower() or "debian" in os_info.lower():
        commands = [
            "sudo apt-get update -qq",
            "sudo apt-get install -y -qq qbittorrent-nox",
            f"mkdir -p {REMOTE_MOVIES_DIR}",
            # Start qBittorrent daemon
            f"nohup qbittorrent-nox --webui-port={REMOTE_QBIT_PORT} "
            f"--profile={REMOTE_MOVIES_DIR}/.qbt "
            f"> /dev/null 2>&1 &",
        ]
        for cmd in commands:
            log.info(f"  $ {cmd[:60]}...")
            ssh_cmd(cmd, timeout=120)

    elif "windows" in os_info.lower() or "Microsoft" in os_info:
        log.info("Windows remote detected. Install qBittorrent manually:")
        log.info(f"  1. Download qBittorrent from https://www.qbittorrent.org/")
        log.info(f"  2. Enable Web UI on port {REMOTE_QBIT_PORT}")
        log.info(f"  3. Set download dir to {REMOTE_MOVIES_DIR}")
        return

    # Configure qBittorrent
    time.sleep(3)
    _qbit_remote_configure()
    log.info("Setup complete!")


def _qbit_remote_configure():
    """Configure qBittorrent on the remote machine."""
    import requests
    base = f"http://{REMOTE_HOST}:{REMOTE_QBIT_PORT}"

    # Login
    resp = requests.post(f"{base}/api/v2/auth/login",
                         data={"username": "admin", "password": "adminadmin"}, timeout=10)
    if "Ok" not in resp.text:
        log.warning("Login failed — might need to set credentials manually")
        return

    cookies = resp.cookies

    # Set preferences
    prefs = {
        "save_path": REMOTE_MOVIES_DIR,
        "max_active_downloads": 3,
        "max_active_torrents": 5,
        "dl_limit": int(MAX_BANDWIDTH.replace("M", "")) * 1024 * 1024,  # bytes/s
        "encryption": 1,  # prefer encryption
        "anonymous_mode": True,
        "dht": True,
        "pex": True,
    }
    requests.post(f"{base}/api/v2/app/setPreferences",
                  data={"json": json.dumps(prefs)}, cookies=cookies, timeout=10)
    log.info("qBittorrent configured on remote")


def download_movie(title: str, year: int = 0):
    """Find torrent for a movie and add it to remote qBittorrent."""
    import requests

    # Get IMDB ID from TMDB
    tmdb_key = os.getenv("TMDB_API_KEY", "")
    if not tmdb_key:
        log.error("TMDB_API_KEY not set")
        return

    search = requests.get(f"https://api.themoviedb.org/3/search/movie",
                          params={"api_key": tmdb_key, "query": title, "year": year},
                          timeout=10).json()
    if not search.get("results"):
        log.error(f"Movie not found: {title}")
        return

    movie = search["results"][0]
    tmdb_id = movie["id"]
    log.info(f"Found: {movie['title']} ({movie.get('release_date', '?')[:4]})")

    # Get IMDB ID
    details = requests.get(f"https://api.themoviedb.org/3/movie/{tmdb_id}",
                           params={"api_key": tmdb_key}, timeout=10).json()
    imdb_id = details.get("imdb_id", "")
    if not imdb_id:
        log.error("No IMDB ID found")
        return

    # Get magnet from Torrentio
    resp = requests.get(f"https://torrentio.strem.fun/stream/movie/{imdb_id}.json", timeout=15)
    if resp.status_code != 200:
        log.error("Torrentio returned no results")
        return

    streams = resp.json().get("streams", [])
    # Filter for 720p/1080p, reasonable size
    good = [s for s in streams if "720p" in s.get("title", "").lower() or "1080p" in s.get("title", "").lower()]
    if not good:
        good = streams[:5]

    if not good:
        log.error("No suitable torrents found")
        return

    best = good[0]
    magnet = best.get("url", "") or best.get("infoHash", "")
    if "magnet:" not in magnet and best.get("infoHash"):
        magnet = f"magnet:?xt=urn:btih:{best['infoHash']}"

    log.info(f"Adding torrent: {best.get('title', 'unknown')[:60]}")

    # Add to remote qBittorrent
    base = f"http://{REMOTE_HOST}:{REMOTE_QBIT_PORT}"
    resp = requests.post(f"{base}/api/v2/auth/login",
                         data={"username": "admin", "password": "adminadmin"}, timeout=10)
    cookies = resp.cookies

    resp = requests.post(f"{base}/api/v2/torrents/add",
                         data={"urls": magnet, "savepath": REMOTE_MOVIES_DIR},
                         cookies=cookies, timeout=10)
    if resp.text == "Ok.":
        log.info(f"Torrent added to remote qBittorrent!")
    else:
        log.error(f"Failed to add torrent: {resp.text}")


def check_status():
    """Check download status on remote qBittorrent."""
    import requests
    base = f"http://{REMOTE_HOST}:{REMOTE_QBIT_PORT}"

    try:
        resp = requests.post(f"{base}/api/v2/auth/login",
                             data={"username": "admin", "password": "adminadmin"}, timeout=10)
        cookies = resp.cookies

        resp = requests.get(f"{base}/api/v2/torrents/info", cookies=cookies, timeout=10)
        torrents = resp.json()

        if not torrents:
            log.info("No active downloads")
            return

        for t in torrents:
            progress = t["progress"] * 100
            speed = t["dlspeed"] / 1024 / 1024
            name = t["name"][:50]
            state = t["state"]
            log.info(f"  {name:50s} {progress:5.1f}% | {speed:.1f} MB/s | {state}")

    except Exception as e:
        log.error(f"Cannot reach remote qBittorrent: {e}")


def pull_completed():
    """Pull completed downloads from remote to local via SCP."""
    import requests
    base = f"http://{REMOTE_HOST}:{REMOTE_QBIT_PORT}"

    try:
        resp = requests.post(f"{base}/api/v2/auth/login",
                             data={"username": "admin", "password": "adminadmin"}, timeout=10)
        cookies = resp.cookies

        resp = requests.get(f"{base}/api/v2/torrents/info", cookies=cookies, timeout=10)
        completed = [t for t in resp.json() if t["progress"] >= 1.0]

        if not completed:
            log.info("No completed downloads to pull")
            return

        Path(LOCAL_MOVIES_DIR).mkdir(parents=True, exist_ok=True)

        for t in completed:
            remote_path = t["content_path"]
            local_path = Path(LOCAL_MOVIES_DIR) / Path(remote_path).name

            if local_path.exists():
                log.info(f"  Already local: {local_path.name}")
                continue

            log.info(f"  Pulling: {Path(remote_path).name}...")
            result = subprocess.run([
                "scp", "-P", str(REMOTE_PORT),
                f"{REMOTE_USER}@{REMOTE_HOST}:{remote_path}",
                str(local_path)
            ], capture_output=True, text=True, timeout=3600)

            if result.returncode == 0:
                log.info(f"  Pulled: {local_path.name} ({local_path.stat().st_size // 1024 // 1024}MB)")

                # Optionally delete from remote after successful pull
                # ssh_cmd(f"rm -f '{remote_path}'")
            else:
                log.error(f"  SCP failed: {result.stderr[:200]}")

    except Exception as e:
        log.error(f"Pull failed: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python remote-download.py --setup")
        print('  python remote-download.py --download "Fight Club"')
        print("  python remote-download.py --status")
        print("  python remote-download.py --pull")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "--setup":
        setup_remote()
    elif cmd == "--download":
        title = sys.argv[2] if len(sys.argv) > 2 else ""
        year = int(sys.argv[3]) if len(sys.argv) > 3 else 0
        download_movie(title, year)
    elif cmd == "--status":
        check_status()
    elif cmd == "--pull":
        pull_completed()
