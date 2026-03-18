"""
ex20 - Análisis de competencia: scrape videos con los mismos hashtags + análisis.

1. Busca videos populares con los mismos hashtags que usamos
2. Extrae métricas (views, likes, engagement)
3. Opcionalmente analiza thumbnails/frames con un VLM (Gemini gratis)
4. Identifica patrones: qué funciona en esos hashtags

Fuentes (todas gratis):
  - YouTube search (yt-dlp, no gasta quota API)
  - TikTok Creative Center (público)
  - VLM: Gemini 2.0 Flash (gratis, 15 req/min) para analizar frames

Uso:
  python src/main.py ex20 --query "villain monologue"
  python src/main.py ex20 --query "epic movie scene" --with-vlm
  python src/main.py ex20 --hashtags "#villain,#moviescene,#shorts"
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

import requests

from common.config import Settings
from common.db import get_db
from common.logger import build_logger


# ---------------------------------------------------------------------------
# Scrape competitor videos from YouTube
# ---------------------------------------------------------------------------

def _yt_search_competitors(query: str, hashtags: list[str], max_results: int = 20) -> list[dict]:
    """Search YouTube for competitor Shorts using yt-dlp (free, no API quota)."""
    search_terms = [query] + [h.lstrip("#") for h in hashtags[:3]]
    search_query = " ".join(search_terms) + " #shorts"

    try:
        result = subprocess.run(
            [
                "yt-dlp",
                f"ytsearch{max_results}:{search_query}",
                "--flat-playlist",
                "--dump-json",
                "--no-download",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return []

        videos = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                duration = data.get("duration", 0) or 0
                # Only Shorts (< 62 seconds)
                if duration > 62:
                    continue

                views = data.get("view_count", 0) or 0
                likes = data.get("like_count", 0) or 0
                comments = data.get("comment_count", 0) or 0

                videos.append({
                    "platform": "youtube",
                    "platform_video_id": data.get("id", ""),
                    "channel_name": data.get("channel", data.get("uploader", "")),
                    "title": data.get("title", ""),
                    "views": views,
                    "likes": likes,
                    "comments": comments,
                    "duration_s": duration,
                    "hashtags": json.dumps(data.get("tags", [])),
                    "thumbnail_url": data.get("thumbnail", ""),
                    "engagement_rate": round((likes + comments) / max(1, views), 6),
                })
            except json.JSONDecodeError:
                continue

        return videos

    except Exception:
        return []


# ---------------------------------------------------------------------------
# TikTok competitor discovery
# ---------------------------------------------------------------------------

def _tiktok_search_by_hashtag(hashtag: str) -> list[dict]:
    """Search TikTok Creative Center for videos using a specific hashtag."""
    tag = hashtag.lstrip("#")
    url = f"https://ads.tiktok.com/business/creativecenter/hashtag/{tag}/pc/en"
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return []

        # Extract video count and trend data from the page
        # This gives us overall hashtag health, not individual videos
        view_match = re.search(r'"viewCount":\s*(\d+)', resp.text)
        video_match = re.search(r'"videoCount":\s*(\d+)', resp.text)

        return [{
            "hashtag": f"#{tag}",
            "total_views": int(view_match.group(1)) if view_match else 0,
            "total_videos": int(video_match.group(1)) if video_match else 0,
            "source": url,
        }]

    except Exception:
        return []


# ---------------------------------------------------------------------------
# VLM Analysis (Gemini 2.0 Flash - free)
# ---------------------------------------------------------------------------

def _analyze_thumbnail_with_vlm(thumbnail_url: str, title: str = "") -> dict:
    """
    Analyze a video thumbnail using Gemini 2.0 Flash (free VLM).

    Extracts:
      - Hook type (text, action, face, question, shock)
      - Text on screen presence
      - Face presence
      - Color scheme (dark, bright, neon, etc.)
      - Estimated quality and appeal
    """
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    if not gemini_key:
        return {"vlm_available": False}

    try:
        # Download thumbnail
        img_resp = requests.get(thumbnail_url, timeout=10)
        if img_resp.status_code != 200:
            return {"vlm_available": False, "error": "thumbnail download failed"}

        img_b64 = base64.b64encode(img_resp.content).decode("utf-8")
        mime = "image/jpeg"

        prompt = f"""Analyze this YouTube Short thumbnail. Title: "{title}"

Answer in JSON only:
{{
  "hook_type": "text|action|face|question|shock|mystery",
  "text_on_screen": true/false,
  "text_content": "what text is visible or empty string",
  "face_present": true/false,
  "face_emotion": "happy|angry|surprised|neutral|none",
  "color_scheme": "dark|bright|neon|warm|cold|mixed",
  "action_level": "static|moderate|high",
  "estimated_appeal": 1-10,
  "what_works": "one sentence about why this thumbnail works or doesn't",
  "style_tags": ["tag1", "tag2"]
}}"""

        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gemini_key}",
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{
                    "parts": [
                        {"inline_data": {"mime_type": mime, "data": img_b64}},
                        {"text": prompt},
                    ]
                }],
            },
            timeout=20,
        )

        if resp.status_code != 200:
            return {"vlm_available": True, "error": f"Gemini returned {resp.status_code}"}

        content = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        # Extract JSON from response
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            analysis = json.loads(match.group())
            analysis["vlm_available"] = True
            return analysis

    except Exception as e:
        return {"vlm_available": True, "error": str(e)[:100]}

    return {"vlm_available": False}


# ---------------------------------------------------------------------------
# Pattern detection
# ---------------------------------------------------------------------------

def _detect_patterns(videos: list[dict]) -> dict:
    """Detect what works based on top-performing competitor videos."""
    if not videos:
        return {}

    # Sort by engagement
    sorted_vids = sorted(videos, key=lambda v: v.get("engagement_rate", 0), reverse=True)
    top_20_pct = sorted_vids[:max(1, len(sorted_vids) // 5)]
    bottom_80_pct = sorted_vids[max(1, len(sorted_vids) // 5):]

    patterns = {
        "sample_size": len(videos),
        "top_performers_count": len(top_20_pct),
    }

    # Average metrics for top vs rest
    if top_20_pct:
        patterns["top_avg_views"] = round(sum(v["views"] for v in top_20_pct) / len(top_20_pct))
        patterns["top_avg_engagement"] = round(
            sum(v["engagement_rate"] for v in top_20_pct) / len(top_20_pct), 5
        )
        patterns["top_avg_duration"] = round(
            sum(v.get("duration_s", 0) for v in top_20_pct) / len(top_20_pct), 1
        )

    if bottom_80_pct:
        patterns["rest_avg_views"] = round(sum(v["views"] for v in bottom_80_pct) / len(bottom_80_pct))
        patterns["rest_avg_engagement"] = round(
            sum(v["engagement_rate"] for v in bottom_80_pct) / len(bottom_80_pct), 5
        )

    # Hashtag frequency in top performers
    top_hashtags: dict[str, int] = {}
    for v in top_20_pct:
        try:
            tags = json.loads(v.get("hashtags", "[]"))
        except Exception:
            tags = []
        for tag in tags:
            tag_lower = tag.lower().strip()
            if tag_lower:
                top_hashtags[tag_lower] = top_hashtags.get(tag_lower, 0) + 1

    patterns["top_hashtags"] = sorted(top_hashtags.items(), key=lambda x: x[1], reverse=True)[:15]

    # VLM insights from top performers
    vlm_insights = [v.get("vlm_analysis", {}) for v in top_20_pct if v.get("vlm_analysis", {}).get("vlm_available")]
    if vlm_insights:
        hook_types: dict[str, int] = {}
        text_on_screen_count = 0
        face_count = 0
        avg_appeal = 0

        for insight in vlm_insights:
            ht = insight.get("hook_type", "unknown")
            hook_types[ht] = hook_types.get(ht, 0) + 1
            if insight.get("text_on_screen"):
                text_on_screen_count += 1
            if insight.get("face_present"):
                face_count += 1
            avg_appeal += insight.get("estimated_appeal", 5)

        patterns["vlm_patterns"] = {
            "dominant_hook_type": max(hook_types, key=hook_types.get) if hook_types else "unknown",
            "text_on_screen_pct": round(text_on_screen_count / len(vlm_insights) * 100),
            "face_present_pct": round(face_count / len(vlm_insights) * 100),
            "avg_appeal": round(avg_appeal / len(vlm_insights), 1),
            "what_works_summary": [
                i.get("what_works", "") for i in vlm_insights[:5] if i.get("what_works")
            ],
        }

    return patterns


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(
    settings: Settings,
    query: str = "epic movie moment",
    hashtags_str: str = "",
    max_results: int = 20,
    with_vlm: bool = False,
) -> Path:
    log = build_logger("ex20", settings.output_dir / "logs" / "ex20.log")
    conn = get_db(settings.data_dir)

    # Parse hashtags
    if hashtags_str:
        hashtags = [h.strip() for h in hashtags_str.split(",") if h.strip()]
    else:
        # Get hashtags from latest growth pack
        meta_dir = settings.output_dir / "metadata"
        hashtags = []
        if meta_dir.exists():
            files = sorted(meta_dir.glob("ex08_growth_pack_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            if files:
                try:
                    pack = json.loads(files[0].read_text(encoding="utf-8"))
                    hashtags = pack.get("youtube", {}).get("hashtags", [])[:5]
                except Exception:
                    pass
        if not hashtags:
            hashtags = [f"#{w}" for w in query.split()[:3]]

    log.info("Searching competitors for: %s (hashtags: %s)", query, hashtags)

    # 1) YouTube competitors
    yt_competitors = _yt_search_competitors(query, hashtags, max_results=max_results)
    log.info("Found %d YouTube competitors", len(yt_competitors))

    # 2) TikTok hashtag health
    tt_hashtag_data = []
    for tag in hashtags[:5]:
        data = _tiktok_search_by_hashtag(tag)
        tt_hashtag_data.extend(data)

    # 3) VLM analysis on top YouTube thumbnails (if enabled)
    if with_vlm and yt_competitors:
        log.info("Running VLM analysis on top %d thumbnails...", min(5, len(yt_competitors)))
        # Only analyze top 5 by views to stay within free limits
        top_by_views = sorted(yt_competitors, key=lambda v: v.get("views", 0), reverse=True)[:5]
        for v in top_by_views:
            if v.get("thumbnail_url"):
                log.info("  Analyzing: %s", v.get("title", "?")[:50])
                v["vlm_analysis"] = _analyze_thumbnail_with_vlm(
                    v["thumbnail_url"],
                    v.get("title", ""),
                )

    # 4) Detect patterns
    patterns = _detect_patterns(yt_competitors)

    # 5) Save competitors to DB
    for v in yt_competitors:
        try:
            vlm = v.get("vlm_analysis", {})
            conn.execute("""
                INSERT OR REPLACE INTO competitor_videos (
                    platform, platform_video_id, channel_name, title,
                    views, likes, comments, duration_s,
                    hashtags, engagement_rate,
                    detected_hook_type, text_on_screen, face_present,
                    estimated_quality, what_works
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                v["platform"], v.get("platform_video_id", ""),
                v.get("channel_name", ""), v.get("title", ""),
                v["views"], v["likes"], v["comments"], v.get("duration_s", 0),
                v.get("hashtags", "[]"), v["engagement_rate"],
                vlm.get("hook_type", ""), 1 if vlm.get("text_on_screen") else 0,
                1 if vlm.get("face_present") else 0,
                vlm.get("estimated_appeal", 0),
                json.dumps({"what_works": vlm.get("what_works", ""), "style_tags": vlm.get("style_tags", [])}),
            ))
        except Exception:
            continue

    conn.commit()

    # 6) Report
    out_dir = settings.output_dir / "analytics"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", query.strip())[:50] or "theme"

    report = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "query": query,
        "hashtags_searched": hashtags,
        "youtube_competitors": len(yt_competitors),
        "tiktok_hashtag_data": tt_hashtag_data,
        "patterns": patterns,
        "top_competitors": sorted(yt_competitors, key=lambda v: v.get("engagement_rate", 0), reverse=True)[:10],
    }

    json_path = out_dir / f"ex20_competitors_{slug}_{ts}.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    txt_path = out_dir / f"ex20_competitors_{slug}_{ts}.txt"
    lines = [
        "ex20 - Competitor Analysis",
        "=" * 50,
        f"Query: {query}",
        f"Hashtags: {', '.join(hashtags)}",
        f"YouTube competitors found: {len(yt_competitors)}",
        "",
    ]

    if patterns:
        lines.append("Patterns detected:")
        lines.append(f"  Top performers avg views: {patterns.get('top_avg_views', 'N/A'):,}")
        lines.append(f"  Top performers avg engagement: {patterns.get('top_avg_engagement', 'N/A')}")
        lines.append(f"  Top performers avg duration: {patterns.get('top_avg_duration', 'N/A')}s")
        lines.append("")

        if patterns.get("top_hashtags"):
            lines.append("  Most used hashtags by top performers:")
            for tag, count in patterns["top_hashtags"][:10]:
                lines.append(f"    #{tag}: {count}x")

        if patterns.get("vlm_patterns"):
            vlm_p = patterns["vlm_patterns"]
            lines.append("")
            lines.append("  VLM visual patterns (from thumbnails):")
            lines.append(f"    Dominant hook: {vlm_p.get('dominant_hook_type', '?')}")
            lines.append(f"    Text on screen: {vlm_p.get('text_on_screen_pct', '?')}%")
            lines.append(f"    Face visible: {vlm_p.get('face_present_pct', '?')}%")
            lines.append(f"    Avg appeal: {vlm_p.get('avg_appeal', '?')}/10")
            for insight in vlm_p.get("what_works_summary", [])[:3]:
                lines.append(f"    - {insight}")

    txt_path.write_text("\n".join(lines), encoding="utf-8")

    conn.close()
    log.info("Competitor analysis saved to %s", json_path)
    return json_path
