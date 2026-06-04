"""
ex05 - Descargar subtitulos (.srt) para peliculas descubiertas.

Flujo:
  1. Lee peliculas sin subtitulos de la BD
  2. Intenta OpenSubtitles API (20 descargas/dia gratis)
  3. Fallback: SubDL API (20 descargas/dia gratis)
  4. Fallback: Whisper (local GPU, sin limite, genera desde audio)
  5. Guarda el .srt en data/raw/srt/ y registra en BD

Whisper elimina el cuello de botella de 20 descargas/dia:
  - Descarga el audio del trailer/clip con yt-dlp
  - Whisper transcribe con timestamps exactos
  - Genera .srt directamente, sin API externa

Uso:
  python main.py ex05
  python main.py ex05 --max-downloads 5
"""

import os
import re
from pathlib import Path

import requests

from core.config import Settings
from core.db import get_db, get_movies_without_subtitles, insert_subtitle
from utils.logger import build_logger


# ── OpenSubtitles REST API (free tier: 20 downloads/day) ─────────────


class OpenSubtitlesClient:
    BASE = "https://api.opensubtitles.com/api/v1"

    def __init__(self, api_key: str, username: str = "", password: str = ""):
        self.api_key = api_key
        self.token = None
        self.headers = {
            "Api-Key": api_key,
            "Content-Type": "application/json",
            "User-Agent": "YoutubeShortsAutomation v1.0",
        }
        if username and password:
            self._login(username, password)

    def _login(self, username: str, password: str) -> None:
        resp = requests.post(
            f"{self.BASE}/login",
            json={"username": username, "password": password},
            headers=self.headers,
            timeout=15,
        )
        if resp.status_code == 200:
            self.token = resp.json().get("token")
            self.headers["Authorization"] = f"Bearer {self.token}"

    def search(self, tmdb_id: int, language: str = "en") -> list[dict]:
        """Search subtitles by TMDB ID."""
        resp = requests.get(
            f"{self.BASE}/subtitles",
            params={
                "tmdb_id": tmdb_id,
                "languages": language,
                "order_by": "download_count",
                "order_direction": "desc",
            },
            headers=self.headers,
            timeout=15,
        )
        if resp.status_code != 200:
            return []
        return resp.json().get("data", [])

    def download(self, file_id: int) -> str | None:
        """Download a subtitle file. Returns the SRT content as string."""
        resp = requests.post(
            f"{self.BASE}/download",
            json={"file_id": file_id},
            headers=self.headers,
            timeout=15,
        )
        if resp.status_code != 200:
            return None

        download_link = resp.json().get("link")
        if not download_link:
            return None

        content_resp = requests.get(download_link, timeout=30)
        if content_resp.status_code == 200:
            return content_resp.text
        return None


# ── SubDL API (free alternative, 20 downloads/day) ───────────────────


class SubDLClient:
    BASE = "https://api.subdl.com/api/v1/subtitles"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def search_and_download(self, tmdb_id: int, language: str = "en") -> str | None:
        """Search and download first matching subtitle."""
        resp = requests.get(
            self.BASE,
            params={
                "api_key": self.api_key,
                "tmdb_id": tmdb_id,
                "languages": language,
                "subs_per_page": 5,
                "type": "movie",
            },
            timeout=15,
        )
        if resp.status_code != 200:
            return None

        subs = resp.json().get("subtitles", [])
        if not subs:
            return None

        # Get download URL from first result
        download_url = subs[0].get("url")
        if not download_url:
            return None

        # SubDL returns a zip, but for simplicity we handle the direct URL
        content_resp = requests.get(
            f"https://dl.subdl.com{download_url}",
            timeout=30,
        )
        if content_resp.status_code == 200:
            return content_resp.text
        return None


# ── SRT Parser (for validation) ──────────────────────────────────────


def validate_srt(content: str) -> bool:
    """Basic validation that content looks like an SRT file."""
    # SRT files have numbered blocks with timestamps like 00:01:23,456 --> 00:01:25,789
    pattern = r"\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}"
    matches = re.findall(pattern, content[:2000])
    return len(matches) >= 2


def save_srt(content: str, srt_dir: Path, movie_title: str, tmdb_id: int) -> Path:
    """Save SRT content to file."""
    # Sanitize filename
    safe_title = re.sub(r'[^\w\s\-]', '', movie_title).strip().replace(' ', '_')
    filename = f"{safe_title}_{tmdb_id}.srt"
    srt_path = srt_dir / filename
    srt_path.write_text(content, encoding="utf-8")
    return srt_path


# ── Whisper local transcription (unlimited, no API key) ──────────────


def _whisper_transcribe(title: str, tmdb_id: int, srt_dir: Path, log) -> str | None:
    """
    Download trailer audio via yt-dlp, transcribe with Whisper.

    Returns SRT content as string, or None if it fails.
    This is the unlimited fallback — no API key, no daily limit.
    """
    import subprocess
    import tempfile

    try:
        import whisper
    except ImportError:
        return None

    # 1. Search YouTube for the movie trailer
    search_query = f"{title} official trailer"
    audio_path = None

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_file = Path(tmpdir) / "audio.wav"

            # yt-dlp: download audio only, first result from search
            result = subprocess.run(
                [
                    "yt-dlp",
                    f"ytsearch1:{search_query}",
                    "--extract-audio",
                    "--audio-format", "wav",
                    "--audio-quality", "5",
                    "--max-downloads", "1",
                    "--no-playlist",
                    "--output", str(audio_file).replace(".wav", ".%(ext)s"),
                    "--quiet",
                ],
                capture_output=True, text=True, timeout=60,
            )

            # Find the downloaded file (yt-dlp may change extension)
            wav_files = list(Path(tmpdir).glob("audio.*"))
            if not wav_files:
                log.warning(f"  Whisper: no audio downloaded for '{title}'")
                return None

            audio_path = wav_files[0]

            # 2. Transcribe with Whisper
            model_size = os.getenv("WHISPER_MODEL", "base")
            model = whisper.load_model(model_size)
            result = whisper.transcribe(model, str(audio_path), language="en")

            # 3. Convert to SRT format
            segments = result.get("segments", [])
            if not segments:
                return None

            srt_lines = []
            for i, seg in enumerate(segments, 1):
                start = _seconds_to_srt_time(seg["start"])
                end = _seconds_to_srt_time(seg["end"])
                text = seg["text"].strip()
                srt_lines.append(f"{i}")
                srt_lines.append(f"{start} --> {end}")
                srt_lines.append(text)
                srt_lines.append("")

            return "\n".join(srt_lines)

    except subprocess.TimeoutExpired:
        log.warning(f"  Whisper: yt-dlp timeout for '{title}'")
        return None
    except Exception as e:
        log.warning(f"  Whisper: error for '{title}': {e}")
        return None


def _seconds_to_srt_time(seconds: float) -> str:
    """Convert seconds to SRT timestamp format: HH:MM:SS,mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ── Entry point ───────────────────────────────────────────────────────


def run(settings: Settings, max_downloads: int = 10) -> Path:
    log = build_logger("ex05", settings.output_dir / "logs" / "ex05.log")
    conn = get_db(settings.data_dir)

    srt_dir = settings.data_dir / "raw" / "srt"
    srt_dir.mkdir(parents=True, exist_ok=True)

    report_lines = ["ex05 - Download Subtitles", "=" * 40, ""]

    # Get movies that need subtitles (ranked by priority score)
    movies = get_movies_without_subtitles(conn)
    log.info(f"Found {len(movies)} movies without subtitles")

    # Show priority ranking so you know WHY each movie was chosen
    report_lines.append("Download priority ranking:")
    for i, m in enumerate(movies[:max_downloads]):
        quote_count = m["quote_count"] if "quote_count" in m.keys() else "?"
        priority = m["download_priority"] if "download_priority" in m.keys() else "?"
        log.info(f"  #{i+1} {m['title']} (quotes={quote_count}, score={priority})")
        report_lines.append(f"  #{i+1} {m['title']} (quotes={quote_count}, score={priority})")
    report_lines.append("")

    if not movies:
        report_lines.append("All movies already have subtitles downloaded.")
        report_path = settings.output_dir / "logs" / "ex05_subtitles_report.txt"
        report_path.write_text("\n".join(report_lines), encoding="utf-8")
        conn.close()
        return report_path

    # Initialize clients
    os_api_key = os.getenv("OPENSUBTITLES_API_KEY", "")
    os_username = os.getenv("OPENSUBTITLES_USERNAME", "")
    os_password = os.getenv("OPENSUBTITLES_PASSWORD", "")
    subdl_api_key = os.getenv("SUBDL_API_KEY", "")

    os_client = OpenSubtitlesClient(os_api_key, os_username, os_password) if os_api_key else None
    subdl_client = SubDLClient(subdl_api_key) if subdl_api_key else None

    # Check if Whisper is available as fallback
    whisper_available = False
    try:
        import whisper as _whisper_check
        whisper_available = True
    except ImportError:
        pass

    if not os_client and not subdl_client and not whisper_available:
        log.error("No subtitle source available. Set OPENSUBTITLES_API_KEY, SUBDL_API_KEY, or pip install openai-whisper")
        report_lines.append("ERROR: No subtitle source configured.")
        report_lines.append("Options (any one):")
        report_lines.append("  1. Set OPENSUBTITLES_API_KEY in .env (20/day free)")
        report_lines.append("  2. Set SUBDL_API_KEY in .env (20/day free)")
        report_lines.append("  3. pip install openai-whisper (unlimited, local GPU)")
        report_path = settings.output_dir / "logs" / "ex05_subtitles_report.txt"
        report_path.write_text("\n".join(report_lines), encoding="utf-8")
        conn.close()
        return report_path

    if not os_client and not subdl_client:
        log.info("No API keys configured. Using Whisper (local GPU) for all subtitles.")

    downloaded = 0
    failed = 0

    for movie in movies[:max_downloads]:
        title = movie["title"]
        tmdb_id = movie["tmdb_id"]
        movie_id = movie["id"]
        log.info(f"Downloading subtitles for: {title} (TMDB:{tmdb_id})")

        srt_content = None
        source = None

        # Try OpenSubtitles first
        if os_client:
            try:
                results = os_client.search(tmdb_id)
                if results:
                    # Get file_id from first result
                    files = results[0].get("attributes", {}).get("files", [])
                    if files:
                        file_id = files[0].get("file_id")
                        if file_id:
                            srt_content = os_client.download(file_id)
                            source = "opensubtitles"
                            log.info(f"  OpenSubtitles: downloaded")
            except Exception as e:
                log.warning(f"  OpenSubtitles failed: {e}")

        # Fallback to SubDL
        if not srt_content and subdl_client:
            try:
                srt_content = subdl_client.search_and_download(tmdb_id)
                if srt_content:
                    source = "subdl"
                    log.info(f"  SubDL: downloaded")
            except Exception as e:
                log.warning(f"  SubDL failed: {e}")

        # Fallback to Whisper: download trailer audio, transcribe locally
        if not srt_content and whisper_available:
            try:
                srt_content = _whisper_transcribe(title, tmdb_id, srt_dir, log)
                if srt_content:
                    source = "whisper"
                    log.info(f"  Whisper: transcribed from trailer")
            except Exception as e:
                log.warning(f"  Whisper failed: {e}")

        if srt_content and validate_srt(srt_content):
            srt_path = save_srt(srt_content, srt_dir, title, tmdb_id)
            insert_subtitle(
                conn,
                movie_id=movie_id,
                language="en",
                srt_path=str(srt_path),
                source=source,
            )
            downloaded += 1
            report_lines.append(f"  OK: {title} ({source})")
            log.info(f"  Saved: {srt_path}")
        else:
            failed += 1
            report_lines.append(f"  FAIL: {title} (no subtitles found)")
            log.warning(f"  No valid subtitles found for {title}")

    report_lines.insert(2, f"Downloaded: {downloaded} | Failed: {failed}")
    report_lines.append("")

    # Summary
    cur = conn.execute("SELECT COUNT(*) as cnt FROM subtitles")
    report_lines.append(f"Total subtitles in DB: {cur.fetchone()['cnt']}")

    report_path = settings.output_dir / "logs" / "ex05_subtitles_report.txt"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    log.info(f"Report saved to {report_path}")

    conn.close()
    return report_path
