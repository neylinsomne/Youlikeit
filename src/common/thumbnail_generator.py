"""
Auto-thumbnail generator for TikTok and YouTube.

Generates two formats from the same source material:
- TikTok:  1080x1920 (9:16 vertical)
- YouTube: 1280x720  (16:9 horizontal)

Sources:
- TMDb poster/backdrop images (auto-downloaded)
- Video frame extraction (best frame via ffmpeg)
- Manga panel (existing pipeline)

Each thumbnail gets:
- Text overlay (title, quote, or hook)
- Color treatment matching the persona
- Gradient overlay for readability
- Persona branding (consistent style)
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path

import requests

log = logging.getLogger(__name__)

TMDB_IMG_BASE = "https://image.tmdb.org/t/p/"

# Sizes
TIKTOK_SIZE = (1080, 1920)   # 9:16
YOUTUBE_SIZE = (1280, 720)    # 16:9

# Font config
FONT_PATH = os.getenv("THUMBNAIL_FONT", "DejaVu-Sans-Bold")

# Persona color schemes (overlay gradient + text)
PERSONA_STYLES = {
    "deep_mind": {
        "gradient_top": "00000080",    # semi-transparent black
        "gradient_bottom": "000000CC",
        "text_color": "white",
        "accent_color": "#00FFFF",     # cyan
        "font_size_title": 72,
        "font_size_sub": 42,
    },
    "pop_oracle": {
        "gradient_top": "1a002580",
        "gradient_bottom": "0a0015CC",
        "text_color": "white",
        "accent_color": "#FF69B4",     # pink
        "font_size_title": 68,
        "font_size_sub": 40,
    },
    "latam": {
        "gradient_top": "1a0a0080",
        "gradient_bottom": "0a0500CC",
        "text_color": "white",
        "accent_color": "#FFA500",     # orange/warm
        "font_size_title": 70,
        "font_size_sub": 42,
    },
    "cinephile": {
        "gradient_top": "00000080",
        "gradient_bottom": "000000CC",
        "text_color": "white",
        "accent_color": "#00FF80",     # green
        "font_size_title": 72,
        "font_size_sub": 42,
    },
}


# ── Source: TMDb images ─────────────────────────────────────────

def download_tmdb_poster(tmdb_id: int, media_type: str = "tv", output_dir: str = "") -> str | None:
    """Download the poster image from TMDb (high quality)."""
    key = os.getenv("TMDB_API_KEY", "")
    if not key:
        return None

    try:
        resp = requests.get(
            f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}",
            params={"api_key": key},
            timeout=10,
        )
        data = resp.json()
        poster_path = data.get("poster_path")
        if not poster_path:
            return None

        # Download high-res poster
        img_url = f"{TMDB_IMG_BASE}w780{poster_path}"
        img_resp = requests.get(img_url, timeout=15)
        if img_resp.status_code != 200:
            return None

        out_dir = Path(output_dir or tempfile.mkdtemp(prefix="thumb_"))
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"poster_{tmdb_id}.jpg"
        out_path.write_bytes(img_resp.content)
        return str(out_path)

    except Exception as e:
        log.warning(f"TMDb poster download failed: {e}")
        return None


def download_tmdb_backdrop(tmdb_id: int, media_type: str = "tv", output_dir: str = "") -> str | None:
    """Download the backdrop/banner image from TMDb (horizontal, good for YouTube)."""
    key = os.getenv("TMDB_API_KEY", "")
    if not key:
        return None

    try:
        resp = requests.get(
            f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}",
            params={"api_key": key},
            timeout=10,
        )
        data = resp.json()
        backdrop_path = data.get("backdrop_path")
        if not backdrop_path:
            return None

        img_url = f"{TMDB_IMG_BASE}w1280{backdrop_path}"
        img_resp = requests.get(img_url, timeout=15)
        if img_resp.status_code != 200:
            return None

        out_dir = Path(output_dir or tempfile.mkdtemp(prefix="thumb_"))
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"backdrop_{tmdb_id}.jpg"
        out_path.write_bytes(img_resp.content)
        return str(out_path)

    except Exception as e:
        log.warning(f"TMDb backdrop download failed: {e}")
        return None


# ── Source: Video frame extraction ──────────────────────────────

def extract_best_frame(
    video_path: str,
    output_path: str = "",
    timestamp_s: float = 0,
) -> str | None:
    """
    Extract the most visually interesting frame from a video.
    If timestamp_s=0, picks frame at 1/3 of the video (usually good).
    """
    if not Path(video_path).exists():
        return None

    if not output_path:
        output_path = str(Path(video_path).with_suffix(".thumb.jpg"))

    if timestamp_s <= 0:
        # Get duration and pick 1/3 point
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "csv=p=0", video_path],
                capture_output=True, text=True, timeout=10,
            )
            duration = float(result.stdout.strip()) if result.stdout.strip() else 10
            timestamp_s = duration / 3
        except Exception:
            timestamp_s = 5

    try:
        subprocess.run(
            ["ffmpeg", "-y", "-ss", str(timestamp_s), "-i", video_path,
             "-vframes", "1", "-q:v", "2", output_path],
            capture_output=True, timeout=15,
        )
        if Path(output_path).exists():
            return output_path
    except Exception as e:
        log.warning(f"Frame extraction failed: {e}")

    return None


# ── Thumbnail generation ────────────────────────────────────────

def generate_thumbnail(
    source_image: str,
    title: str,
    subtitle: str = "",
    persona: str = "deep_mind",
    output_dir: str = "",
    formats: list[str] | None = None,
) -> dict:
    """
    Generate thumbnails for TikTok and YouTube from a source image.

    Returns: {"tiktok": "path/to/tiktok_thumb.jpg", "youtube": "path/to/yt_thumb.jpg"}
    """
    if not Path(source_image).exists():
        return {"error": f"Source image not found: {source_image}"}

    formats = formats or ["tiktok", "youtube"]
    style = PERSONA_STYLES.get(persona, PERSONA_STYLES["deep_mind"])
    out_dir = Path(output_dir or tempfile.mkdtemp(prefix="thumbs_"))
    out_dir.mkdir(parents=True, exist_ok=True)

    results = {}

    for fmt in formats:
        if fmt == "tiktok":
            w, h = TIKTOK_SIZE
            out_path = str(out_dir / "thumb_tiktok.jpg")
        else:
            w, h = YOUTUBE_SIZE
            out_path = str(out_dir / "thumb_youtube.jpg")

        # Build ffmpeg filter chain
        # 1. Scale + crop to target size
        # 2. Add gradient overlay
        # 3. Add text
        title_safe = title.replace("'", "'\\''").replace(":", "\\:")
        sub_safe = subtitle.replace("'", "'\\''").replace(":", "\\:") if subtitle else ""

        font_title = style["font_size_title"]
        font_sub = style["font_size_sub"]
        text_color = style["text_color"]
        accent = style["accent_color"].lstrip("#")

        # Vertical (TikTok): text at bottom
        # Horizontal (YouTube): text at center-left
        if fmt == "tiktok":
            text_y_title = f"h-{font_title + font_sub + 120}"
            text_y_sub = f"h-{font_sub + 60}"
            text_x = "(w-text_w)/2"
        else:
            text_y_title = "(h-text_h)/2-30"
            text_y_sub = "(h/2)+30"
            text_x = "60"

        filters = [
            f"scale={w}:{h}:force_original_aspect_ratio=increase",
            f"crop={w}:{h}",
            # Gradient overlay (darken bottom for text readability)
            f"drawbox=x=0:y=ih/2:w=iw:h=ih/2:color=black@0.5:t=fill",
        ]

        # Title text
        filters.append(
            f"drawtext=text='{title_safe}'"
            f":fontsize={font_title}:fontcolor={text_color}"
            f":x={text_x}:y={text_y_title}"
            f":fontfile={FONT_PATH}"
            f":borderw=3:bordercolor=black"
        )

        # Subtitle text
        if sub_safe:
            filters.append(
                f"drawtext=text='{sub_safe}'"
                f":fontsize={font_sub}:fontcolor=0x{accent}"
                f":x={text_x}:y={text_y_sub}"
                f":fontfile={FONT_PATH}"
                f":borderw=2:bordercolor=black"
            )

        filter_chain = ",".join(filters)

        try:
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", source_image,
                 "-vf", filter_chain,
                 "-q:v", "2", out_path],
                capture_output=True, text=True, timeout=15,
            )
            if Path(out_path).exists():
                results[fmt] = out_path
                log.info(f"Thumbnail {fmt}: {out_path} ({w}x{h})")
            else:
                log.warning(f"Thumbnail {fmt} failed: {result.stderr[:200]}")
        except Exception as e:
            log.warning(f"Thumbnail {fmt} error: {e}")

    return results


def generate_thumbnails_from_tmdb(
    tmdb_id: int,
    title: str,
    subtitle: str = "",
    media_type: str = "tv",
    persona: str = "latam",
    output_dir: str = "",
) -> dict:
    """
    All-in-one: download TMDb images + generate both thumbnail formats.
    Uses poster for TikTok (vertical), backdrop for YouTube (horizontal).
    """
    out_dir = Path(output_dir or f"outputs/thumbnails/{tmdb_id}")
    out_dir.mkdir(parents=True, exist_ok=True)

    results = {}

    # TikTok: use poster (already vertical-ish)
    poster = download_tmdb_poster(tmdb_id, media_type, str(out_dir))
    if poster:
        tt_result = generate_thumbnail(
            poster, title, subtitle, persona, str(out_dir), formats=["tiktok"],
        )
        results.update(tt_result)

    # YouTube: use backdrop (horizontal)
    backdrop = download_tmdb_backdrop(tmdb_id, media_type, str(out_dir))
    if backdrop:
        yt_result = generate_thumbnail(
            backdrop, title, subtitle, persona, str(out_dir), formats=["youtube"],
        )
        results.update(yt_result)

    # Fallback: if only one image, use it for both
    source = poster or backdrop
    if source and len(results) < 2:
        missing = [f for f in ["tiktok", "youtube"] if f not in results]
        if missing:
            fallback = generate_thumbnail(
                source, title, subtitle, persona, str(out_dir), formats=missing,
            )
            results.update(fallback)

    return results
