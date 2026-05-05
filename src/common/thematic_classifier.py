"""
Thematic Classifier: 3-level deep classification of manga/anime/series content.

Levels:
1. SERIES    — The manga/series as a whole (themes, archetypes, tone)
2. ARC       — Individual arcs/seasons (Eclipse Arc in Berserk, Fear Arc in Attack on Titan)
3. EPISODE   — Specific episodes/chapters with iconic moments

Why this matters:
- Narration about "betrayal" → best matches with an Eclipse Arc panel, not any Berserk panel
- Narration about "obsession" → Walter White S5 > Walter White S1
- Panel matcher uses these tags as additional signal beyond visual similarity

Uses Gemini as LLM, with heuristic fallback.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path

import requests

log = logging.getLogger(__name__)

CACHE_DIR = Path("data/thematic_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ── Controlled vocabulary: deep themes beyond genres ────────────

DEEP_THEMES = {
    # Moral / philosophical
    "betrayal": {"emotion": "dark", "archetype": "traitor"},
    "sacrifice": {"emotion": "tragic", "archetype": "martyr"},
    "revenge": {"emotion": "dark", "archetype": "avenger"},
    "redemption": {"emotion": "hopeful", "archetype": "redeemer"},
    "ambition": {"emotion": "epic", "archetype": "climber"},
    "corruption": {"emotion": "dark", "archetype": "fallen"},
    "power": {"emotion": "epic", "archetype": "tyrant"},
    "identity": {"emotion": "dark", "archetype": "seeker"},
    "free_will": {"emotion": "dark", "archetype": "rebel"},

    # Human condition
    "loneliness": {"emotion": "tragic", "archetype": "isolated"},
    "loss": {"emotion": "tragic", "archetype": "grieving"},
    "obsession": {"emotion": "dark", "archetype": "obsessed"},
    "madness": {"emotion": "dark", "archetype": "fractured"},
    "trauma": {"emotion": "tragic", "archetype": "wounded"},
    "existentialism": {"emotion": "dark", "archetype": "questioner"},

    # Relationships
    "love": {"emotion": "hopeful", "archetype": "lover"},
    "friendship": {"emotion": "hopeful", "archetype": "companion"},
    "brotherhood": {"emotion": "epic", "archetype": "brother_in_arms"},
    "family": {"emotion": "hopeful", "archetype": "parent_child"},
    "rivalry": {"emotion": "epic", "archetype": "rival"},
    "mentorship": {"emotion": "hopeful", "archetype": "teacher"},

    # Conflict
    "war": {"emotion": "epic", "archetype": "soldier"},
    "survival": {"emotion": "tragic", "archetype": "survivor"},
    "hunt": {"emotion": "dark", "archetype": "hunter"},
    "escape": {"emotion": "tragic", "archetype": "fugitive"},

    # Growth
    "coming_of_age": {"emotion": "hopeful", "archetype": "youth"},
    "transformation": {"emotion": "epic", "archetype": "changer"},
    "awakening": {"emotion": "hopeful", "archetype": "awakened"},

    # Dark
    "horror": {"emotion": "dark", "archetype": "victim"},
    "apocalypse": {"emotion": "tragic", "archetype": "doomed"},
    "nihilism": {"emotion": "dark", "archetype": "nihilist"},
    "cycle_of_violence": {"emotion": "tragic", "archetype": "cursed"},
}


# ── DB Schema ───────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS series_themes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    series_slug TEXT UNIQUE NOT NULL,
    series_title TEXT NOT NULL,
    tmdb_id INTEGER,
    anilist_id INTEGER,
    primary_themes TEXT,      -- JSON list of top 3-5 deep themes
    secondary_themes TEXT,    -- JSON list of supporting themes
    dominant_emotion TEXT,
    archetype_primary TEXT,   -- protagonist archetype
    archetype_antagonist TEXT,
    tonal_profile TEXT,       -- JSON: {epic: 0.8, tragic: 0.9, ...}
    classified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source TEXT DEFAULT 'llm'
);

CREATE TABLE IF NOT EXISTS series_arcs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    series_slug TEXT NOT NULL,
    arc_name TEXT NOT NULL,
    arc_order INTEGER,
    episode_start INTEGER,
    episode_end INTEGER,
    season_number INTEGER,
    themes TEXT,              -- JSON list
    dominant_emotion TEXT,
    synopsis TEXT,
    iconic_moments TEXT,      -- JSON list of {moment, emotion, quote}
    UNIQUE(series_slug, arc_name)
);

CREATE TABLE IF NOT EXISTS scene_moments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    series_slug TEXT NOT NULL,
    season_number INTEGER,
    episode_number INTEGER,
    episode_name TEXT,
    iconic_score REAL DEFAULT 0.5,
    themes TEXT,              -- JSON list
    emotion TEXT,
    moment_description TEXT,
    quote TEXT,
    still_url TEXT,
    local_still_path TEXT
);

CREATE INDEX IF NOT EXISTS idx_series_themes_slug ON series_themes(series_slug);
CREATE INDEX IF NOT EXISTS idx_arcs_slug ON series_arcs(series_slug);
CREATE INDEX IF NOT EXISTS idx_scenes_slug ON scene_moments(series_slug);
"""


def init_db(conn: sqlite3.Connection):
    conn.executescript(SCHEMA)
    conn.commit()


# ── Level 1: Series-level classification ────────────────────────

def classify_series(
    series_title: str,
    description: str = "",
    genres: list[str] | None = None,
    keywords: list[str] | None = None,
    reviews: list[str] | None = None,
) -> dict:
    """
    Classify a series into deep themes + archetypes + tonal profile.

    Returns: {
        primary_themes: [...],
        secondary_themes: [...],
        dominant_emotion: "...",
        archetype_primary: "...",
        archetype_antagonist: "...",
        tonal_profile: {epic: 0.8, tragic: 0.9, ...}
    }
    """
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    if not gemini_key:
        return _classify_heuristic(series_title, description, genres, keywords)

    theme_list = ", ".join(DEEP_THEMES.keys())
    emotions = "dark | epic | tragic | hopeful | shock"

    reviews_text = ""
    if reviews:
        reviews_text = "\n\nREVIEWS:\n" + "\n".join(f"- {r[:200]}" for r in reviews[:3])

    prompt = f"""Classify this series by DEEP themes (not genres).

SERIES: {series_title}
GENRES: {', '.join(genres or [])}
KEYWORDS: {', '.join(keywords or [])}
DESCRIPTION: {description}{reviews_text}

ALLOWED THEMES (choose only from this list):
{theme_list}

ALLOWED EMOTIONS: {emotions}

Return JSON (no markdown):
{{
  "primary_themes": ["theme1", "theme2", "theme3"],
  "secondary_themes": ["theme4", "theme5"],
  "dominant_emotion": "tragic",
  "archetype_primary": "what the protagonist represents (e.g., 'tormented warrior')",
  "archetype_antagonist": "what the main antagonist represents",
  "tonal_profile": {{
    "epic": 0.0 to 1.0,
    "tragic": 0.0 to 1.0,
    "dark": 0.0 to 1.0,
    "hopeful": 0.0 to 1.0
  }}
}}"""

    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gemini_key}",
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.3, "maxOutputTokens": 500},
            },
            timeout=20,
        )
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        text = re.sub(r"```json?\s*", "", text).strip().rstrip("`")
        return json.loads(text)
    except Exception as e:
        log.warning(f"LLM series classify failed for {series_title}: {e}")
        return _classify_heuristic(series_title, description, genres, keywords)


def _classify_heuristic(
    title: str,
    description: str,
    genres: list[str] | None,
    keywords: list[str] | None,
) -> dict:
    """Fallback: detect themes from keyword matching."""
    text = f"{title} {description} {' '.join(genres or [])} {' '.join(keywords or [])}".lower()

    found_themes = []
    for theme in DEEP_THEMES:
        theme_variants = [theme, theme.replace("_", " "), theme.replace("_", "-")]
        if any(v in text for v in theme_variants):
            found_themes.append(theme)

    # Keyword → theme inference
    keyword_map = {
        "war": "war", "battle": "war",
        "curse": "corruption", "possession": "corruption",
        "supernatural": "horror", "demon": "horror",
        "friendship": "friendship", "team": "brotherhood",
        "family": "family", "father": "family", "mother": "family",
        "revenge": "revenge", "vengeance": "revenge",
        "tragedy": "loss", "death": "loss",
        "sacrifice": "sacrifice",
        "betray": "betrayal",
        "school": "coming_of_age", "teen": "coming_of_age",
    }

    for kw, theme in keyword_map.items():
        if kw in text and theme not in found_themes:
            found_themes.append(theme)

    primary = found_themes[:3] if found_themes else ["identity"]
    secondary = found_themes[3:6]

    # Infer emotion from primary theme
    emotion = DEEP_THEMES.get(primary[0], {}).get("emotion", "dark") if primary else "dark"
    archetype_primary = DEEP_THEMES.get(primary[0], {}).get("archetype", "seeker") if primary else "seeker"

    return {
        "primary_themes": primary,
        "secondary_themes": secondary,
        "dominant_emotion": emotion,
        "archetype_primary": archetype_primary,
        "archetype_antagonist": "unknown",
        "tonal_profile": {"dark": 0.7, "tragic": 0.5, "epic": 0.5, "hopeful": 0.3},
        "source": "heuristic",
    }


def save_series_classification(conn: sqlite3.Connection, series_slug: str, series_title: str, classification: dict, tmdb_id: int = 0):
    """Save series classification to DB."""
    init_db(conn)
    conn.execute("""
        INSERT OR REPLACE INTO series_themes
        (series_slug, series_title, tmdb_id,
         primary_themes, secondary_themes, dominant_emotion,
         archetype_primary, archetype_antagonist, tonal_profile,
         classified_at, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        series_slug, series_title, tmdb_id,
        json.dumps(classification.get("primary_themes", []), ensure_ascii=False),
        json.dumps(classification.get("secondary_themes", []), ensure_ascii=False),
        classification.get("dominant_emotion", ""),
        classification.get("archetype_primary", ""),
        classification.get("archetype_antagonist", ""),
        json.dumps(classification.get("tonal_profile", {}), ensure_ascii=False),
        datetime.utcnow().isoformat(),
        classification.get("source", "llm"),
    ))
    conn.commit()


# ── Level 2: Arc/Season classification ──────────────────────────

def classify_arcs_from_seasons(
    series_title: str,
    seasons: list[dict],
) -> list[dict]:
    """
    Given TMDb seasons list, classify each as an arc with themes.

    seasons: [{season_number, name, overview, episode_count}]
    """
    arcs = []
    for s in seasons:
        if not s.get("overview"):
            continue
        classification = classify_series(
            series_title=f"{series_title} - {s.get('name', 'Season ' + str(s['season_number']))}",
            description=s["overview"],
        )
        arcs.append({
            "arc_name": s.get("name", f"Season {s['season_number']}"),
            "season_number": s["season_number"],
            "synopsis": s["overview"],
            "themes": classification.get("primary_themes", []),
            "dominant_emotion": classification.get("dominant_emotion", "dark"),
        })
    return arcs


# ── Level 3: Episode/scene moment extraction ────────────────────

def _attach_stills_to_moments(moments: list[dict], episodes: list[dict]) -> list[dict]:
    """Attach the TMDb still URL to each moment based on episode_number match."""
    ep_map = {e.get("episode_number"): e.get("still") for e in episodes if e.get("still")}
    for m in moments:
        ep_num = m.get("episode_number")
        if ep_num in ep_map:
            m["still_url"] = ep_map[ep_num]
    return moments


def extract_iconic_moments(
    series_title: str,
    season_number: int,
    episodes: list[dict],
    max_moments: int = 5,
) -> list[dict]:
    """
    Identify the most iconic moments across episodes.

    Uses LLM to rate each episode's overview by iconic-ness and extract scenes.
    """
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    if not gemini_key or not episodes:
        return []

    # Build compact episode list (filter only by having overview)
    ep_lines = []
    for e in episodes:
        if e.get("overview"):
            ep_lines.append(f"Ep{e['episode_number']} ({e.get('vote_average', 0):.1f}): {e['name']} — {e['overview'][:150]}")

    if not ep_lines:
        log.info(f"  No episodes with overview for {series_title} S{season_number}")
        return []

    prompt = f"""From the following episodes of "{series_title}" Season {season_number},
identify the {max_moments} most ICONIC / VIRAL / EMOTIONALLY IMPACTFUL moments.

Episodes:
{chr(10).join(ep_lines[:30])}

Return JSON array (no markdown). For each iconic moment:
{{
  "episode_number": int,
  "episode_name": "...",
  "moment_description": "brief description of the iconic moment",
  "quote": "famous quote or key line (if known)",
  "themes": ["theme1", "theme2"],  // from: betrayal, sacrifice, revenge, love, etc
  "emotion": "dark|epic|tragic|hopeful|shock",
  "iconic_score": 0.0 to 1.0
}}"""

    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gemini_key}",
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.4, "maxOutputTokens": 1500},
            },
            timeout=30,
        )
        if resp.status_code != 200:
            log.warning(f"Gemini returned {resp.status_code}: {resp.text[:200]}")
            return []
        rj = resp.json()
        candidates = rj.get("candidates", [])
        if not candidates:
            log.warning(f"Gemini returned no candidates: {rj}")
            return []
        text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        if not text:
            log.warning(f"Empty text from Gemini. Finish reason: {candidates[0].get('finishReason')}")
            return []
        result = _extract_json_array(text)
        if not result:
            log.warning(f"Could not parse moments from LLM response (first 300 chars): {text[:300]}")
        else:
            result = _attach_stills_to_moments(result, episodes)
        return result
    except Exception as e:
        log.warning(f"Iconic moments extraction failed: {e}")
        return []


def _extract_json_array(text: str) -> list:
    """Robust JSON array extraction — handles preamble/code fences/trailing text."""
    # Try markdown fence first
    m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, flags=re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass

    # Find the first [ and last ] and try that
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            pass

    # Nothing worked
    log.warning(f"Could not parse JSON array from: {text[:200]}")
    return []


def save_scene_moments(
    conn: sqlite3.Connection,
    series_slug: str,
    moments: list[dict],
    season_number: int = 1,
):
    """Save extracted iconic moments to DB."""
    init_db(conn)
    for m in moments:
        conn.execute("""
            INSERT INTO scene_moments
            (series_slug, season_number, episode_number, episode_name,
             iconic_score, themes, emotion, moment_description, quote, still_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            series_slug, season_number,
            m.get("episode_number", 0), m.get("episode_name", ""),
            m.get("iconic_score", 0.5),
            json.dumps(m.get("themes", []), ensure_ascii=False),
            m.get("emotion", "dark"),
            m.get("moment_description", ""),
            m.get("quote", ""),
            m.get("still_url", ""),
        ))
    conn.commit()


# ── Full series classification (all 3 levels) ──────────────────

def classify_series_full(
    conn: sqlite3.Connection,
    series_title: str,
    tmdb_id: int = 0,
    slug: str | None = None,
) -> dict:
    """
    Do the full 3-level classification for a series using TMDb data.

    1. Fetch enriched TMDb data
    2. Classify series overall (themes, archetype, tonal profile)
    3. Classify each season as an arc
    4. Extract iconic moments per season
    """
    from common.tmdb_enriched import get_enriched_series, get_season_episodes

    slug = slug or re.sub(r"[^a-z0-9]+", "_", series_title.lower()).strip("_")

    log.info(f"\n=== Classifying {series_title} (slug={slug}) ===")

    # 1. Get TMDb data
    if not tmdb_id:
        # Try to find it
        key = os.getenv("TMDB_API_KEY", "")
        resp = requests.get(
            "https://api.themoviedb.org/3/search/tv",
            params={"api_key": key, "query": series_title},
            timeout=10,
        )
        results = resp.json().get("results", [])
        if not results:
            log.warning(f"  Not found on TMDb: {series_title}")
            return {}
        tmdb_id = results[0]["id"]

    log.info(f"  TMDb ID: {tmdb_id}")
    data = get_enriched_series(tmdb_id)
    if not data:
        return {}

    # 2. Series-level
    log.info("  Classifying series...")
    classification = classify_series(
        series_title=data["title"],
        description=data["overview"],
        genres=data.get("genres", []),
        keywords=data.get("keywords", []),
        reviews=[r.get("content", "") for r in data.get("reviews", [])[:3]],
    )
    save_series_classification(conn, slug, data["title"], classification, tmdb_id)
    log.info(f"    Themes: {classification.get('primary_themes', [])}")
    log.info(f"    Emotion: {classification.get('dominant_emotion', '')}")

    # 3. Arcs (seasons)
    log.info("  Classifying arcs...")
    arcs = classify_arcs_from_seasons(data["title"], data.get("seasons", []))
    for arc in arcs:
        conn.execute("""
            INSERT OR IGNORE INTO series_arcs
            (series_slug, arc_name, arc_order, season_number, themes, dominant_emotion, synopsis)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            slug, arc["arc_name"], arc["season_number"], arc["season_number"],
            json.dumps(arc["themes"], ensure_ascii=False),
            arc["dominant_emotion"], arc["synopsis"],
        ))
        log.info(f"    Arc: {arc['arc_name'][:40]} → {arc['themes']}")
    conn.commit()

    # 4. Iconic moments per season (only S1 to save API calls)
    log.info("  Extracting iconic moments (S1)...")
    episodes = get_season_episodes(tmdb_id, 1)
    moments = extract_iconic_moments(data["title"], 1, episodes, max_moments=5)
    save_scene_moments(conn, slug, moments, season_number=1)
    for m in moments:
        log.info(f"    Ep{m.get('episode_number', '?')}: {m.get('moment_description', '')[:60]}")

    return {
        "series": classification,
        "arcs": arcs,
        "moments": moments,
    }


# ── Query API for panel matcher ─────────────────────────────────

def get_series_themes(conn: sqlite3.Connection, series_slug: str) -> dict | None:
    """Get classification for a series (for panel_matcher scoring)."""
    init_db(conn)
    row = conn.execute(
        "SELECT * FROM series_themes WHERE series_slug = ?",
        (series_slug,),
    ).fetchone()
    if not row:
        return None

    d = dict(row)
    for field in ("primary_themes", "secondary_themes", "tonal_profile"):
        if d.get(field):
            try:
                d[field] = json.loads(d[field])
            except Exception:
                pass
    return d


def get_moments_by_themes(
    conn: sqlite3.Connection,
    series_slug: str,
    themes: list[str],
    min_score: float = 0.4,
) -> list[dict]:
    """Find iconic moments that match a set of themes."""
    init_db(conn)
    rows = conn.execute(
        "SELECT * FROM scene_moments WHERE series_slug = ? AND iconic_score >= ?",
        (series_slug, min_score),
    ).fetchall()

    scored = []
    for r in rows:
        d = dict(r)
        try:
            moment_themes = json.loads(d.get("themes") or "[]")
        except Exception:
            moment_themes = []
        d["themes"] = moment_themes
        overlap = len(set(themes) & set(moment_themes))
        d["theme_overlap"] = overlap
        scored.append(d)

    scored.sort(key=lambda x: (x["theme_overlap"], x["iconic_score"]), reverse=True)
    return scored
