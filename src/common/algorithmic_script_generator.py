"""
Algorithmic script generator — no LLM required.

Loads templates from data/script_templates/{narration,personality,test}.json
and fills slots ({character}, {series}, {keyword}) with values pulled from
the local database (series_themes, scene_moments) or the input series.

Selection is *deterministic per (series_slug, video_type, vtype)* using a
seeded PRNG, so re-running on the same series gives the same script. Pass
`seed_extra` to vary the output (useful for A/B testing two scripts on the
same series).

Output schema matches the existing LLM-based generator exactly:
    [
      {"text": "...", "emotion": "dark", "is_hook": true},
      {"text": "...", "emotion": "tragic"},
      ...
    ]

The first segment is always marked is_hook=True. The last segment is the
outro. Body length adapts to keep total runtime in the 25-50 second band.
"""

from __future__ import annotations

import json
import logging
import random
import re
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)

TEMPLATE_DIR = Path("data/script_templates")
VIDEO_TYPES = ("narration", "personality", "test")

# Default series-level fallbacks if DB has no classification yet
_FALLBACK_THEMES = ["default"]
_FALLBACK_EMOTION = "dark"
_FALLBACK_CHAR = "the protagonist"

# Mapping of vtype to body-segment count (approx 25-50s @ ~4s/segment)
_BODY_LEN = {"narration": 4, "personality": 4, "test": 4}


# ── Template loading ────────────────────────────────────────────

_template_cache: dict[str, dict] = {}


def _load_template(vtype: str) -> dict:
    """Load and cache the JSON template for a video type."""
    if vtype in _template_cache:
        return _template_cache[vtype]
    path = TEMPLATE_DIR / f"{vtype}.json"
    if not path.exists():
        raise FileNotFoundError(f"Template not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    _template_cache[vtype] = data
    return data


# ── DB context loading ──────────────────────────────────────────

def _load_context(
    conn: sqlite3.Connection | None,
    series_slug: str,
    series_title: str,
) -> dict:
    """Pull series themes + iconic moments + characters from DB. All optional."""
    ctx = {
        "series_title": series_title,
        "series_slug": series_slug,
        "themes": list(_FALLBACK_THEMES),
        "dominant_emotion": _FALLBACK_EMOTION,
        "moments": [],
        "main_character": _FALLBACK_CHAR,
    }
    if conn is None:
        return ctx

    try:
        row = conn.execute(
            "SELECT primary_themes, dominant_emotion, archetype_primary "
            "FROM series_themes WHERE series_slug = ?",
            (series_slug,),
        ).fetchone()
        if row:
            try:
                themes = json.loads(row[0]) if row[0] else []
            except Exception:
                themes = []
            if themes:
                ctx["themes"] = [str(t).lower() for t in themes]
            if row[1]:
                ctx["dominant_emotion"] = row[1]
    except sqlite3.Error:
        pass

    try:
        rows = conn.execute(
            "SELECT moment_description, themes, emotion, quote, episode_number "
            "FROM scene_moments WHERE series_slug = ? "
            "ORDER BY iconic_score DESC LIMIT 8",
            (series_slug,),
        ).fetchall()
        for r in rows:
            try:
                themes = json.loads(r[1]) if r[1] else []
            except Exception:
                themes = []
            ctx["moments"].append({
                "description": r[0] or "",
                "themes": [str(t).lower() for t in themes],
                "emotion": (r[2] or "dark").lower(),
                "quote": r[3] or "",
                "episode": r[4] or 0,
            })
    except sqlite3.Error:
        pass

    # Character heuristic: extract a likely name from the highest-iconic moment
    if ctx["moments"]:
        top_desc = ctx["moments"][0]["description"]
        ctx["main_character"] = _guess_character_from_text(top_desc) or _FALLBACK_CHAR

    return ctx


def _guess_character_from_text(text: str) -> str | None:
    """
    Pick the first capitalized word that is likely a character name.
    Skips sentence-initial words and common nouns.
    """
    if not text:
        return None
    SKIP = {
        "The", "A", "An", "This", "That", "It", "He", "She", "They", "We",
        "After", "Before", "When", "While", "During", "And", "But", "So",
        "Episode", "Season", "Arc", "Chapter", "Series",
    }
    words = re.findall(r"\b([A-Z][a-z]{2,})\b", text)
    for w in words:
        if w not in SKIP:
            return w
    return None


# ── Slot filling ────────────────────────────────────────────────

_SLOT_RE = re.compile(r"\{(\w+)\}")


def _fill_slots(template: str, slots: dict[str, str]) -> str:
    """Substitute {slot} placeholders with values from the slots dict."""
    def repl(m: re.Match) -> str:
        key = m.group(1)
        return str(slots.get(key, m.group(0)))
    return _SLOT_RE.sub(repl, template)


def _build_slots(ctx: dict) -> dict[str, str]:
    """Build the slot dictionary for template substitution."""
    series_title = ctx["series_title"]
    main_char = ctx["main_character"]
    themes = ctx["themes"]
    keyword = themes[0] if themes else "moment"
    return {
        "series": series_title,
        "character": main_char,
        "keyword": keyword,
        "emotion": ctx["dominant_emotion"],
    }


def _theme_for_body(themes: list[str], persona_bodies: dict) -> str:
    """Pick which theme bucket of bodies to use, falling back to 'default'."""
    available = set(persona_bodies.keys())
    for t in themes:
        if t in available:
            return t
    return "default"


# ── Main API ────────────────────────────────────────────────────

def generate_scripts_algorithmic(
    conn: sqlite3.Connection | None,
    series_slug: str,
    series_title: str,
    persona: str = "deep_mind",
    seed_extra: str = "",
) -> dict:
    """
    Generate scripts for all 3 video types deterministically (no LLM).

    Returns dict {video_type: [segments]} with the same shape as the
    LLM-based generator. The first segment of each script is marked
    is_hook=True; segments 2..N-1 are the body; the last is the outro.
    """
    ctx = _load_context(conn, series_slug, series_title)

    # Stable seed per series so re-runs are reproducible.
    base_seed = f"{series_slug}|{persona}|{seed_extra}"

    results: dict[str, list[dict]] = {}
    for vtype in VIDEO_TYPES:
        try:
            tpl = _load_template(vtype)
        except FileNotFoundError as e:
            log.warning("  %s: %s", vtype, e)
            continue

        persona_block = tpl.get("personas", {}).get(persona)
        if not persona_block:
            # Fall back to deep_mind block if the requested persona has no template
            persona_block = tpl.get("personas", {}).get("deep_mind", {})
            if not persona_block:
                log.warning("  %s: no template for persona '%s'", vtype, persona)
                continue

        rng = random.Random(f"{base_seed}|{vtype}")
        slots = _build_slots(ctx)

        # Hook
        hook_text = _fill_slots(rng.choice(persona_block.get("hooks", [""])), slots)

        # Body
        bodies = persona_block.get("bodies", {})
        theme_key = _theme_for_body(ctx["themes"], bodies)
        body_pool = list(bodies.get(theme_key) or bodies.get("default") or [])
        rng.shuffle(body_pool)
        body_count = _BODY_LEN.get(vtype, 4)
        body_lines = [_fill_slots(line, slots) for line in body_pool[:body_count]]

        # Outro
        outros = persona_block.get("outros", [])
        outro_text = _fill_slots(rng.choice(outros), slots) if outros else ""

        # Build segment list with emotions
        segments: list[dict] = [{
            "text": hook_text,
            "emotion": ctx["dominant_emotion"],
            "is_hook": True,
        }]
        body_emotion_cycle = _emotion_arc(ctx["dominant_emotion"])
        for i, line in enumerate(body_lines):
            segments.append({
                "text": line,
                "emotion": body_emotion_cycle[i % len(body_emotion_cycle)],
                "is_hook": False,
            })
        if outro_text:
            segments.append({
                "text": outro_text,
                "emotion": "hopeful" if vtype == "narration" else ctx["dominant_emotion"],
                "is_hook": False,
            })

        results[vtype] = segments
        log.info(
            "  %s: %d segments (theme=%s, hook='%s')",
            vtype, len(segments), theme_key, hook_text[:50],
        )

    return results


def _emotion_arc(dominant: str) -> list[str]:
    """A small emotion arc for body segments (build → climax → settle)."""
    arcs = {
        "dark":    ["dark", "tragic", "dark", "epic"],
        "tragic":  ["tragic", "dark", "tragic", "hopeful"],
        "epic":    ["epic", "dark", "epic", "epic"],
        "hopeful": ["hopeful", "epic", "tragic", "hopeful"],
        "shock":   ["shock", "dark", "tragic", "dark"],
    }
    return arcs.get(dominant.lower(), arcs["dark"])
