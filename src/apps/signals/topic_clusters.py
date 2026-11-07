"""
Topic Clusters: configurable multi-topic trend categories for the ETL pipeline.

Each cluster defines:
- Seeds: Google Trends search queries to run
- Priority: 1-10, higher = more frequent scraping
- Interval: how often to scrape (minutes)
- RSS feeds: optional news feeds for this cluster

The scheduler picks clusters based on priority and last-scraped time.

Usage:
    from apps.signals.topic_clusters import (
        get_enabled_clusters,
        get_cluster_config,
        schedule_next_cluster,
        get_due_clusters,
    )

    clusters = get_enabled_clusters()
    next_cluster = schedule_next_cluster()
    due = get_due_clusters()
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

log = logging.getLogger(__name__)


# ── Cluster data class ──────────────────────────────────────────────


class TopicCluster:
    """Represents a single topic cluster with its configuration."""

    def __init__(
        self,
        cluster_name: str,
        display_name: str,
        priority: int = 5,
        seeds: list[str] | None = None,
        rss_feeds: list[str] | None = None,
        interval_minutes: int = 240,
        enabled: bool = True,
        last_scraped_at: Optional[datetime] = None,
    ):
        self.cluster_name = cluster_name
        self.display_name = display_name
        self.priority = priority
        self.seeds = seeds or []
        self.rss_feeds = rss_feeds or []
        self.interval_minutes = interval_minutes
        self.enabled = enabled
        self.last_scraped_at = last_scraped_at

    @property
    def is_due(self) -> bool:
        """Check if this cluster is due for scraping based on its interval."""
        if self.last_scraped_at is None:
            return True
        next_run = self.last_scraped_at + timedelta(minutes=self.interval_minutes)
        return datetime.now() >= next_run

    @property
    def minutes_until_due(self) -> int:
        """Minutes until this cluster is due for scraping."""
        if self.last_scraped_at is None:
            return 0
        next_run = self.last_scraped_at + timedelta(minutes=self.interval_minutes)
        delta = next_run - datetime.now()
        return max(0, int(delta.total_seconds() / 60))

    def to_dict(self) -> dict:
        return {
            "cluster_name": self.cluster_name,
            "display_name": self.display_name,
            "priority": self.priority,
            "seeds": self.seeds,
            "rss_feeds": self.rss_feeds,
            "interval_minutes": self.interval_minutes,
            "enabled": self.enabled,
            "last_scraped_at": self.last_scraped_at.isoformat() if self.last_scraped_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"TopicCluster('{self.cluster_name}', priority={self.priority}, "
            f"interval={self.interval_minutes}m, enabled={self.enabled})"
        )


# ── Database helpers ────────────────────────────────────────────────


def _row_to_cluster(row: sqlite3.Row) -> TopicCluster:
    """Convert a DB row to a TopicCluster object."""
    last_scraped = None
    if row.get("last_scraped_at"):
        try:
            last_scraped = datetime.fromisoformat(row["last_scraped_at"])
        except (ValueError, TypeError):
            pass

    return TopicCluster(
        cluster_name=row["cluster_name"],
        display_name=row["display_name"],
        priority=row["priority"],
        seeds=json.loads(row["seeds_json"] or "[]"),
        rss_feeds=json.loads(row["rss_feeds_json"] or "[]"),
        interval_minutes=row["interval_minutes"],
        enabled=bool(row["enabled"]),
        last_scraped_at=last_scraped,
    )


def get_enabled_clusters(conn: sqlite3.Connection) -> list[TopicCluster]:
    """Get all enabled topic clusters, sorted by priority descending."""
    cur = conn.execute(
        "SELECT * FROM topic_clusters WHERE enabled = 1 ORDER BY priority DESC"
    )
    return [_row_to_cluster(row) for row in cur.fetchall()]


def get_cluster_config(conn: sqlite3.Connection, cluster_name: str) -> Optional[TopicCluster]:
    """Get a specific cluster's configuration."""
    cur = conn.execute(
        "SELECT * FROM topic_clusters WHERE cluster_name = ?",
        (cluster_name,),
    )
    row = cur.fetchone()
    if row:
        return _row_to_cluster(row)
    return None


def get_due_clusters(conn: sqlite3.Connection) -> list[TopicCluster]:
    """Get clusters that are due for scraping (interval has passed)."""
    clusters = get_enabled_clusters(conn)
    return [c for c in clusters if c.is_due]


def schedule_next_cluster(conn: sqlite3.Connection) -> Optional[TopicCluster]:
    """
    Pick the next cluster to scrape using priority-weighted round-robin.

    Strategy:
    1. Among due clusters, pick the highest priority
    2. If none due, pick the one closest to being due (highest priority among them)
    3. Returns None if no clusters are enabled
    """
    clusters = get_enabled_clusters(conn)
    if not clusters:
        return None

    due = [c for c in clusters if c.is_due]
    if due:
        # Among due, pick highest priority
        due.sort(key=lambda c: c.priority, reverse=True)
        return due[0]

    # None due — pick the one closest to being due, weighted by priority
    # Score = (minutes_until_due / interval_minutes) - (priority * 0.1)
    # Lower score = more urgent
    scored = []
    for c in clusters:
        urgency = c.minutes_until_due / max(c.interval_minutes, 1)
        score = urgency - (c.priority * 0.05)
        scored.append((score, c))

    scored.sort(key=lambda x: x[0])
    return scored[0][1]


def mark_cluster_scraped(conn: sqlite3.Connection, cluster_name: str):
    """Update the last_scraped_at timestamp for a cluster."""
    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE topic_clusters SET last_scraped_at = ? WHERE cluster_name = ?",
        (now, cluster_name),
    )
    conn.commit()


def update_cluster_config(
    conn: sqlite3.Connection,
    cluster_name: str,
    **kwargs,
) -> bool:
    """
    Update a cluster's configuration.

    Allowed kwargs: display_name, priority, seeds_json, rss_feeds_json,
    interval_minutes, enabled
    """
    allowed = {"display_name", "priority", "seeds_json", "rss_feeds_json",
               "interval_minutes", "enabled"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return False

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [cluster_name]

    conn.execute(
        f"UPDATE topic_clusters SET {set_clause} WHERE cluster_name = ?",
        values,
    )
    conn.commit()
    return True


# ── Default cluster definitions (fallback if DB not available) ──────

DEFAULT_CLUSTERS: list[dict] = [
    {
        "cluster_name": "movies_tv",
        "display_name": "Movies & TV",
        "priority": 9,
        "seeds": [
            "movie release", "tv series", "streaming", "netflix",
            "peliculas", "movie quotes", "escenas de cine",
        ],
        "interval_minutes": 60,
    },
    {
        "cluster_name": "anime_manga_otaku",
        "display_name": "Anime & Manga",
        "priority": 9,
        "seeds": [
            "anime release", "manga chapter", "cosplay",
            "anime convention", "anime trending", "manga release",
        ],
        "interval_minutes": 60,
    },
    {
        "cluster_name": "music_entertainment",
        "display_name": "Music & Entertainment",
        "priority": 8,
        "seeds": [
            "music charts", "new album", "concert", "festival",
            "billboard", "trending song", "viral music",
        ],
        "interval_minutes": 120,
    },
    {
        "cluster_name": "news_politics",
        "display_name": "News & Politics",
        "priority": 8,
        "seeds": [
            "breaking news", "politics today", "world news",
            "trending news", "current events",
        ],
        "interval_minutes": 60,
    },
    {
        "cluster_name": "technology",
        "display_name": "Technology",
        "priority": 7,
        "seeds": [
            "tech news", "AI", "startup", "gadgets",
            "cybersecurity", "new technology",
        ],
        "interval_minutes": 120,
    },
    {
        "cluster_name": "sports",
        "display_name": "Sports",
        "priority": 6,
        "seeds": [
            "sports highlights", "football", "NBA", "UFC",
            "motorsport", "sports news",
        ],
        "interval_minutes": 180,
    },
    {
        # Gaming PRIORITY bumped 5→9 (2026-05-29): el usuario pidió foco
        # en consumo entretenimiento + videojuegos. Las fuentes nuevas
        # viven en apps.signals.market_signals (Steam Charts, OpenCritic, IGN,
        # Polygon, RPS, Eurogamer, reddit r/Games, reddit r/patientgamers).
        "cluster_name": "gaming",
        "display_name": "Gaming",
        "priority": 9,
        "seeds": [
            "gaming news", "new game release", "esports",
            "indie game", "steam sale", "tier list", "speedrun",
            "videojuegos", "game review", "metacritic",
        ],
        "rss_feeds": [
            "https://feeds.ign.com/ign/games-all",
            "https://www.polygon.com/rss/index.xml",
            "https://www.rockpapershotgun.com/feed",
            "https://www.eurogamer.net/feed",
            "https://opencritic.com/feed/rss",
        ],
        "interval_minutes": 120,
    },
    {
        # NUEVO 2026-05-29: foros y comunidad — cubre las 3 personas.
        # El market_signals.py ya hace fetch_reddit_hot por subreddit;
        # este cluster solo sirve para reporting/UI del scheduler.
        "cluster_name": "community_forums",
        "display_name": "Community & Forums",
        "priority": 8,
        "seeds": [
            "reddit hot", "fan reaction", "tier list",
            "fan theory", "discussion thread", "letterboxd review",
        ],
        "interval_minutes": 120,
    },
    {
        # NUEVO 2026-05-29: tracking de releases (anime/manga/movies).
        # Distinto a "gaming" porque el ritmo y las fuentes son otras.
        "cluster_name": "releases_tracker",
        "display_name": "Release Tracking",
        "priority": 8,
        "seeds": [
            "anime release", "manga chapter", "new movie",
            "trakt trending", "letterboxd weekly", "mangaupdates",
        ],
        "rss_feeds": [
            "https://www.mangaupdates.com/rss.php",
            "https://letterboxd.com/films/popular/this/week/rss/",
        ],
        "interval_minutes": 180,
    },
    {
        "cluster_name": "memes_viral",
        "display_name": "Memes & Viral",
        "priority": 6,
        "seeds": [
            "viral meme", "trending hashtag", "viral video",
            "internet challenge", "trending meme",
        ],
        "interval_minutes": 120,
    },
    {
        "cluster_name": "fashion_lifestyle",
        "display_name": "Fashion & Lifestyle",
        "priority": 3,
        "seeds": [
            "fashion week", "streetwear", "sneakers",
            "beauty trends", "fashion trends",
        ],
        "interval_minutes": 360,
    },
    {
        "cluster_name": "science_health",
        "display_name": "Science & Health",
        "priority": 5,
        "seeds": [
            "science news", "space", "medical breakthrough",
            "climate change", "health news",
        ],
        "interval_minutes": 240,
    },
    {
        "cluster_name": "business_finance",
        "display_name": "Business & Finance",
        "priority": 3,
        "seeds": [
            "stock market", "crypto", "business news",
            "economy", "finance tips",
        ],
        "interval_minutes": 360,
    },
    {
        "cluster_name": "latam_culture",
        "display_name": "LatAm Culture",
        "priority": 6,
        "seeds": [
            "novela trending", "musica latina", "regueton",
            "famosos latinos", "telenovela", "cine latino",
        ],
        "interval_minutes": 180,
    },
]


def seed_default_clusters(conn: sqlite3.Connection):
    """Ensure all default clusters exist in the database."""
    for cluster in DEFAULT_CLUSTERS:
        conn.execute(
            """INSERT OR IGNORE INTO topic_clusters
               (cluster_name, display_name, priority, seeds_json, interval_minutes)
               VALUES (?, ?, ?, ?, ?)""",
            (
                cluster["cluster_name"],
                cluster["display_name"],
                cluster["priority"],
                json.dumps(cluster["seeds"]),
                cluster["interval_minutes"],
            ),
        )
    conn.commit()
    log.info(f"Seeded {len(DEFAULT_CLUSTERS)} default topic clusters")
