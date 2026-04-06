"""
ex12 - Upload de Shorts a YouTube via Data API v3.

La YouTube Data API v3 es gratis:
  - 10,000 unidades/dia
  - Un upload consume ~1,600 unidades = ~6 uploads/dia gratis

Requisitos:
  1. Google Cloud Console: habilitar YouTube Data API v3
  2. Crear OAuth 2.0 credentials (tipo "Desktop app")
  3. Descargar client_secrets.json a la raiz del proyecto
  4. Primera ejecucion: abre el navegador para autorizar

Uso:
  python src/main.py ex12 --video outputs/video/finals/short_villain.mp4
  python src/main.py ex12 --video outputs/video/finals/short_villain.mp4 --title "Top villain quotes"
  python src/main.py ex12 --video outputs/video/finals/short_villain.mp4 --privacy unlisted
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from common.config import Settings
from common.db import get_db
from common.logger import build_logger


def _find_client_secrets() -> Path | None:
    """Look for Google OAuth client_secrets.json in common locations."""
    from exercises.ex34_oauth_manager import find_client_secrets
    return find_client_secrets()


def _get_authenticated_service(secrets_path: Path, log, persona: str = ""):
    """
    Build an authenticated YouTube API service using OAuth 2.0.
    Delegates to ex34_oauth_manager for unified token management.
    Persona selects which channel token to use.
    """
    from exercises.ex34_oauth_manager import get_youtube_service
    return get_youtube_service(secrets_path=secrets_path, log=log, persona=persona)


def _load_growth_pack(output_dir: Path, query: str) -> dict:
    """Load the latest growth pack from ex08 for hashtags and description."""
    meta_dir = output_dir / "metadata"
    if not meta_dir.exists():
        return {}

    candidates = sorted(meta_dir.glob("ex08_growth_pack_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)

    # Try to match query
    if query:
        safe_q = query.replace(" ", "_").lower()
        for c in candidates:
            if safe_q in c.stem.lower():
                return json.loads(c.read_text(encoding="utf-8"))

    if candidates:
        return json.loads(candidates[0].read_text(encoding="utf-8"))
    return {}


def _build_upload_metadata(
    title: str,
    description: str,
    tags: list[str],
    privacy: str,
    category_id: str = "24",  # Entertainment
) -> dict:
    """Build the YouTube upload request body."""
    return {
        "snippet": {
            "title": title[:100],  # YouTube max title length
            "description": description[:5000],
            "tags": tags[:30],  # YouTube max 30 tags (500 chars total)
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
            "shorts_parameters": {
                "is_short": True,
            },
        },
    }


def upload_video(
    youtube_service,
    video_path: Path,
    metadata: dict,
    log,
) -> str | None:
    """
    Upload a video to YouTube using the resumable upload protocol.

    Returns the video ID on success, None on failure.
    """
    try:
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        log.error("google-api-python-client not installed.")
        return None

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=10 * 1024 * 1024,  # 10MB chunks
    )

    request = youtube_service.videos().insert(
        part="snippet,status",
        body=metadata,
        media_body=media,
    )

    log.info(f"Uploading: {video_path.name} ({video_path.stat().st_size / 1024 / 1024:.1f} MB)")

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            log.info(f"  Upload progress: {int(status.progress() * 100)}%")

    video_id = response.get("id")
    if video_id:
        log.info(f"Upload complete! Video ID: {video_id}")
        log.info(f"URL: https://www.youtube.com/shorts/{video_id}")
        return video_id

    log.error(f"Upload failed. Response: {response}")
    return None


# ── Entry point ──────────────────────────────────────────────────────


def run(
    settings: Settings,
    video_path: str = "",
    title: str = "",
    privacy: str = "unlisted",
    query: str = "",
    persona: str = "",
    video: str = "",
) -> Path:
    log = build_logger("ex12", settings.output_dir / "logs" / "ex12.log")
    report_lines = ["ex12 - YouTube Upload Report", "=" * 50, ""]

    # Find the video
    video = Path(video_path) if video_path else None
    if not video or not video.exists():
        # Try to find latest final
        finals_dir = settings.output_dir / "video" / "finals"
        if finals_dir.exists():
            candidates = sorted(finals_dir.glob("short_*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
            if candidates:
                video = candidates[0]

    if not video or not video.exists():
        msg = "No video file found. Run ex11 first to generate a Short."
        log.error(msg)
        report_path = settings.output_dir / "logs" / "ex12_upload_report.txt"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(f"ex12 - ERROR: {msg}\n", encoding="utf-8")
        return report_path

    log.info(f"Video: {video}")
    report_lines.append(f"Video: {video}")
    report_lines.append(f"Size: {video.stat().st_size / 1024 / 1024:.1f} MB")

    # Find client secrets
    secrets = _find_client_secrets()
    if not secrets:
        msg = (
            "client_secrets.json not found.\n"
            "Setup:\n"
            "  1. Go to https://console.cloud.google.com\n"
            "  2. Enable YouTube Data API v3\n"
            "  3. Create OAuth 2.0 credentials (Desktop app)\n"
            "  4. Download and save as client_secrets.json in project root"
        )
        log.error(msg)
        report_lines.append(f"\nERROR: {msg}")
        report_path = settings.output_dir / "logs" / "ex12_upload_report.txt"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("\n".join(report_lines), encoding="utf-8")
        return report_path

    # Authenticate
    # video param alias for backward compat
    if video and not video_path:
        video_path = video
    youtube = _get_authenticated_service(secrets, log, persona=persona)
    if not youtube:
        report_lines.append("\nERROR: Authentication failed. Check logs.")
        report_path = settings.output_dir / "logs" / "ex12_upload_report.txt"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("\n".join(report_lines), encoding="utf-8")
        return report_path

    # Load growth pack for hashtags/description
    pack = _load_growth_pack(settings.output_dir, query)

    # Build title
    if not title:
        yt_data = pack.get("youtube", {})
        templates = yt_data.get("title_templates", [])
        title = templates[0] if templates else f"Movie Short - {query or 'compilation'}"

    # Build description
    yt_data = pack.get("youtube", {})
    desc = yt_data.get("description_template", f"Short about {query or 'movies'}.")
    hashtags = yt_data.get("hashtags", ["#shorts", "#movie", "#cinema"])
    desc += "\n\n" + " ".join(hashtags)

    # Build tags from hashtags (remove #)
    tags = [h.lstrip("#") for h in hashtags if h.startswith("#")]

    log.info(f"Title: {title}")
    log.info(f"Privacy: {privacy}")
    report_lines.append(f"\nTitle: {title}")
    report_lines.append(f"Privacy: {privacy}")
    report_lines.append(f"Tags: {', '.join(tags[:10])}")

    # Build metadata and upload
    metadata = _build_upload_metadata(title, desc, tags, privacy)

    try:
        video_id = upload_video(youtube, video, metadata, log)
    except Exception as e:
        log.error(f"Upload error: {e}")
        video_id = None

    if video_id:
        url = f"https://www.youtube.com/shorts/{video_id}"
        report_lines.append(f"\nUPLOAD SUCCESS!")
        report_lines.append(f"Video ID: {video_id}")
        report_lines.append(f"URL: {url}")

        # Update DB
        conn = get_db(settings.data_dir)
        conn.execute(
            "UPDATE shorts SET youtube_id = ?, status = 'uploaded' WHERE output_file = ?",
            (video_id, str(video)),
        )
        conn.commit()
        conn.close()
    else:
        report_lines.append("\nUPLOAD FAILED - check ex12.log for details")

    report_path = settings.output_dir / "logs" / "ex12_upload_report.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    log.info(f"Report: {report_path}")

    return report_path
