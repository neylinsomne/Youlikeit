"""ex37 - Classify manga/anime quotes (category, emotion, viral score).

ETL Pattern:
  Extract:  Unclassified quotes from manga_quotes table
  Transform: Classify with Gemini (same LLM provider as ex10)
  Load:     Update manga_quotes with classification fields

Reuses the same LLM infrastructure as ex10 for movies.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from core.config import Settings
from core.db import get_db
from integrations.llm_provider import LLMProvider

log = logging.getLogger(__name__)


MANGA_SYSTEM_PROMPT = """You classify anime/manga quotes for YouTube Shorts.
For each quote, return a JSON object with:
- category: villain, motivational, comedy, dramatic, romantic, philosophical, action, horror
- emotion: anger, joy, sadness, fear, surprise, disgust, neutral, determination, melancholy
- viral_score: 1-10 (how likely to go viral on YouTube Shorts)
- edit_style: zoom, slowmo, rapid_cut, freeze_frame, split_screen, ken_burns
- scene_type: monologue, dialogue, battle_cry, inner_thought, narration, one_liner

Consider anime/manga aesthetics: epic battle moments, philosophical monologues,
and emotional turning points tend to score highest for Shorts.
Return ONLY valid JSON, no markdown."""


def _get_unclassified(conn, batch_size: int) -> list:
    """Get manga quotes without classification."""
    cur = conn.execute(
        """SELECT mq.id, mq.text, mq.character_name, ms.title, ms.media_type, ms.genres
           FROM manga_quotes mq
           JOIN manga_series ms ON mq.series_id = ms.id
           WHERE mq.category IS NULL
           ORDER BY ms.composite_score DESC
           LIMIT ?""",
        (batch_size,),
    )
    return cur.fetchall()


def _classify_batch(quotes: list, conn, provider: str = "auto") -> list[dict]:
    """Classify a batch of manga quotes using LLM."""
    llm = LLMProvider(conn)
    results = []
    for q in quotes:
        prompt = (
            f'Anime/Manga: {q["title"]} ({q["media_type"]})\n'
            f'Character: {q["character_name"] or "Unknown"}\n'
            f'Genres: {q["genres"]}\n'
            f'Quote: "{q["text"]}"\n\n'
            f"Classify this quote. Return JSON with: category, emotion, viral_score, edit_style, scene_type"
        )
        try:
            raw = llm.generate(prompt, task="classify_manga", extra_system=MANGA_SYSTEM_PROMPT)
            if raw:
                # Parse JSON from response
                import re
                json_match = re.search(r'\{[^}]+\}', raw)
                if json_match:
                    result = json.loads(json_match.group())
                    result["quote_id"] = q["id"]
                    results.append(result)
        except Exception as e:
            log.warning(f"LLM error for quote {q['id']}: {e}")

    return results


def _heuristic_classify(quote: dict) -> dict:
    """Fallback heuristic classifier for manga quotes."""
    text = (quote["text"] or "").lower()
    genres = (quote["genres"] or "").lower()

    # Category detection
    category = "dramatic"
    villain_words = ["kill", "destroy", "weak", "power", "fear", "death", "crush", "pathetic"]
    motivational_words = ["dream", "protect", "never give up", "strong", "believe", "hope", "fight for"]
    comedy_words = ["idiot", "fool", "stupid", "haha", "funny", "joke"]
    philosophical_words = ["meaning", "life", "truth", "justice", "world", "human", "existence"]
    romantic_words = ["love", "heart", "feel", "together", "promise"]

    if any(w in text for w in villain_words):
        category = "villain"
    elif any(w in text for w in motivational_words):
        category = "motivational"
    elif any(w in text for w in comedy_words):
        category = "comedy"
    elif any(w in text for w in philosophical_words):
        category = "philosophical"
    elif any(w in text for w in romantic_words):
        category = "romantic"
    elif "action" in genres:
        category = "action"

    # Emotion
    emotion = "determination"
    if any(w in text for w in ["sad", "cry", "tears", "pain", "lost"]):
        emotion = "sadness"
    elif any(w in text for w in ["anger", "rage", "furious", "hate"]):
        emotion = "anger"
    elif any(w in text for w in ["happy", "joy", "laugh", "smile"]):
        emotion = "joy"
    elif any(w in text for w in ["fear", "scared", "terrif"]):
        emotion = "fear"

    # Viral score based on length and category
    viral_score = 6
    if len(text) < 100 and category in ("villain", "motivational", "philosophical"):
        viral_score = 8
    elif len(text) > 200:
        viral_score = 5

    return {
        "quote_id": quote["id"],
        "category": category,
        "emotion": emotion,
        "viral_score": viral_score,
        "edit_style": "ken_burns",
        "scene_type": "monologue",
    }


def run(settings: Settings, provider: str = "auto", batch_size: int = 50) -> str:
    """Classify manga/anime quotes."""
    data_dir = Path(settings.data_dir)
    conn = get_db(data_dir)

    # Check manga tables exist
    try:
        conn.execute("SELECT 1 FROM manga_quotes LIMIT 1")
    except Exception:
        log.error("manga_quotes table not found. Run ex36 first.")
        return ""

    quotes = _get_unclassified(conn, batch_size)
    if not quotes:
        log.info("All manga quotes already classified")
        return ""

    log.info(f"Classifying {len(quotes)} manga quotes...")

    # Try LLM first, fallback to heuristic
    classified = []
    if provider != "heuristic":
        try:
            classified = _classify_batch(quotes, conn, provider)
            log.info(f"LLM classified: {len(classified)}/{len(quotes)}")
        except Exception as e:
            log.warning(f"LLM failed, using heuristic: {e}")

    # Heuristic for remaining
    classified_ids = {c["quote_id"] for c in classified}
    for q in quotes:
        if q["id"] not in classified_ids:
            classified.append(_heuristic_classify(dict(q)))

    # Update DB
    for c in classified:
        conn.execute(
            """UPDATE manga_quotes SET category = ?, emotion = ?, viral_score = ?
               WHERE id = ?""",
            (c.get("category"), c.get("emotion"), c.get("viral_score"), c["quote_id"]),
        )
    conn.commit()
    log.info(f"Updated {len(classified)} quotes in DB")

    # Report
    report_dir = Path(settings.output_dir) / "logs"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"ex37_manga_classify_{datetime.now():%Y%m%d_%H%M%S}.txt"

    # Distribution
    cur = conn.execute(
        "SELECT category, COUNT(*) as n FROM manga_quotes WHERE category IS NOT NULL GROUP BY category ORDER BY n DESC"
    )
    dist = {row["category"]: row["n"] for row in cur.fetchall()}
    log.info(f"Classification distribution: {dist}")

    lines = [
        "ex37 - Manga/Anime Quote Classification Report",
        "=" * 50,
        f"Classified: {len(classified)} quotes",
        f"Provider: {provider}",
        "",
        "Distribution:",
    ]
    for cat, n in dist.items():
        lines.append(f"  {cat}: {n}")

    lines.append("")
    lines.append("Sample classified quotes:")
    cur = conn.execute(
        """SELECT mq.text, mq.character_name, mq.category, mq.emotion, mq.viral_score, ms.title
           FROM manga_quotes mq JOIN manga_series ms ON mq.series_id = ms.id
           WHERE mq.category IS NOT NULL
           ORDER BY mq.viral_score DESC LIMIT 10"""
    )
    for row in cur.fetchall():
        lines.append(
            f"  [{row['viral_score']}/10] [{row['category']}] [{row['emotion']}] "
            f"{row['title']} - {row['character_name']}: {row['text'][:60]}"
        )

    report_path.write_text("\n".join(lines), encoding="utf-8")
    log.info(f"Report: {report_path}")
    return str(report_path)
