"""
Script Generator: auto-generate narration scripts for any series using LLM.

Uses:
- series_themes (from thematic_classifier) — series overall tone + themes
- scene_moments (DB) — specific iconic episodes with quotes
- personas.py — persona prompts for voice style
- cross_ref pool — known antiheroes to reference

For each video type (narration/personality/test), produces a list of segments:
  [{text, emotion, themes}]

These are ready for the existing test_content_cycle_v2 pipeline.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3

import requests

log = logging.getLogger(__name__)


# ── Video type specifications ───────────────────────────────────

VIDEO_TYPES = {
    "narration": {
        "label": "Narration (safe storytelling)",
        "instruction": (
            "Tell the story of a pivotal moment. Make the viewer FEEL the weight of "
            "what happened. Use vivid imagery, build tension, let pauses breathe. "
            "5-6 short segments, 30-50 seconds total."
        ),
        "tone_desc": "immersive storyteller, calm but gripping",
        "cta_style": "Follow for more stories.",
        "hook_rule": (
            "Segment 1 must be 4-7 words ending in an ellipsis (…). Set the scene "
            "with tension. Avoid full sentences. Example: 'It was the night that "
            "changed everything…'"
        ),
        "hook_cps": 2.0,  # cuts per second during the hook
    },
    "personality": {
        "label": "Personality (hot take)",
        "instruction": (
            "Take a provocative, contrarian position on the series. Challenge the "
            "common reading. Compare the main antagonist/antihero to 2-3 FICTIONAL "
            "characters from cinema/anime (Walter White, Light Yagami, Michael "
            "Corleone, etc.). End with a question that invites debate. "
            "5-6 short segments, 30-50 seconds total."
        ),
        "tone_desc": "philosophical provocateur, challenging, uses rhetorical questions",
        "cta_style": "Agree or disagree? Comment.",
        "hook_rule": (
            "Segment 1 must be a contrarian declaration ending in a period — max 8 "
            "words, no question marks, no ellipses. Pure assertion. "
            "Example: 'Griffith was right. And you know it.'"
        ),
        "hook_cps": 3.5,
    },
    "test": {
        "label": "Test (emotional gut-punch)",
        "instruction": (
            "Go straight for the emotional core. Pick ONE devastating moment and "
            "dwell on it. Short sentences. Repetition for impact. Raw honesty. "
            "Vulnerability. 5-6 short segments, 25-40 seconds total."
        ),
        "tone_desc": "raw, emotional, vulnerable",
        "cta_style": "Did this hit you too?",
        "hook_rule": (
            "Segment 1 must reference a count or a feeling — slow, vulnerable, "
            "max 9 words. Example: 'I have watched this scene a hundred times.' "
            "or 'There is a moment I cannot forget.'"
        ),
        "hook_cps": 1.0,
    },
}


# ── Hook keyword detection ──────────────────────────────────────
# Used to suggest which word in the first segment should be visually
# emphasized (size 1.4x, accent color) by the subtitle renderer.

HOOK_ACCENT_KEYWORDS = {
    "narration": ["night", "everything", "changed", "moment", "world", "axis", "consequences"],
    "personality": ["right", "wrong", "underrated", "overrated", "stop", "everyone", "no one"],
    "test": ["hundred", "thousand", "every", "single", "broke", "cannot", "never"],
}


def _build_context(
    conn: sqlite3.Connection,
    series_slug: str,
    series_title: str,
) -> dict:
    """Build all the context the LLM needs to write scripts."""
    ctx = {"series_title": series_title, "series_slug": series_slug}

    # Series themes
    row = conn.execute(
        "SELECT * FROM series_themes WHERE series_slug = ?", (series_slug,),
    ).fetchone()
    if row:
        d = dict(row)
        try:
            d["primary_themes"] = json.loads(d.get("primary_themes") or "[]")
            d["secondary_themes"] = json.loads(d.get("secondary_themes") or "[]")
            d["tonal_profile"] = json.loads(d.get("tonal_profile") or "{}")
        except Exception:
            pass
        ctx["themes"] = d.get("primary_themes", [])
        ctx["archetype"] = d.get("archetype_primary", "")
        ctx["archetype_antagonist"] = d.get("archetype_antagonist", "")
        ctx["dominant_emotion"] = d.get("dominant_emotion", "dark")

    # Iconic moments
    moments_rows = conn.execute(
        """SELECT season_number, episode_number, episode_name, moment_description,
                  themes, emotion, quote, iconic_score
           FROM scene_moments WHERE series_slug = ?
           ORDER BY iconic_score DESC LIMIT 8""",
        (series_slug,),
    ).fetchall()
    ctx["moments"] = []
    for m in moments_rows:
        d = dict(m)
        try:
            d["themes"] = json.loads(d.get("themes") or "[]")
        except Exception:
            d["themes"] = []
        ctx["moments"].append(d)

    return ctx


# ── LLM prompt construction ─────────────────────────────────────

def _build_prompt(
    series_title: str,
    video_type: str,
    persona: str,
    context: dict,
) -> str:
    """Build the full LLM prompt for a video type."""
    spec = VIDEO_TYPES[video_type]

    themes = ", ".join(context.get("themes", [])) or "general drama"
    archetype = context.get("archetype") or "protagonist"

    moments_lines = []
    for m in context.get("moments", [])[:5]:
        quote_part = f' (quote: "{m["quote"]}")' if m.get("quote") else ""
        moments_lines.append(
            f"- Ep{m.get('episode_number', '?')}: {m.get('moment_description', '')[:150]}{quote_part}"
        )
    moments_text = "\n".join(moments_lines) if moments_lines else "(no iconic moments catalogued)"

    persona_prompts = {
        "deep_mind": (
            "You are Deep Mind — a philosophical narrator. Analytical, contemplative, "
            "never references real historical figures (only fictional characters). "
            "Uses pauses for impact."
        ),
        "pop_oracle": (
            "You are Pop Oracle — witty, conversational, cultural-ref heavy. "
            "Connects fiction to current pop culture trends."
        ),
        "latam": (
            "Eres Voz Latina — hablas en español. Apasionado, conectas ficción con "
            "realidad cultural latinoamericana."
        ),
    }
    persona_desc = persona_prompts.get(persona, persona_prompts["deep_mind"])

    lang = "Spanish" if persona == "latam" else "English"

    hook_rule = spec.get("hook_rule", "")

    return f"""{persona_desc}

Generate a YouTube Short script ({lang}) for the series "{series_title}".

Video type: {spec['label']}
Approach: {spec['instruction']}
Tone: {spec['tone_desc']}

SERIES DATA:
- Main themes: {themes}
- Protagonist archetype: {archetype}
- Dominant emotion: {context.get('dominant_emotion', 'dark')}

ICONIC MOMENTS (pick 1-2 to anchor your script):
{moments_text}

HOOK RULE (segment 1 — first 3 seconds, the most important segment):
{hook_rule}
The first segment is the retention hook. It must work as a standalone sentence
that makes a viewer NOT swipe away. Mark it with `"is_hook": true` in the JSON.

CONSTRAINTS:
- 5-6 segments of 1 short sentence each (5-12 words)
- Each segment ends with natural pause (period, ellipsis)
- No references to real historical people (Napoleon, Caesar, etc.)
- If comparing, ONLY compare to fictional characters from cinema/anime
- Emotion must be ONE OF: dark | tragic | epic | hopeful | shock
- Include characters/series names directly when relevant (they'll become cross-ref images)

Return JSON array (no markdown):
[
  {{"text": "first segment (HOOK)", "emotion": "dark", "is_hook": true}},
  {{"text": "second segment", "emotion": "tragic"}},
  ...
]"""


def _call_gemini(prompt: str, temperature: float = 0.7) -> str:
    """Call Gemini Flash."""
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")

    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}",
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": 1500},
        },
        timeout=30,
    )
    resp.raise_for_status()
    candidates = resp.json().get("candidates", [])
    if not candidates:
        return ""
    return candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")


def _extract_json_array(text: str) -> list:
    """Extract JSON array from LLM response (robust to preamble/fences)."""
    m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, flags=re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass

    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            pass
    return []


# ── Main API ────────────────────────────────────────────────────

def generate_scripts_for_series(
    conn: sqlite3.Connection,
    series_slug: str,
    series_title: str,
    persona: str = "deep_mind",
    use_llm: bool = False,
    seed_extra: str = "",
) -> dict:
    """
    Generate the 3 video scripts (narration, personality, test) for a series.

    By default uses the deterministic, JSON-template-based algorithmic
    generator (no LLM). Pass `use_llm=True` to fall back to the legacy
    Gemini-driven path (kept for experimentation).

    Returns dict {video_type: [segments]} ready for the rendering pipeline.
    """
    if not use_llm:
        from common.algorithmic_script_generator import generate_scripts_algorithmic
        log.info("Using algorithmic script generator (no LLM)")
        return generate_scripts_algorithmic(
            conn=conn,
            series_slug=series_slug,
            series_title=series_title,
            persona=persona,
            seed_extra=seed_extra,
        )

    # ── Legacy LLM path (opt-in) ────────────────────────────────
    context = _build_context(conn, series_slug, series_title)

    if not context.get("themes"):
        log.warning(
            f"Series '{series_slug}' has no classification. "
            f"Run: from common.thematic_stills import ensure_series_classified; "
            f"ensure_series_classified(conn, '{series_title}', tmdb_id=?, slug='{series_slug}')"
        )

    results = {}
    for vtype in ("narration", "personality", "test"):
        log.info(f"  Generating {vtype} script for {series_title}...")
        prompt = _build_prompt(series_title, vtype, persona, context)
        try:
            text = _call_gemini(prompt, temperature=0.7)
            segments = _extract_json_array(text)
            if not segments:
                log.warning(f"  {vtype}: LLM returned no segments, raw: {text[:200]}")
                continue
            # Validate schema and force is_hook=True on first segment if not set
            clean = []
            for i, s in enumerate(segments):
                if "text" not in s:
                    continue
                clean.append({
                    "text": s["text"],
                    "emotion": s.get("emotion", "dark"),
                    "is_hook": bool(s.get("is_hook", i == 0)),
                })
            # Defensive: only the first segment can be the hook
            for j, c in enumerate(clean):
                c["is_hook"] = (j == 0)
            results[vtype] = clean
            log.info(f"  {vtype}: {len(clean)} segments (hook='{clean[0]['text'][:40]}…')")
        except Exception as e:
            log.error(f"  {vtype} failed: {e}")

    return results


def voice_params_for_video_type(vtype: str) -> dict:
    """edge-tts rate/pitch per video type (matches test_content_cycle_v2)."""
    return {
        "narration": {"rate": "-5%", "pitch": "-8Hz"},
        "personality": {"rate": "-3%", "pitch": "-5Hz"},
        "test": {"rate": "-8%", "pitch": "-10Hz"},
    }.get(vtype, {"rate": "-5%", "pitch": "-8Hz"})


def hook_cps_for_video_type(vtype: str) -> float:
    """Cuts-per-second target for the hook (first segment) of each video type."""
    spec = VIDEO_TYPES.get(vtype, {})
    return spec.get("hook_cps", 1.0)


def detect_hook_accent_word(text: str, vtype: str) -> str | None:
    """
    Pick the keyword to visually emphasize in the hook subtitle.
    Returns the word found, or None if no candidate matches.
    """
    candidates = HOOK_ACCENT_KEYWORDS.get(vtype, [])
    lower = text.lower()
    for kw in candidates:
        # Word boundary, case-insensitive
        if re.search(r"\b" + re.escape(kw) + r"\b", lower):
            return kw
    # Fallback: longest noun-ish word > 5 chars
    words = [w.strip(".,!?…\"'") for w in text.split()]
    long_words = sorted(
        [w for w in words if len(w) > 5 and w[0].isalpha()],
        key=len, reverse=True,
    )
    return long_words[0] if long_words else None
