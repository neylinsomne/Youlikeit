"""
Content Rotator: decides which series to produce next.

Selection strategy:
1. Series that have NOT been produced for N days (freshness)
2. Weighted by trending score (AniList trending rank)
3. Weighted by classification completeness (themes + moments available)
4. Cycles through personas so each one gets different series

Rotation rules:
- Same persona should NOT repeat the same series within 14 days
- Across all personas, prefer diverse series (don't make 3 Berserk videos same day)
- Trending series get bonus weight (they capture current viewer interest)
- If a series hasn't been classified yet, classify first, then queue

DB tables used:
- series_themes (from thematic_classifier) — classified series
- scene_moments — iconic moments per series
- content_schedule (new) — history of what's been produced when

Usage:
    rotator = ContentRotator()
    next_series = rotator.pick_next("deep_mind")
    # → {"slug": "vinland_saga", "title": "Vinland Saga", "tmdb_id": 64196, ...}
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta

log = logging.getLogger(__name__)


# ── Curated pool of series we CAN produce for ───────────────────
# Must have: TMDb ID + available on Fandom wiki OR MangaDex

CATALOG = {
    # — Seinen/Dark themes (perfect for Deep Mind) —
    "berserk": {
        "title": "Berserk: The Golden Age Arc",
        "tmdb_id": 211057,
        "primary_personas": ["deep_mind"],
        "tags": ["seinen", "dark", "philosophical"],
    },
    "jujutsu_kaisen": {
        "title": "Jujutsu Kaisen",
        "tmdb_id": 95479,
        "primary_personas": ["deep_mind", "pop_oracle"],
        "tags": ["action", "supernatural", "trending"],
    },
    "attack_on_titan": {
        "title": "Attack on Titan",
        "tmdb_id": 1429,
        "primary_personas": ["deep_mind"],
        "tags": ["dark", "political", "tragic"],
    },
    "vinland_saga": {
        "title": "Vinland Saga",
        "tmdb_id": 64196,
        "primary_personas": ["deep_mind"],
        "tags": ["seinen", "historical", "philosophical"],
    },
    "monster": {
        "title": "Monster",
        "tmdb_id": 36493,
        "primary_personas": ["deep_mind"],
        "tags": ["psychological", "thriller", "seinen"],
    },
    "death_note": {
        "title": "Death Note",
        "tmdb_id": 13916,
        "primary_personas": ["deep_mind", "pop_oracle"],
        "tags": ["psychological", "supernatural", "iconic"],
    },
    "neon_genesis_evangelion": {
        "title": "Neon Genesis Evangelion",
        "tmdb_id": 30991,
        "primary_personas": ["deep_mind"],
        "tags": ["mecha", "psychological", "seminal"],
    },
    "cowboy_bebop": {
        "title": "Cowboy Bebop",
        "tmdb_id": 30991,
        "primary_personas": ["deep_mind"],
        "tags": ["seinen", "philosophical", "seminal"],
    },
    # — Trending/action (Pop Oracle material) —
    "chainsaw_man": {
        "title": "Chainsaw Man",
        "tmdb_id": 114410,
        "primary_personas": ["pop_oracle"],
        "tags": ["trending", "action", "edgy"],
    },
    "solo_leveling": {
        "title": "Solo Leveling",
        "tmdb_id": 127532,
        "primary_personas": ["pop_oracle"],
        "tags": ["trending", "action", "power-fantasy"],
    },
    "frieren": {
        "title": "Frieren: Beyond Journey's End",
        "tmdb_id": 209867,
        "primary_personas": ["pop_oracle", "deep_mind"],
        "tags": ["trending", "fantasy", "contemplative"],
    },
    "oshi_no_ko": {
        "title": "Oshi no Ko",
        "tmdb_id": 203857,
        "primary_personas": ["pop_oracle"],
        "tags": ["trending", "idol", "meta"],
    },
    "one_piece": {
        "title": "One Piece",
        "tmdb_id": 37854,
        "primary_personas": ["pop_oracle"],
        "tags": ["shonen", "mainstream", "long-running"],
    },
    # — LatAm telenovelas / Voz Latina —
    "yo_soy_betty_la_fea": {
        "title": "Yo soy Betty, la fea",
        "tmdb_id": 71220,
        "primary_personas": ["latam"],
        "tags": ["telenovela", "colombia", "iconic"],
    },
    "la_casa_de_las_flores": {
        "title": "La Casa de las Flores",
        "tmdb_id": 76315,
        "primary_personas": ["latam"],
        "tags": ["telenovela", "mexico", "modern"],
    },
    "pasion_de_gavilanes": {
        "title": "Pasión de Gavilanes",
        "tmdb_id": 36648,
        "primary_personas": ["latam"],
        "tags": ["telenovela", "colombia", "iconic"],
    },
    "el_senor_de_los_cielos": {
        "title": "El Señor de los Cielos",
        "tmdb_id": 39391,
        "primary_personas": ["latam"],
        "tags": ["narco", "mexico", "drama"],
    },
}


# ── DB schema for rotation history ──────────────────────────────

ROTATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS content_produced (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    persona TEXT NOT NULL,
    series_slug TEXT NOT NULL,
    series_title TEXT NOT NULL,
    video_type TEXT NOT NULL,
    produced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    youtube_id TEXT,
    tiktok_id TEXT,
    script_json TEXT,
    output_path TEXT
);
CREATE INDEX IF NOT EXISTS idx_produced_persona_series ON content_produced(persona, series_slug);
CREATE INDEX IF NOT EXISTS idx_produced_at ON content_produced(produced_at);
"""


def init_rotation_db(conn: sqlite3.Connection):
    conn.executescript(ROTATION_SCHEMA)
    conn.commit()


def log_produced(
    conn: sqlite3.Connection,
    persona: str,
    series_slug: str,
    series_title: str,
    video_type: str,
    output_path: str = "",
    youtube_id: str = "",
    tiktok_id: str = "",
    script: dict | None = None,
):
    """Record that a video was produced (used for future rotation decisions)."""
    init_rotation_db(conn)
    conn.execute("""
        INSERT INTO content_produced
        (persona, series_slug, series_title, video_type, output_path,
         youtube_id, tiktok_id, script_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        persona, series_slug, series_title, video_type, output_path,
        youtube_id, tiktok_id,
        json.dumps(script or {}, ensure_ascii=False),
    ))
    conn.commit()


# ── Rotation logic ──────────────────────────────────────────────

class ContentRotator:
    def __init__(self, db_path: str = "data/shorts_pipeline.db"):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        init_rotation_db(self.conn)

    def _days_since_last(self, persona: str, slug: str) -> float:
        """How many days since this persona last produced this series?"""
        row = self.conn.execute("""
            SELECT MAX(produced_at) as last FROM content_produced
            WHERE persona = ? AND series_slug = ?
        """, (persona, slug)).fetchone()

        if not row or not row["last"]:
            return 999  # Never produced — max freshness
        try:
            last = datetime.fromisoformat(row["last"].replace("Z", ""))
        except Exception:
            return 999
        return (datetime.utcnow() - last).total_seconds() / 86400

    def _is_classified(self, slug: str) -> bool:
        """Does this series have themes + moments classified?"""
        row = self.conn.execute(
            "SELECT COUNT(*) as c FROM scene_moments WHERE series_slug = ?",
            (slug,),
        ).fetchone()
        return bool(row and row["c"] > 0)

    def _trending_bonus(self, slug: str) -> float:
        """Extra weight if the series is in current trending cache."""
        try:
            from common.trending_anime import get_trending_titles
            trending = get_trending_titles(top_n=15, use_cache=True)
            for i, t in enumerate(trending):
                t_slug = t.get("title", "").lower().replace(" ", "_").replace(":", "")
                if slug in t_slug or t_slug in slug:
                    return 0.5 - (i * 0.03)  # Top 1 = +0.5, decreases
        except Exception:
            pass
        return 0.0

    def score_candidate(
        self,
        persona: str,
        slug: str,
        min_days_cooldown: int = 14,
    ) -> float:
        """
        Compute rotation score for (persona, series).

        Higher = better pick.
        """
        catalog_entry = CATALOG.get(slug)
        if not catalog_entry:
            return 0.0

        # Persona affinity — is this series in their wheelhouse?
        if persona in catalog_entry.get("primary_personas", []):
            persona_weight = 1.0
        else:
            # Cross-persona test (e.g., Deep Mind trying Oshi no Ko)
            persona_weight = 0.4

        # Freshness: cooldown must have passed
        days = self._days_since_last(persona, slug)
        if days < min_days_cooldown:
            return 0.0  # Too recent — skip

        freshness = min(days / 30, 1.0)  # Capped at 1.0 after 30 days

        # Trending bonus
        trending_bonus = self._trending_bonus(slug)

        # Classified bonus (ready to produce, no delay)
        classified_bonus = 0.3 if self._is_classified(slug) else 0.0

        return (persona_weight * 0.5) + (freshness * 0.4) + trending_bonus + classified_bonus

    def pick_next(
        self,
        persona: str,
        exclude: list[str] | None = None,
        min_days_cooldown: int = 14,
    ) -> dict | None:
        """Pick the next series for this persona."""
        exclude = exclude or []

        candidates = []
        for slug, entry in CATALOG.items():
            if slug in exclude:
                continue
            score = self.score_candidate(persona, slug, min_days_cooldown)
            if score > 0:
                candidates.append({
                    "slug": slug,
                    "title": entry["title"],
                    "tmdb_id": entry["tmdb_id"],
                    "tags": entry.get("tags", []),
                    "score": round(score, 3),
                    "days_since_last": round(self._days_since_last(persona, slug), 1),
                    "classified": self._is_classified(slug),
                })

        candidates.sort(key=lambda c: c["score"], reverse=True)
        return candidates[0] if candidates else None

    def plan_batch(
        self,
        personas: list[str] | None = None,
        min_days_cooldown: int = 14,
    ) -> list[dict]:
        """
        Plan a batch: one series per persona, diverse across personas.
        Returns list of {persona, slug, title, tmdb_id, score}.
        """
        personas = personas or ["deep_mind", "pop_oracle", "latam"]
        batch = []
        used_slugs = set()

        for persona in personas:
            pick = self.pick_next(
                persona, exclude=list(used_slugs),
                min_days_cooldown=min_days_cooldown,
            )
            if pick:
                pick["persona"] = persona
                batch.append(pick)
                used_slugs.add(pick["slug"])

        return batch

    def get_production_history(self, days: int = 30) -> list[dict]:
        """Recent production log."""
        rows = self.conn.execute("""
            SELECT * FROM content_produced
            WHERE produced_at > datetime('now', ?)
            ORDER BY produced_at DESC
        """, (f"-{days} days",)).fetchall()
        return [dict(r) for r in rows]

    def close(self):
        self.conn.close()


# ── CLI helper ──────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    rotator = ContentRotator()

    print("\n=== ROTATION PLAN ===\n")
    batch = rotator.plan_batch()
    for item in batch:
        print(f"  {item['persona']:12s} -> {item['slug']:30s} "
              f"score={item['score']:.2f}  "
              f"days_since={item['days_since_last']}  "
              f"classified={item['classified']}")

    print("\n=== TOP 5 CANDIDATES PER PERSONA ===\n")
    for persona in ["deep_mind", "pop_oracle", "latam"]:
        print(f"\n── {persona} ──")
        scored = []
        for slug in CATALOG:
            s = rotator.score_candidate(persona, slug, min_days_cooldown=0)
            if s > 0:
                scored.append((slug, s))
        scored.sort(key=lambda x: x[1], reverse=True)
        for slug, score in scored[:5]:
            classified = "✓" if rotator._is_classified(slug) else "—"
            print(f"  {slug:30s} score={score:.2f}  classified={classified}")

    rotator.close()
