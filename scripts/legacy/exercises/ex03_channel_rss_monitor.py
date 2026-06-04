import json
from datetime import datetime
from pathlib import Path

import feedparser

from core.config import Settings
from utils.logger import build_logger


def run(channel_id: str, settings: Settings) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = settings.data_dir / "processed" / f"ex03_rss_{channel_id}_{ts}.json"
    log_path = settings.output_dir / "logs" / f"ex03_{ts}.log"

    logger = build_logger("ex03", log_path)
    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    logger.info("Leyendo feed RSS: %s", rss_url)

    feed = feedparser.parse(rss_url)

    items = []
    for entry in feed.entries[:10]:
        items.append(
            {
                "title": entry.get("title"),
                "published": entry.get("published"),
                "link": entry.get("link"),
                "video_id": entry.get("yt_videoid"),
            }
        )

    out_path.write_text(
        json.dumps({"channel_id": channel_id, "count": len(items), "items": items}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    logger.info("Resultados guardados en %s", out_path)
    return out_path
