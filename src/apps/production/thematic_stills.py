"""
Thematic Stills: bridge between thematic_classifier and panel_matcher.

Flow:
1. Detect themes in each narration segment
2. Query scene_moments DB for matching iconic moments in the current series
3. Download the TMDb episode stills for those moments
4. Return paths ready to add to panel_matcher's image pool

Example:
    Narration: "Griffith's betrayal destroyed everything"
      themes → [betrayal, corruption, ambition]
    Query: scene_moments WHERE series='berserk' AND themes ∩ [betrayal, ...] > 0
    Result: Ep25 "Advent" still → betrayal 0.95
    Download still → use as panel
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path

import requests

log = logging.getLogger(__name__)

CACHE_DIR = Path("data/thematic_stills")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ── Theme detection from narration ──────────────────────────────

THEME_KEYWORDS = {
    "betrayal": ["betray", "betrayal", "backstab", "turned on", "treason"],
    "sacrifice": ["sacrifice", "give up", "offer up", "abandon", "surrender"],
    "revenge": ["revenge", "vengeance", "payback", "avenge", "retribution"],
    "redemption": ["redeem", "redemption", "second chance", "make amends"],
    "ambition": ["ambition", "dream", "goal", "rise", "climb", "want more"],
    "corruption": ["corrupt", "twisted", "tainted", "fall", "rot"],
    "power": ["power", "strength", "force", "dominate", "control", "rule"],
    "identity": ["who am i", "self", "identity", "become", "mask"],
    "free_will": ["free will", "choice", "destiny", "fate", "decide"],
    "loneliness": ["alone", "lonely", "isolation", "solitude", "no one"],
    "loss": ["lost", "loss", "gone", "dead", "death", "mourn", "grief"],
    "obsession": ["obsession", "obsessed", "consumed", "fixated"],
    "madness": ["madness", "insane", "crazy", "lost his mind", "broken"],
    "trauma": ["trauma", "scar", "wound", "hurt", "pain", "suffer"],
    "existentialism": ["meaning", "purpose", "existence", "why", "nothing matters"],
    "love": ["love", "lover", "beloved", "heart", "romance"],
    "friendship": ["friend", "friendship", "companion", "ally"],
    "brotherhood": ["brother", "brotherhood", "family", "band", "crew"],
    "rivalry": ["rival", "rivalry", "opponent", "nemesis"],
    "mentorship": ["mentor", "teacher", "master", "guide", "wisdom"],
    "war": ["war", "battle", "fight", "combat", "conflict"],
    "survival": ["survive", "survival", "alive", "live through"],
    "hunt": ["hunt", "chase", "pursue", "prey"],
    "escape": ["escape", "run", "flee", "get away"],
    "coming_of_age": ["grew up", "childhood", "young", "adult", "mature"],
    "transformation": ["transform", "change", "become", "turn into"],
    "awakening": ["awake", "awaken", "realize", "understand", "enlighten"],
    "horror": ["horror", "terror", "nightmare", "fear"],
    "apocalypse": ["end of world", "apocalypse", "doomsday", "extinction"],
    "nihilism": ["meaningless", "nothing", "void", "empty"],
    "cycle_of_violence": ["cycle", "again and again", "never ends", "repeat"],
}


def detect_themes(text: str, max_themes: int = 5) -> list[str]:
    """
    Detect deep themes in a narration segment.

    Returns list of theme names (from the 35-theme vocabulary), sorted by
    keyword hits descending.
    """
    text_lower = text.lower()
    scores = {}

    for theme, keywords in THEME_KEYWORDS.items():
        hits = 0
        for kw in keywords:
            # Word boundary for single words, substring for phrases
            if " " in kw:
                if kw in text_lower:
                    hits += 1
            else:
                if re.search(r"\b" + re.escape(kw) + r"\b", text_lower):
                    hits += 1
        if hits > 0:
            scores[theme] = hits

    sorted_themes = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [t for t, _ in sorted_themes[:max_themes]]


# ── DB query + still download ───────────────────────────────────

def _download_still(url: str, out_dir: Path, prefix: str) -> str | None:
    """Download a TMDb still image."""
    if not url:
        return None

    try:
        ext = Path(url).suffix or ".jpg"
        out_path = out_dir / f"{prefix}{ext}"
        if out_path.exists() and out_path.stat().st_size > 1000:
            return str(out_path)

        resp = requests.get(url, timeout=20, headers={"User-Agent": "YouLikeIt/1.0"})
        if resp.status_code != 200 or len(resp.content) < 1000:
            return None

        out_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(resp.content)
        return str(out_path)
    except Exception as e:
        log.debug(f"Still download failed: {e}")
        return None


def get_thematic_stills_for_segment(
    conn: sqlite3.Connection,
    segment_text: str,
    series_slug: str,
    max_candidates: int = 1,
    min_overlap: int = 1,
    use_fandom: bool = True,
) -> list[dict]:
    """
    For a narration segment, find and download the best thematic stills.

    Priority order:
    1. Fandom wiki (named iconic scenes — highest quality match)
    2. TMDb episode still (generic episode screenshot — fallback)

    Returns list of {path, moment_description, themes, episode_number, score}.
    """
    themes = detect_themes(segment_text)
    if not themes:
        return []

    # Query scene_moments for this series with theme overlap
    rows = conn.execute(
        "SELECT * FROM scene_moments WHERE series_slug = ? ORDER BY iconic_score DESC",
        (series_slug,),
    ).fetchall()

    if not rows:
        return []

    scored = []
    for r in rows:
        d = dict(r)
        try:
            moment_themes = json.loads(d.get("themes") or "[]")
        except Exception:
            moment_themes = []

        overlap = len(set(themes) & set(moment_themes))
        if overlap < min_overlap:
            continue

        d["matched_themes"] = list(set(themes) & set(moment_themes))
        d["score"] = overlap + d.get("iconic_score", 0)
        scored.append(d)

    scored.sort(key=lambda x: x["score"], reverse=True)
    results = []

    for moment in scored[:max_candidates]:
        ep_num = moment.get("episode_number")
        season_num = moment.get("season_number", 1)
        slug = re.sub(r"[^a-z0-9]+", "_", series_slug)

        path = None
        source = None

        # 1. Try Fandom wiki first (named iconic scenes = much better match)
        if use_fandom and ep_num:
            try:
                from integrations.fandom_scraper import download_episode_iconic_scenes
                fandom_paths = download_episode_iconic_scenes(
                    series_slug, ep_num, season_num, max_images=2,
                )
                if fandom_paths:
                    path = fandom_paths[0]
                    source = "fandom"
            except Exception as e:
                log.debug(f"Fandom scrape failed: {e}")

        # 2. Fall back to TMDb still_url
        if not path and moment.get("still_url"):
            prefix = f"{slug}_s{season_num}e{ep_num or 0}"
            path = _download_still(
                moment["still_url"], CACHE_DIR / slug, prefix,
            )
            if path:
                source = "tmdb"

        if path:
            results.append({
                "path": path,
                "source": source,
                "moment_description": moment.get("moment_description", ""),
                "themes": moment.get("matched_themes", []),
                "all_themes": moment.get("themes", []),
                "episode_number": ep_num,
                "episode_name": moment.get("episode_name", ""),
                "emotion": moment.get("emotion"),
                "quote": moment.get("quote", ""),
                "score": moment["score"],
            })

    return results


def get_thematic_stills_for_narration(
    conn: sqlite3.Connection,
    narration_segments: list[dict],
    series_slug: str,
    max_per_segment: int = 1,
) -> list[str]:
    """
    For all narration segments, collect thematic stills (deduplicated).

    Returns list of local image paths ready to merge into panel_matcher pool.
    """
    all_paths = []
    seen = set()

    for seg in narration_segments:
        text = seg.get("text", seg.get("narration_text", ""))
        stills = get_thematic_stills_for_segment(
            conn, text, series_slug, max_candidates=max_per_segment,
        )

        for s in stills:
            if s["path"] in seen:
                continue
            seen.add(s["path"])
            all_paths.append(s["path"])
            src = s.get("source", "?")
            log.info(
                f"  Thematic [{src}]: '{text[:40]}' -> Ep{s['episode_number']} "
                f"(themes: {s['themes']}, score: {s['score']:.2f})"
            )

    log.info(f"  Collected {len(all_paths)} thematic stills")
    return all_paths


def ensure_series_classified(
    conn: sqlite3.Connection,
    series_title: str,
    tmdb_id: int = 0,
    slug: str | None = None,
) -> str:
    """
    Ensure a series has been classified (cached in DB). If not, classify it.
    Returns the canonical slug.
    """
    from apps.content.thematic_classifier import classify_series_full

    slug = slug or re.sub(r"[^a-z0-9]+", "_", series_title.lower()).strip("_")

    # Check if already classified
    existing = conn.execute(
        "SELECT id FROM series_themes WHERE series_slug = ?", (slug,),
    ).fetchone()

    has_moments = conn.execute(
        "SELECT COUNT(*) FROM scene_moments WHERE series_slug = ?", (slug,),
    ).fetchone()[0]

    if existing and has_moments > 0:
        log.info(f"  Series '{slug}' already classified ({has_moments} moments)")
        return slug

    log.info(f"  Classifying '{series_title}' (first time)...")
    classify_series_full(conn, series_title, tmdb_id=tmdb_id, slug=slug)
    return slug
