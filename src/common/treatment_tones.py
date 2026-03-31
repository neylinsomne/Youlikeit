"""
Treatment tones: how a persona APPROACHES a topic.

Same persona + same theme can produce completely different content
depending on the treatment tone:

  - critical:    challenges, questions, provocates ("Griffith was RIGHT")
  - narrative:   tells the story, immerses, lets it breathe
  - analytical:  breaks down why it works, structure, craft
  - emotional:   leans into the feeling, raw reaction, vulnerability
  - comparative: constantly cross-references, "X is like Y because Z"

Each persona has natural affinities (Deep Mind → critical/analytical,
Pop Oracle → emotional/comparative) but ALL combos are testable.

The AB testing system generates variants from the persona x tone matrix,
measures engagement, and feeds back which combos work for which themes.
"""

from __future__ import annotations
import json
import sqlite3
import logging
from pathlib import Path

log = logging.getLogger(__name__)


# ── Treatment tone definitions ──────────────────────────────────

TREATMENT_TONES = {
    "critical": {
        "label": "Critical",
        "prompt_addon": (
            "APPROACH: Be provocative. Challenge conventional readings. "
            "Take a controversial but defensible position. "
            "Make the audience disagree or passionately agree. "
            "Example: 'Griffith wasn't the villain — he was the only honest one.'"
        ),
        "voice_modifiers": {"rate_delta": "-3%", "pitch_delta": "-2Hz"},
        "color_overlay": "cold",
        "subtitle_highlight": "&H5050FF&",  # red tint — heat
        "pacing_modifier": 0.9,  # slightly faster, assertive
        "hook_types": ["hot_take", "contradiction", "unpopular_opinion"],
        "cta_style": "Agree or disagree? Comment.",
        "hashtag_prefixes": ["#hottake", "#unpopularopinion", "#controversial"],
    },
    "narrative": {
        "label": "Narrative",
        "prompt_addon": (
            "APPROACH: Immerse the viewer in the story. "
            "Make them FEEL like they're watching it for the first time. "
            "Use vivid imagery, build tension, let pauses breathe. "
            "You're a campfire storyteller, not a critic."
        ),
        "voice_modifiers": {"rate_delta": "-8%", "pitch_delta": "-5Hz"},
        "color_overlay": "warm",
        "subtitle_highlight": "&H00E8FF&",  # gold — warm
        "pacing_modifier": 1.2,  # slower, let it breathe
        "hook_types": ["scene_setting", "in_media_res", "whisper"],
        "cta_style": "Follow for more stories.",
        "hashtag_prefixes": ["#storytelling", "#storytime", "#anime"],
    },
    "analytical": {
        "label": "Analytical",
        "prompt_addon": (
            "APPROACH: Break it down. Explain the structure, the choices, "
            "the WHY behind what works. You're teaching the audience to see "
            "what they missed. Use specific examples and name techniques. "
            "Frame as 'Here's what most people don't notice about this scene.'"
        ),
        "voice_modifiers": {"rate_delta": "+0%", "pitch_delta": "+0Hz"},
        "color_overlay": "neutral",
        "subtitle_highlight": "&H00FF80&",  # green — clarity
        "pacing_modifier": 1.0,  # normal speed
        "hook_types": ["did_you_notice", "breakdown", "hidden_detail"],
        "cta_style": "What detail did I miss? Tell me.",
        "hashtag_prefixes": ["#breakdown", "#analysis", "#explained"],
    },
    "emotional": {
        "label": "Emotional",
        "prompt_addon": (
            "APPROACH: Go for the gut. This is about FEELING, not thinking. "
            "If the scene is sad, make them cry. If it's triumphant, give them chills. "
            "Short sentences. Repetition for impact. Raw honesty. "
            "Vulnerability is strength."
        ),
        "voice_modifiers": {"rate_delta": "-5%", "pitch_delta": "-3Hz"},
        "color_overlay": "desaturated",
        "subtitle_highlight": "&H8080FF&",  # salmon — emotion
        "pacing_modifier": 1.1,  # slightly slower, weight
        "hook_types": ["confession", "raw_reaction", "silence_then_punch"],
        "cta_style": "Did this hit you too?",
        "hashtag_prefixes": ["#emotional", "#feels", "#crying"],
    },
    "comparative": {
        "label": "Comparative",
        "prompt_addon": (
            "APPROACH: Everything connects. Every scene reminds you of something else. "
            "Compare across media: manga to film, anime to music, fiction to real events. "
            "The VALUE is in the unexpected connection. "
            "'This Eclipse scene? It's basically the Red Wedding meets Evangelion's Third Impact.'"
        ),
        "voice_modifiers": {"rate_delta": "+2%", "pitch_delta": "+0Hz"},
        "color_overlay": "vivid",
        "subtitle_highlight": "&H00FFFF&",  # cyan — connection
        "pacing_modifier": 0.95,  # slightly faster, energetic
        "hook_types": ["x_meets_y", "unexpected_connection", "same_energy"],
        "cta_style": "What's YOUR comparison? Drop it below.",
        "hashtag_prefixes": ["#comparison", "#versus", "#sameenergy"],
    },
}

# ── Persona x Tone affinity matrix ─────────────────────────────
# Values 0.0-1.0: how natural this combo is. Higher = more natural.
# Low affinity combos are MORE interesting to test (surprising results).

PERSONA_TONE_AFFINITY = {
    "deep_mind": {
        "critical": 0.9,      # Very natural — philosophical provocation
        "narrative": 0.6,     # Can do it but not his strength
        "analytical": 0.85,   # Strong — connects to deeper meaning
        "emotional": 0.5,     # Unnatural — interesting to test
        "comparative": 0.7,   # Good — Nietzsche meets Miyazaki
    },
    "cinephile": {
        "critical": 0.5,      # Unnatural — he appreciates, rarely attacks
        "narrative": 0.7,     # Decent — can set scenes through craft lens
        "analytical": 0.95,   # Perfect — this IS his thing
        "emotional": 0.4,     # Very unnatural — high test value
        "comparative": 0.9,   # Strong — always comparing directors
    },
    "pop_oracle": {
        "critical": 0.8,      # Hot takes are her brand
        "narrative": 0.3,     # Very unnatural — she doesn't tell stories
        "analytical": 0.3,    # Not her style at all
        "emotional": 0.85,    # Strong — raw reactions, vulnerability
        "comparative": 0.9,   # Perfect — fiction meets real life
    },
}


# ── Theme categories for cross-analysis ─────────────────────────

THEME_CATEGORIES = {
    "betrayal":     {"emotions": ["dark", "tragic"], "weight": 1.0},
    "sacrifice":    {"emotions": ["tragic", "epic"], "weight": 1.0},
    "power":        {"emotions": ["dark", "epic"], "weight": 0.9},
    "love":         {"emotions": ["hopeful", "tragic"], "weight": 0.8},
    "revenge":      {"emotions": ["dark", "epic"], "weight": 0.9},
    "redemption":   {"emotions": ["hopeful", "epic"], "weight": 0.8},
    "identity":     {"emotions": ["dark", "hopeful"], "weight": 0.7},
    "corruption":   {"emotions": ["dark"], "weight": 0.9},
    "friendship":   {"emotions": ["hopeful", "tragic"], "weight": 0.7},
    "madness":      {"emotions": ["dark", "shock"], "weight": 0.8},
    "war":          {"emotions": ["epic", "tragic"], "weight": 0.9},
    "coming_of_age": {"emotions": ["hopeful"], "weight": 0.6},
    "existential":  {"emotions": ["dark", "tragic"], "weight": 0.8},
    "ambition":     {"emotions": ["epic", "dark"], "weight": 0.9},
}


# ── DB schema for crossover analytics ──────────────────────────

CROSSOVER_SCHEMA = """
CREATE TABLE IF NOT EXISTS content_variants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    short_id INTEGER REFERENCES shorts(id),
    persona TEXT NOT NULL,
    tone TEXT NOT NULL,
    theme_category TEXT,
    emotion TEXT,
    hook_type TEXT,
    color_grade TEXT,
    voice_params TEXT,           -- JSON
    subtitle_style TEXT,         -- JSON
    pacing_modifier REAL,
    prompt_addon TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS crossover_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    variant_id INTEGER REFERENCES content_variants(id),
    short_id INTEGER REFERENCES shorts(id),
    platform TEXT DEFAULT 'youtube',    -- youtube, tiktok
    views INTEGER DEFAULT 0,
    likes INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    shares INTEGER DEFAULT 0,
    watch_time_avg_s REAL,
    retention_at_3s REAL,               -- % still watching at 3s
    retention_at_15s REAL,              -- % still watching at 15s
    retention_at_30s REAL,              -- % still watching at 30s
    engagement_rate REAL,               -- (likes+comments+shares)/views
    ctr REAL,                           -- click-through rate from impressions
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_cv_persona_tone ON content_variants(persona, tone);
CREATE INDEX IF NOT EXISTS idx_cv_theme ON content_variants(theme_category);
CREATE INDEX IF NOT EXISTS idx_cm_variant ON crossover_metrics(variant_id);
"""


def init_crossover_db(conn: sqlite3.Connection):
    """Create crossover analytics tables."""
    conn.executescript(CROSSOVER_SCHEMA)
    conn.commit()


# ── Test matrix generator ──────────────────────────────────────

def generate_test_matrix(
    conn: sqlite3.Connection,
    theme: str,
    series_title: str = "",
    personas: list[str] | None = None,
    tones: list[str] | None = None,
    max_tests: int = 6,
) -> list[dict]:
    """
    Generate A/B test combinations for a theme.

    Strategy: prioritize LOW affinity combos (surprising results)
    mixed with HIGH affinity combos (reliable baseline).

    Returns list of test configs ready for ab_testing.create_ab_test().
    """
    from common.ab_testing import TESTABLE_VARIABLES

    personas = personas or list(PERSONA_TONE_AFFINITY.keys())
    tones = tones or list(TREATMENT_TONES.keys())

    # Build all combos with their affinity scores
    combos = []
    for persona in personas:
        affinities = PERSONA_TONE_AFFINITY.get(persona, {})
        for tone in tones:
            affinity = affinities.get(tone, 0.5)
            combos.append({
                "persona": persona,
                "tone": tone,
                "affinity": affinity,
                "surprise_value": 1.0 - affinity,  # Low affinity = high surprise
            })

    # Sort: alternate between high-surprise and high-affinity
    combos.sort(key=lambda c: c["surprise_value"], reverse=True)
    high_surprise = combos[:len(combos) // 2]
    high_affinity = combos[len(combos) // 2:]
    high_affinity.sort(key=lambda c: c["affinity"], reverse=True)

    # Pair them: each test = one high-affinity (baseline) vs one high-surprise (experiment)
    tests = []
    for i in range(min(max_tests, len(high_surprise), len(high_affinity))):
        baseline = high_affinity[i]
        experiment = high_surprise[i]

        tone_a = TREATMENT_TONES[baseline["tone"]]
        tone_b = TREATMENT_TONES[experiment["tone"]]

        test = {
            "name": f"{theme}: {baseline['persona']}/{baseline['tone']} vs {experiment['persona']}/{experiment['tone']}",
            "hypothesis": (
                f"Testing if {experiment['persona']} with {experiment['tone']} tone "
                f"(affinity={experiment['affinity']:.1f}, surprise={experiment['surprise_value']:.1f}) "
                f"outperforms {baseline['persona']} with {baseline['tone']} tone "
                f"(affinity={baseline['affinity']:.1f}) for theme '{theme}'"
            ),
            "variable": "persona",
            "variant_a": {
                "persona": baseline["persona"],
                "tone": baseline["tone"],
                "affinity": baseline["affinity"],
                "prompt_addon": tone_a["prompt_addon"],
                "color_overlay": tone_a["color_overlay"],
                "voice_modifiers": tone_a["voice_modifiers"],
                "hook_type": tone_a["hook_types"][0],
                "hashtags": tone_a["hashtag_prefixes"],
                "theme": theme,
                "series": series_title,
            },
            "variant_b": {
                "persona": experiment["persona"],
                "tone": experiment["tone"],
                "affinity": experiment["affinity"],
                "prompt_addon": tone_b["prompt_addon"],
                "color_overlay": tone_b["color_overlay"],
                "voice_modifiers": tone_b["voice_modifiers"],
                "hook_type": tone_b["hook_types"][0],
                "hashtags": tone_b["hashtag_prefixes"],
                "theme": theme,
                "series": series_title,
            },
        }
        tests.append(test)

    log.info(f"Generated {len(tests)} test combos for theme '{theme}'")
    return tests


def register_variant(
    conn: sqlite3.Connection,
    short_id: int,
    persona: str,
    tone: str,
    theme_category: str = "",
    emotion: str = "",
    hook_type: str = "",
) -> int:
    """Register a content variant for crossover tracking."""
    init_crossover_db(conn)

    tone_config = TREATMENT_TONES.get(tone, {})

    cur = conn.execute("""
        INSERT INTO content_variants
        (short_id, persona, tone, theme_category, emotion, hook_type,
         color_grade, voice_params, pacing_modifier, prompt_addon)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        short_id, persona, tone, theme_category, emotion, hook_type,
        tone_config.get("color_overlay", ""),
        json.dumps(tone_config.get("voice_modifiers", {})),
        tone_config.get("pacing_modifier", 1.0),
        tone_config.get("prompt_addon", ""),
    ))
    conn.commit()
    return cur.lastrowid


def get_crossover_report(conn: sqlite3.Connection) -> dict:
    """
    Big data crossover: theme x tone x persona → average metrics.
    This is the core insight engine.
    """
    init_crossover_db(conn)

    report = {
        "by_persona_tone": [],
        "by_theme_tone": [],
        "by_persona_theme": [],
        "top_combos": [],
        "worst_combos": [],
        "surprise_winners": [],
    }

    # Persona x Tone (which voice + approach combo works best?)
    rows = conn.execute("""
        SELECT cv.persona, cv.tone,
               COUNT(*) as n,
               AVG(cm.engagement_rate) as avg_engagement,
               AVG(cm.retention_at_15s) as avg_retention_15s,
               AVG(cm.views) as avg_views,
               AVG(cm.watch_time_avg_s) as avg_watch_time
        FROM content_variants cv
        JOIN crossover_metrics cm ON cm.variant_id = cv.id
        GROUP BY cv.persona, cv.tone
        HAVING n >= 2
        ORDER BY avg_engagement DESC
    """).fetchall()
    report["by_persona_tone"] = [dict(r) for r in rows]

    # Theme x Tone (which themes respond to which treatment?)
    rows = conn.execute("""
        SELECT cv.theme_category, cv.tone,
               COUNT(*) as n,
               AVG(cm.engagement_rate) as avg_engagement,
               AVG(cm.retention_at_15s) as avg_retention_15s,
               AVG(cm.views) as avg_views
        FROM content_variants cv
        JOIN crossover_metrics cm ON cm.variant_id = cv.id
        WHERE cv.theme_category != ''
        GROUP BY cv.theme_category, cv.tone
        HAVING n >= 2
        ORDER BY avg_engagement DESC
    """).fetchall()
    report["by_theme_tone"] = [dict(r) for r in rows]

    # Persona x Theme (which persona owns which themes?)
    rows = conn.execute("""
        SELECT cv.persona, cv.theme_category,
               COUNT(*) as n,
               AVG(cm.engagement_rate) as avg_engagement,
               AVG(cm.retention_at_15s) as avg_retention_15s
        FROM content_variants cv
        JOIN crossover_metrics cm ON cm.variant_id = cv.id
        WHERE cv.theme_category != ''
        GROUP BY cv.persona, cv.theme_category
        HAVING n >= 2
        ORDER BY avg_engagement DESC
    """).fetchall()
    report["by_persona_theme"] = [dict(r) for r in rows]

    # Top 10 overall combos
    rows = conn.execute("""
        SELECT cv.persona, cv.tone, cv.theme_category, cv.emotion,
               cm.engagement_rate, cm.retention_at_15s, cm.views,
               cm.watch_time_avg_s
        FROM content_variants cv
        JOIN crossover_metrics cm ON cm.variant_id = cv.id
        ORDER BY cm.engagement_rate DESC
        LIMIT 10
    """).fetchall()
    report["top_combos"] = [dict(r) for r in rows]

    # Surprise winners: low affinity combos that outperformed
    for row in report["by_persona_tone"]:
        persona = row.get("persona", "")
        tone = row.get("tone", "")
        affinity = PERSONA_TONE_AFFINITY.get(persona, {}).get(tone, 0.5)
        if affinity < 0.5 and row.get("avg_engagement", 0) > 0:
            row["affinity"] = affinity
            row["surprise_factor"] = (1 - affinity) * row["avg_engagement"]
            report["surprise_winners"].append(row)

    report["surprise_winners"].sort(key=lambda x: x.get("surprise_factor", 0), reverse=True)

    return report


def recommend_next_content(
    conn: sqlite3.Connection,
    available_themes: list[str],
    n: int = 3,
) -> list[dict]:
    """
    Based on crossover data, recommend the best persona x tone x theme
    combos to produce next. Balances exploitation (what works) with
    exploration (undertested combos).

    Returns top N recommendations.
    """
    init_crossover_db(conn)

    recommendations = []

    for theme in available_themes:
        # Check what we've already tested for this theme
        tested = conn.execute("""
            SELECT cv.persona, cv.tone, COUNT(*) as n,
                   AVG(cm.engagement_rate) as avg_eng
            FROM content_variants cv
            LEFT JOIN crossover_metrics cm ON cm.variant_id = cv.id
            WHERE cv.theme_category = ?
            GROUP BY cv.persona, cv.tone
        """, (theme,)).fetchall()

        tested_combos = {(r["persona"], r["tone"]): dict(r) for r in tested}

        for persona, affinities in PERSONA_TONE_AFFINITY.items():
            for tone, affinity in affinities.items():
                key = (persona, tone)
                if key in tested_combos:
                    data = tested_combos[key]
                    # Exploitation score: engagement * sample confidence
                    sample_confidence = min(1.0, data["n"] / 5)
                    exploit = (data.get("avg_eng") or 0) * sample_confidence
                    # Exploration: less tested = more valuable
                    explore = max(0, 1.0 - sample_confidence) * 0.5
                else:
                    # Never tested — high exploration value
                    exploit = 0
                    explore = 0.8

                # Surprise bonus: low affinity combos get extra explore weight
                surprise_bonus = (1 - affinity) * 0.3

                score = exploit + explore + surprise_bonus

                recommendations.append({
                    "theme": theme,
                    "persona": persona,
                    "tone": tone,
                    "affinity": affinity,
                    "exploit_score": round(exploit, 3),
                    "explore_score": round(explore + surprise_bonus, 3),
                    "total_score": round(score, 3),
                    "times_tested": tested_combos.get(key, {}).get("n", 0),
                    "avg_engagement": tested_combos.get(key, {}).get("avg_eng"),
                    "reason": (
                        "untested_combo" if key not in tested_combos
                        else "high_performer" if exploit > 0.5
                        else "needs_more_data" if tested_combos[key]["n"] < 3
                        else "surprise_candidate" if affinity < 0.5
                        else "exploitation"
                    ),
                })

    recommendations.sort(key=lambda r: r["total_score"], reverse=True)
    return recommendations[:n]
