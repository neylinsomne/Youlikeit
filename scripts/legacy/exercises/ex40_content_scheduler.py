"""
ex40 - Content Scheduler: 3 videos x 3 canales cada 3 dias.

Cada canal (persona) produce 3 tipos de video:

  1. NARRATION  — Lo seguro. RAG + voz + manga/pelicula. Cuenta la historia.
                   Usa el pipeline probado (ex04→ex11→ex18).
                   Tono: "narrative". Sin riesgos.

  2. PERSONALITY — La identidad del canal. El tono natural de la persona.
                   Deep Mind critica, Cinephile analiza, Pop Oracle compara.
                   Usa el tone de mayor afinidad de la persona.

  3. TEST       — El experimento. Combo de baja afinidad o variable nueva.
                   Alimenta el A/B testing. Puede ser un hit o un fracaso.
                   Los datos alimentan el crossover analytics.

Cadencia: cada 3 dias se genera un batch de 9 videos (3x3).
El scheduler decide QUE tema, QUE tono, y QUE persona para cada slot.

Uso:
  python src/main.py ex40                          # genera el proximo batch
  python src/main.py ex40 --series "Berserk"       # forzar serie
  python src/main.py ex40 --dry-run                # solo muestra el plan
  python src/main.py ex40 --persona deep_mind      # solo un canal
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from core.config import Settings
from core.db import get_db
from utils.logger import build_logger


# ── Video types ─────────────────────────────────────────────────

VIDEO_TYPES = {
    "narration": {
        "label": "Narration (safe)",
        "tone": "narrative",
        "description": "RAG + voice + manga. Tell the story. No risks.",
        "pipeline_steps": [
            # Content discovery + matching
            ("ex04", ["--query", "{query}", "--max-movies", "12", "--mode", "trending"]),
            ("ex05", ["--max-downloads", "12"]),
            ("ex06", ["--threshold", "72", "--with-chroma"]),
            ("ex10", ["--provider", "auto", "--batch-size", "50"]),
            # Build + cut
            ("ex07", ["--query", "{query}", "--max-results", "5"]),
            ("ex09", ["--query", "{query}", "--max-results", "5", "--group-size", "3"]),
            ("ex11", ["--query", "{query}", "--burn-subs"]),
            # Narrate
            ("ex18", ["--query", "{query}", "--lang", "en", "--narration-style", "reflective", "--persona", "{persona}"]),
            # Strategy
            ("ex08", ["--query", "{query}", "--country-code", "US", "--period-days", "7"]),
            ("ex17", ["--query", "{query}", "--platform", "both", "--country-code", "US"]),
        ],
        "upload_privacy": "unlisted",  # safe to publish quickly
    },
    "personality": {
        "label": "Personality (identity)",
        "tone": "auto",  # uses persona's highest affinity tone
        "description": "The channel's signature style. What makes THIS persona unique.",
        "pipeline_steps": [
            ("ex04", ["--query", "{query}", "--max-movies", "12", "--mode", "trending"]),
            ("ex05", ["--max-downloads", "12"]),
            ("ex06", ["--threshold", "72", "--with-chroma"]),
            ("ex10", ["--provider", "auto", "--batch-size", "50"]),
            ("ex07", ["--query", "{query}", "--max-results", "5"]),
            ("ex09", ["--query", "{query}", "--max-results", "5", "--group-size", "3"]),
            ("ex11", ["--query", "{query}", "--burn-subs"]),
            ("ex18", ["--query", "{query}", "--lang", "en", "--narration-style", "{style}", "--persona", "{persona}"]),
            ("ex08", ["--query", "{query}", "--country-code", "US", "--period-days", "7"]),
            ("ex17", ["--query", "{query}", "--platform", "both", "--country-code", "US"]),
        ],
        "upload_privacy": "unlisted",
    },
    "test": {
        "label": "Test (experiment)",
        "tone": "auto",  # picked by recommend_next_content()
        "description": "A/B test variant. Low affinity combo. Data collection.",
        "pipeline_steps": [
            ("ex04", ["--query", "{query}", "--max-movies", "12", "--mode", "trending"]),
            ("ex05", ["--max-downloads", "12"]),
            ("ex06", ["--threshold", "72", "--with-chroma"]),
            ("ex10", ["--provider", "auto", "--batch-size", "50"]),
            ("ex07", ["--query", "{query}", "--max-results", "5"]),
            ("ex09", ["--query", "{query}", "--max-results", "5", "--group-size", "3"]),
            ("ex11", ["--query", "{query}", "--burn-subs"]),
            ("ex18", ["--query", "{query}", "--lang", "en", "--narration-style", "{style}", "--persona", "{persona}"]),
            ("ex08", ["--query", "{query}", "--country-code", "US", "--period-days", "7"]),
            ("ex17", ["--query", "{query}", "--platform", "both", "--country-code", "US"]),
        ],
        "upload_privacy": "unlisted",
    },
}

# Narration style mapping from tone
TONE_TO_STYLE = {
    "critical": "dramatic",
    "narrative": "reflective",
    "analytical": "reflective",
    "emotional": "poetic",
    "comparative": "casual",
}

# ── Persona best tones (for "personality" video type) ───────────

PERSONA_SIGNATURE_TONES = {
    "deep_mind": "critical",      # His brand: philosophical provocation
    "cinephile": "analytical",    # His brand: craft breakdown
    "pop_oracle": "comparative",  # Her brand: fiction meets reality
    "latam": "comparative",       # His brand: cross-country novela comparison
}

# Language per persona
PERSONA_LANG = {
    "deep_mind": "en",
    "cinephile": "en",
    "pop_oracle": "en",
    "latam": "es",
}


# ── Theme pool ──────────────────────────────────────────────────

def _get_available_themes(conn: sqlite3.Connection, include_culture: bool = True, persona: str = "") -> list[str]:
    """Get themes from DB (quotes) + live culture feed. LatAm persona gets Spanish sources."""
    themes = []

    # LatAm persona uses completely different sources
    if persona == "latam":
        try:
            from apps.signals.latam_discovery import generate_latam_themes
            latam_themes = generate_latam_themes(max_themes=10)
            themes.extend([t["query"] for t in latam_themes])
        except Exception:
            pass

        if len(themes) < 3:
            themes.extend([
                "Betty la Fea", "Al Fondo Hay Sitio", "Rebelde",
                "El Secreto de sus Ojos", "La Casa de las Flores",
                "Pasión de Gavilanes",
            ])
        return themes

    # English personas: quotes DB + US culture feed
    rows = conn.execute("""
        SELECT DISTINCT q.category as theme, COUNT(*) as n
        FROM quotes q
        WHERE q.start_ms IS NOT NULL AND q.confidence > 70
        GROUP BY q.category
        HAVING n >= 3
        ORDER BY n DESC
    """).fetchall()
    themes.extend([r["theme"] for r in rows if r["theme"]])

    if include_culture:
        try:
            from apps.signals.culture_feed import (
                fetch_rss_headlines,
                extract_themes_from_culture,
            )
            headlines = fetch_rss_headlines(max_per_feed=3)
            culture_themes = extract_themes_from_culture(headlines, max_themes=8)
            for ct in culture_themes:
                themes.append(ct["query"])
        except Exception:
            pass

    if len(themes) < 3:
        themes.extend([
            "villain monologue", "epic fight scene", "emotional farewell",
            "plot twist", "character transformation", "sacrifice moment",
        ])

    return themes


def _get_recently_used_themes(conn: sqlite3.Connection, days: int = 9) -> set[str]:
    """Themes used in the last N days (avoid repeats)."""
    rows = conn.execute("""
        SELECT DISTINCT theme_query FROM shorts
        WHERE created_at > datetime('now', ?)
    """, (f"-{days} days",)).fetchall()
    return {r["theme_query"] for r in rows if r["theme_query"]}


def _pick_theme(conn: sqlite3.Connection, persona: str) -> str:
    """Pick a theme that hasn't been used recently."""
    available = _get_available_themes(conn, persona=persona)
    recent = _get_recently_used_themes(conn)
    fresh = [t for t in available if t not in recent]
    if fresh:
        return fresh[0]
    if available:
        return available[0]
    return "novela latinoamericana" if persona == "latam" else "epic movie moment"


# ── Batch planner ───────────────────────────────────────────────

def plan_batch(
    conn: sqlite3.Connection,
    personas: list[str] | None = None,
    series: str = "",
    force_theme: str = "",
) -> list[dict]:
    """
    Plan the next batch: 3 videos per persona.

    Returns a list of 9 video plans (3 personas x 3 types).
    """
    from apps.production.treatment_tones import (
        PERSONA_TONE_AFFINITY,
        recommend_next_content,
    )

    personas = personas or ["deep_mind", "pop_oracle", "latam"]
    batch = []

    for persona in personas:
        theme = force_theme or _pick_theme(conn, persona)
        query = f"{theme} {series}".strip() if series else theme
        affinities = PERSONA_TONE_AFFINITY.get(persona, {})
        lang = PERSONA_LANG.get(persona, "en")

        # ── Video 1: NARRATION (safe) ──
        batch.append({
            "persona": persona,
            "video_type": "narration",
            "theme": theme,
            "query": query,
            "tone": "narrative",
            "style": "reflective",
            "lang": lang,
            "reason": "safe_baseline",
            "affinity": affinities.get("narrative", 0.5),
        })

        # ── Video 2: PERSONALITY (signature tone) ──
        sig_tone = PERSONA_SIGNATURE_TONES.get(persona, "analytical")
        batch.append({
            "persona": persona,
            "video_type": "personality",
            "theme": theme,
            "query": query,
            "tone": sig_tone,
            "style": TONE_TO_STYLE.get(sig_tone, "reflective"),
            "lang": lang,
            "reason": "signature_identity",
            "affinity": affinities.get(sig_tone, 0.5),
        })

        # ── Video 3: TEST (experiment from recommender) ──
        recs = recommend_next_content(conn, [theme], n=5)
        # Find a rec for THIS persona, or any low-affinity combo
        test_rec = None
        for r in recs:
            if r["persona"] == persona:
                test_rec = r
                break
        if not test_rec:
            # Find lowest affinity combo for this persona
            lowest = min(affinities.items(), key=lambda x: x[1])
            test_rec = {"tone": lowest[0], "reason": "lowest_affinity"}

        test_tone = test_rec.get("tone", "emotional")
        batch.append({
            "persona": persona,
            "video_type": "test",
            "theme": theme,
            "query": query,
            "tone": test_tone,
            "style": TONE_TO_STYLE.get(test_tone, "reflective"),
            "lang": lang,
            "reason": test_rec.get("reason", "experiment"),
            "affinity": affinities.get(test_tone, 0.5),
        })

    return batch


def format_batch_plan(batch: list[dict]) -> str:
    """Human-readable batch plan."""
    lines = [
        "=" * 60,
        "CONTENT BATCH PLAN",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"Videos: {len(batch)} ({len(batch)//3} personas x 3 types)",
        "=" * 60,
        "",
    ]

    current_persona = ""
    for v in batch:
        if v["persona"] != current_persona:
            current_persona = v["persona"]
            lines.append(f"── {current_persona.upper().replace('_', ' ')} ──")
            lines.append("")

        type_icon = {"narration": "📖", "personality": "🎭", "test": "🧪"}
        icon = type_icon.get(v["video_type"], "?")

        lang_flag = "🇪🇸" if v.get('lang') == 'es' else "🇺🇸"
        lines.append(f"  {icon} {v['video_type'].upper():12s} | {lang_flag} {v.get('lang','en'):2s} | tone: {v['tone']:12s} | aff: {v['affinity']:.1f} | {v['reason']}")
        lines.append(f"     theme: {v['theme']}")
        lines.append(f"     style: {v['style']}")
        lines.append("")

    return "\n".join(lines)


# ── Schema ──────────────────────────────────────────────────────

SCHEDULE_SCHEMA = """
CREATE TABLE IF NOT EXISTS content_schedule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT NOT NULL,
    persona TEXT NOT NULL,
    video_type TEXT NOT NULL,
    theme TEXT NOT NULL,
    query TEXT NOT NULL,
    tone TEXT NOT NULL,
    style TEXT NOT NULL,
    affinity REAL,
    reason TEXT,
    status TEXT DEFAULT 'planned',
    short_id INTEGER,
    variant_id INTEGER,
    ab_test_id INTEGER,
    planned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    uploaded_youtube INTEGER DEFAULT 0,
    uploaded_tiktok INTEGER DEFAULT 0,
    error TEXT
);
"""


def _init_schedule_db(conn: sqlite3.Connection):
    conn.executescript(SCHEDULE_SCHEMA)
    conn.commit()


def save_batch(conn: sqlite3.Connection, batch: list[dict]) -> str:
    """Save a batch plan to the DB. Returns batch_id."""
    _init_schedule_db(conn)

    batch_id = datetime.now(timezone.utc).strftime("batch_%Y%m%d_%H%M%S")

    for v in batch:
        conn.execute("""
            INSERT INTO content_schedule
            (batch_id, persona, video_type, theme, query, tone, style, affinity, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            batch_id, v["persona"], v["video_type"], v["theme"],
            v["query"], v["tone"], v["style"], v.get("affinity", 0),
            v.get("reason", ""),
        ))

    conn.commit()
    return batch_id


def get_next_pending(conn: sqlite3.Connection) -> dict | None:
    """Get the next planned video to produce."""
    _init_schedule_db(conn)
    row = conn.execute("""
        SELECT * FROM content_schedule
        WHERE status = 'planned'
        ORDER BY id ASC
        LIMIT 1
    """).fetchone()
    return dict(row) if row else None


def mark_started(conn: sqlite3.Connection, schedule_id: int):
    conn.execute("""
        UPDATE content_schedule SET status='producing', started_at=datetime('now')
        WHERE id=?
    """, (schedule_id,))
    conn.commit()


def mark_completed(conn: sqlite3.Connection, schedule_id: int, short_id: int = 0, variant_id: int = 0):
    conn.execute("""
        UPDATE content_schedule SET status='completed', completed_at=datetime('now'),
        short_id=?, variant_id=?
        WHERE id=?
    """, (short_id, variant_id, schedule_id))
    conn.commit()


def mark_failed(conn: sqlite3.Connection, schedule_id: int, error: str):
    conn.execute("""
        UPDATE content_schedule SET status='failed', error=?
        WHERE id=?
    """, (error[:500], schedule_id))
    conn.commit()


def get_batch_status(conn: sqlite3.Connection, batch_id: str = "") -> list[dict]:
    """Get status of all items in a batch (or latest batch)."""
    _init_schedule_db(conn)
    if not batch_id:
        row = conn.execute("SELECT batch_id FROM content_schedule ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return []
        batch_id = row["batch_id"]

    rows = conn.execute("""
        SELECT * FROM content_schedule WHERE batch_id = ? ORDER BY id
    """, (batch_id,)).fetchall()
    return [dict(r) for r in rows]


# ── Learning cycle ──────────────────────────────────────────────

LEARNING_STEPS = [
    ("ex19", ["--days-back", "30"]),              # Pull analytics
    ("ex24", ["--days-back", "30"]),              # Retention curves
    ("ex21", ["--min-samples", "3"]),             # Auto-adjust
    ("ex22", ["--ab-action", "auto"]),            # AB test conclusions
]


# ── Entry point ─────────────────────────────────────────────────

def run(
    settings: Settings,
    series: str = "",
    persona: str = "",
    dry_run: bool = False,
    theme: str = "",
) -> Path:
    log = build_logger("ex40", settings.output_dir / "logs" / "ex40.log")
    conn = get_db(settings.data_dir)

    personas = [persona] if persona else ["deep_mind", "cinephile", "pop_oracle"]

    log.info("Planning content batch: %s", ", ".join(personas))

    # Plan the batch
    batch = plan_batch(conn, personas=personas, series=series, force_theme=theme)

    # Display plan
    plan_text = format_batch_plan(batch)
    print(plan_text)
    log.info("Batch plan:\n%s", plan_text)

    # Save plan
    plan_path = settings.output_dir / "schedule"
    plan_path.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    plan_file = plan_path / f"batch_plan_{ts}.txt"
    plan_file.write_text(plan_text, encoding="utf-8")

    plan_json = plan_path / f"batch_plan_{ts}.json"
    plan_json.write_text(json.dumps(batch, indent=2, ensure_ascii=False), encoding="utf-8")

    if dry_run:
        log.info("Dry run — batch saved but NOT executing.")
        conn.close()
        return plan_file

    # Save to DB
    batch_id = save_batch(conn, batch)
    log.info("Batch saved: %s (%d items)", batch_id, len(batch))

    conn.close()

    # Return plan file — execution is done by run-content-cycle.ps1
    # which reads the schedule and runs each item's pipeline steps
    return plan_file
