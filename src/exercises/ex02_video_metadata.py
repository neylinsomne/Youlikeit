import json
from datetime import datetime
from pathlib import Path

from yt_dlp import YoutubeDL

from common.config import Settings
from common.logger import build_logger


def run(url: str, settings: Settings) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = settings.data_dir / "raw" / f"ex02_metadata_{ts}.json"
    log_path = settings.output_dir / "logs" / f"ex02_{ts}.log"

    logger = build_logger("ex02", log_path)
    logger.info("Extrayendo metadata de %s", url)

    ydl_opts = {
        "quiet": True,
        "skip_download": True,
    }

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    # Guardamos un subconjunto util para ejercicios.
    payload = {
        "id": info.get("id"),
        "title": info.get("title"),
        "uploader": info.get("uploader"),
        "duration": info.get("duration"),
        "view_count": info.get("view_count"),
        "like_count": info.get("like_count"),
        "upload_date": info.get("upload_date"),
        "tags": info.get("tags"),
        "categories": info.get("categories"),
        "webpage_url": info.get("webpage_url"),
    }

    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Metadata guardada en %s", out_path)

    return out_path
