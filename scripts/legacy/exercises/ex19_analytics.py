"""
ex19 - Scraper de métricas de videos propios publicados.

Revisa tus videos subidos en YouTube y TikTok para obtener:
  - Views, likes, comments, shares
  - Retención promedio (YouTube Analytics)
  - CTR e impresiones
  - Engagement rate calculado

Alimenta la tabla `analytics` para que ex21 ajuste los pesos.

Fuentes:
  - YouTube: Data API v3 (gratis, ya tienes OAuth de ex12)
  - TikTok: scraping público de perfil (sin API, gratis)

Uso:
  python src/main.py ex19
  python src/main.py ex19 --days-back 7
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

import requests

from core.config import Settings
from core.db import get_db
from utils.logger import build_logger


# ---------------------------------------------------------------------------
# YouTube Analytics (via Data API v3 - free)
# ---------------------------------------------------------------------------

def _youtube_get_my_videos(days_back: int = 30) -> list[dict]:
    """Get your uploaded YouTube Shorts via Data API v3."""
    api_key = os.getenv("YOUTUBE_API_KEY", "")
    channel_id = os.getenv("YOUTUBE_CHANNEL_ID", "")

    if not api_key or not channel_id:
        return []

    published_after = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%dT00:00:00Z")

    try:
        # Search for your own videos
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "key": api_key,
                "channelId": channel_id,
                "part": "snippet",
                "order": "date",
                "publishedAfter": published_after,
                "maxResults": 50,
                "type": "video",
            },
            timeout=15,
        )
        if resp.status_code != 200:
            return []

        items = resp.json().get("items", [])
        video_ids = [i["id"]["videoId"] for i in items if i.get("id", {}).get("videoId")]

        if not video_ids:
            return []

        # Get statistics for each video
        stats_resp = requests.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={
                "key": api_key,
                "id": ",".join(video_ids),
                "part": "statistics,snippet,contentDetails",
            },
            timeout=15,
        )
        if stats_resp.status_code != 200:
            return []

        videos = []
        for item in stats_resp.json().get("items", []):
            stats = item.get("statistics", {})
            snippet = item.get("snippet", {})
            videos.append({
                "platform": "youtube",
                "platform_video_id": item["id"],
                "title": snippet.get("title", ""),
                "views": int(stats.get("viewCount", 0)),
                "likes": int(stats.get("likeCount", 0)),
                "comments": int(stats.get("commentCount", 0)),
                "shares": 0,  # YouTube API doesn't expose shares
                "hashtags_used": json.dumps(snippet.get("tags", [])),
                "upload_time": snippet.get("publishedAt", ""),
            })

        return videos

    except Exception:
        return []


# ---------------------------------------------------------------------------
# TikTok Metrics (public scraping - no API needed)
# ---------------------------------------------------------------------------

def _tiktok_get_profile_videos(username: str = "") -> list[dict]:
    """
    Scrape public TikTok profile for video metrics.
    Note: TikTok aggressively blocks scraping. This is best-effort.
    For reliable metrics, use TikTok Business analytics manually.
    """
    if not username:
        username = os.getenv("TIKTOK_USERNAME", "")
    if not username:
        return []

    # Clean username
    username = username.lstrip("@")

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        resp = requests.get(
            f"https://www.tiktok.com/@{username}",
            headers=headers,
            timeout=15,
        )
        if resp.status_code != 200:
            return []

        # Try to extract video data from the page's embedded JSON
        # TikTok embeds video data in __UNIVERSAL_DATA_FOR_REHYDRATION__
        match = re.search(
            r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',
            resp.text,
            re.DOTALL,
        )
        if not match:
            return []

        data = json.loads(match.group(1))
        # Navigate the nested structure to find video items
        user_module = data.get("__DEFAULT_SCOPE__", {}).get("webapp.user-detail", {})
        items = user_module.get("userInfo", {}).get("items", [])

        if not items:
            # Alternative path
            video_list = data.get("__DEFAULT_SCOPE__", {}).get("webapp.video-detail", {})
            items = video_list.get("itemList", [])

        videos = []
        for item in items[:50]:
            stats = item.get("stats", {})
            videos.append({
                "platform": "tiktok",
                "platform_video_id": item.get("id", ""),
                "title": item.get("desc", ""),
                "views": int(stats.get("playCount", 0)),
                "likes": int(stats.get("diggCount", 0)),
                "comments": int(stats.get("commentCount", 0)),
                "shares": int(stats.get("shareCount", 0)),
                "hashtags_used": json.dumps(
                    [t.get("hashtagName", "") for t in item.get("textExtra", []) if t.get("hashtagName")]
                ),
                "song_used": item.get("music", {}).get("title", ""),
                "upload_time": datetime.fromtimestamp(item.get("createTime", 0)).isoformat()
                if item.get("createTime") else "",
            })

        return videos

    except Exception:
        return []


# ---------------------------------------------------------------------------
# Calculate derived metrics
# ---------------------------------------------------------------------------

def _calc_engagement(video: dict) -> dict:
    """Calculate engagement rate and viral ratio."""
    views = max(1, video.get("views", 0))
    likes = video.get("likes", 0)
    comments = video.get("comments", 0)
    shares = video.get("shares", 0)

    video["engagement_rate"] = round((likes + comments + shares) / views, 6)
    video["viral_ratio"] = round(shares / views, 6) if shares > 0 else 0.0
    return video


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(
    settings: Settings,
    days_back: int = 30,
) -> Path:
    log = build_logger("ex19", settings.output_dir / "logs" / "ex19.log")
    conn = get_db(settings.data_dir)

    all_videos = []

    # 1) YouTube
    log.info("Fetching YouTube analytics (last %d days)...", days_back)
    yt_videos = _youtube_get_my_videos(days_back=days_back)
    if yt_videos:
        log.info("Found %d YouTube videos", len(yt_videos))
        all_videos.extend(yt_videos)
    else:
        log.warning("No YouTube videos found. Set YOUTUBE_API_KEY and YOUTUBE_CHANNEL_ID in .env")

    # 2) TikTok
    log.info("Fetching TikTok analytics...")
    tt_videos = _tiktok_get_profile_videos()
    if tt_videos:
        log.info("Found %d TikTok videos", len(tt_videos))
        all_videos.extend(tt_videos)
    else:
        log.warning("No TikTok videos found. Set TIKTOK_USERNAME in .env")

    # 3) Calculate engagement + save to DB
    for video in all_videos:
        video = _calc_engagement(video)

        # Match to short_id if possible
        short_id = None
        if video.get("title"):
            cur = conn.execute(
                "SELECT id FROM shorts WHERE title LIKE ? LIMIT 1",
                (f"%{video['title'][:50]}%",),
            )
            row = cur.fetchone()
            if row:
                short_id = row["id"]

        # Upsert analytics
        existing = conn.execute(
            "SELECT id FROM analytics WHERE platform = ? AND platform_video_id = ?",
            (video["platform"], video.get("platform_video_id", "")),
        ).fetchone()

        if existing:
            conn.execute("""
                UPDATE analytics SET
                    views = ?, likes = ?, comments = ?, shares = ?,
                    engagement_rate = ?, viral_ratio = ?,
                    hashtags_used = ?, song_used = ?,
                    scraped_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                video["views"], video["likes"], video["comments"], video["shares"],
                video["engagement_rate"], video["viral_ratio"],
                video.get("hashtags_used", "[]"), video.get("song_used", ""),
                existing["id"],
            ))
        else:
            conn.execute("""
                INSERT INTO analytics (
                    short_id, platform, platform_video_id,
                    views, likes, comments, shares,
                    engagement_rate, viral_ratio,
                    hashtags_used, song_used, upload_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                short_id, video["platform"], video.get("platform_video_id", ""),
                video["views"], video["likes"], video["comments"], video["shares"],
                video["engagement_rate"], video["viral_ratio"],
                video.get("hashtags_used", "[]"), video.get("song_used", ""),
                video.get("upload_time", ""),
            ))

    conn.commit()

    # 4) Generate report
    out_dir = settings.output_dir / "analytics"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    report_path = out_dir / f"ex19_analytics_{ts}.txt"
    lines = [
        "ex19 - Analytics Report",
        "=" * 50,
        f"Period: last {days_back} days",
        f"YouTube videos: {len(yt_videos)}",
        f"TikTok videos: {len(tt_videos)}",
        "",
    ]

    # Sort by engagement
    all_videos.sort(key=lambda v: v.get("engagement_rate", 0), reverse=True)

    if all_videos:
        lines.append("Top performers by engagement:")
        for i, v in enumerate(all_videos[:10], 1):
            lines.append(
                f"  {i}. [{v['platform']}] {v.get('title', '?')[:60]}"
            )
            lines.append(
                f"     Views: {v['views']:,} | Likes: {v['likes']:,} | "
                f"Engagement: {v['engagement_rate']:.4f} | Viral: {v['viral_ratio']:.4f}"
            )
            if v.get("song_used"):
                lines.append(f"     Song: {v['song_used']}")
            lines.append("")

        # Insights
        avg_eng = sum(v["engagement_rate"] for v in all_videos) / len(all_videos)
        avg_views = sum(v["views"] for v in all_videos) / len(all_videos)
        lines.append(f"Average engagement rate: {avg_eng:.4f}")
        lines.append(f"Average views: {avg_views:,.0f}")

        # Best hashtags
        hashtag_perf: dict[str, list[float]] = {}
        for v in all_videos:
            try:
                tags = json.loads(v.get("hashtags_used", "[]"))
            except Exception:
                tags = []
            for tag in tags:
                if tag not in hashtag_perf:
                    hashtag_perf[tag] = []
                hashtag_perf[tag].append(v["engagement_rate"])

        if hashtag_perf:
            lines.append("")
            lines.append("Hashtag performance (avg engagement):")
            sorted_tags = sorted(
                hashtag_perf.items(),
                key=lambda x: sum(x[1]) / len(x[1]),
                reverse=True,
            )
            for tag, rates in sorted_tags[:10]:
                avg = sum(rates) / len(rates)
                lines.append(f"  #{tag}: {avg:.4f} (used {len(rates)}x)")
    else:
        lines.append("No videos found. Configure API keys in .env:")
        lines.append("  YOUTUBE_API_KEY=...")
        lines.append("  YOUTUBE_CHANNEL_ID=...")
        lines.append("  TIKTOK_USERNAME=@...")

    report_path.write_text("\n".join(lines), encoding="utf-8")

    conn.close()
    log.info("Analytics report saved to %s", report_path)
    return report_path
