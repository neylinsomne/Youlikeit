"""
Google Trends integration for trend-aware content publishing.

Uses pytrends (unofficial Google Trends API, no API key needed).
Provides trending topics related to cinema for:
  - ex17: publish strategy (time content when topic is trending)
  - ex33: curriculum planner (prioritize trending themes)

Rate limit: ~1 req/60s to avoid blocks. Cache results for 6 hours.

Usage:
  from common.trends import get_cinema_trends, get_topic_interest

  trends = get_cinema_trends(geo="CO")  # trending movie topics in Colombia
  interest = get_topic_interest("Christopher Nolan")  # is this trending?
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path


def _get_cache_path() -> Path:
    cache = Path("data") / "processed" / "trends_cache.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    return cache


def _load_cache() -> dict:
    path = _get_cache_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            # Expire after 6 hours
            if time.time() - data.get("ts", 0) < 21600:
                return data
        except Exception:
            pass
    return {}


def _save_cache(data: dict):
    data["ts"] = time.time()
    _get_cache_path().write_text(
        json.dumps(data, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def get_cinema_trends(geo: str = "", limit: int = 10) -> list[dict]:
    """
    Get trending topics related to cinema/movies.

    Returns list of {topic, interest, rising} sorted by interest.
    """
    cache = _load_cache()
    cache_key = f"cinema_{geo}"
    if cache_key in cache:
        return cache[cache_key]

    try:
        from pytrends.request import TrendReq
    except ImportError:
        return []

    try:
        pytrends = TrendReq(hl="es", timeout=(5, 15))

        # Search related queries for cinema topics
        seeds = ["películas", "movie quotes", "escenas de cine"]
        all_topics = []

        for seed in seeds[:2]:  # Rate limit: max 2 queries
            pytrends.build_payload(
                [seed],
                timeframe="now 7-d",
                geo=geo.upper() if geo else "",
            )
            related = pytrends.related_queries()

            for kw, data in related.items():
                # Rising queries (breakout topics)
                rising = data.get("rising")
                if rising is not None and not rising.empty:
                    for _, row in rising.head(limit).iterrows():
                        all_topics.append({
                            "topic": row["query"],
                            "interest": int(row["value"]) if row["value"] != "Breakout" else 1000,
                            "rising": True,
                        })

                # Top queries (sustained interest)
                top = data.get("top")
                if top is not None and not top.empty:
                    for _, row in top.head(limit).iterrows():
                        all_topics.append({
                            "topic": row["query"],
                            "interest": int(row["value"]),
                            "rising": False,
                        })

            time.sleep(2)  # Rate limit

        # Deduplicate and sort
        seen = set()
        unique = []
        for t in sorted(all_topics, key=lambda x: x["interest"], reverse=True):
            if t["topic"].lower() not in seen:
                seen.add(t["topic"].lower())
                unique.append(t)

        result = unique[:limit]
        cache[cache_key] = result
        _save_cache(cache)
        return result

    except Exception:
        return []


def get_topic_interest(topic: str, geo: str = "") -> dict:
    """
    Check if a specific topic is trending right now.

    Returns {topic, current_interest, trend_direction, is_hot}
    """
    cache = _load_cache()
    cache_key = f"interest_{topic}_{geo}"
    if cache_key in cache:
        return cache[cache_key]

    try:
        from pytrends.request import TrendReq
    except ImportError:
        return {"topic": topic, "current_interest": 0, "trend_direction": "unknown", "is_hot": False}

    try:
        pytrends = TrendReq(hl="es", timeout=(5, 15))
        pytrends.build_payload(
            [topic],
            timeframe="now 7-d",
            geo=geo.upper() if geo else "",
        )
        interest = pytrends.interest_over_time()

        if interest.empty:
            result = {"topic": topic, "current_interest": 0, "trend_direction": "flat", "is_hot": False}
        else:
            values = interest[topic].tolist()
            current = values[-1] if values else 0
            prev = values[-3] if len(values) >= 3 else current

            if current > prev * 1.3:
                direction = "rising"
            elif current < prev * 0.7:
                direction = "falling"
            else:
                direction = "stable"

            result = {
                "topic": topic,
                "current_interest": int(current),
                "trend_direction": direction,
                "is_hot": current >= 70 or direction == "rising",
            }

        cache[cache_key] = result
        _save_cache(cache)
        return result

    except Exception:
        return {"topic": topic, "current_interest": 0, "trend_direction": "unknown", "is_hot": False}


def suggest_trending_queries(geo: str = "") -> list[str]:
    """
    Suggest content queries based on what's trending in cinema.
    For use in ex33 curriculum planner.
    """
    trends = get_cinema_trends(geo=geo, limit=8)
    return [t["topic"] for t in trends if t.get("interest", 0) > 20]
