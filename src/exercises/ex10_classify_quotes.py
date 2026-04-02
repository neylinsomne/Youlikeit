"""
ex10 - Clasificacion de frases con LLM gratuito (Groq / Gemini / Ollama).

Objetivo:
  - Clasifica cada frase con timestamp por: categoria, emocion, potencial viral,
    estilo de edicion sugerido y tipo de escena.
  - Usa un LLM gratuito para analizar el texto + contexto de la pelicula.
  - Tambien detecta escenas extendidas agrupando subtitulos consecutivos.

APIs gratuitas soportadas (en orden de prioridad):
  1. Groq  (llama3-8b): 30 req/min, gratis, rapido
  2. Gemini (gemini-2.5-flash): 15 req/min gratis
  3. Ollama local: sin limite, necesita GPU

Uso:
  python src/main.py ex10
  python src/main.py ex10 --provider groq
  python src/main.py ex10 --provider gemini
  python src/main.py ex10 --provider ollama --ollama-model mistral
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import requests

from common.config import Settings
from common.db import get_db
from common.logger import build_logger


# ── LLM Providers ────────────────────────────────────────────────────


CLASSIFY_PROMPT = """Analyze this movie quote and return ONLY a JSON object (no markdown, no explanation).

Movie: {movie_title} ({year})
Character: {character}
Quote: "{text}"

Return this exact JSON structure:
{{
  "category": "<one of: villain, romance, motivational, comedy, action, dramatic, horror>",
  "emotion": "<one of: anger, joy, sadness, fear, surprise, disgust, neutral>",
  "viral_score": <integer 1-10, how likely this works as a viral Short clip>,
  "edit_style": "<one of: zoom, slowmo, rapid_cut, freeze_frame, split_screen>",
  "scene_type": "<one of: dialogue, monologue, action, reaction, one_liner>"
}}

Scoring guide for viral_score:
- 9-10: Iconic, universally recognized, strong emotion, under 10 words
- 7-8: Memorable, strong emotion, good for compilation
- 5-6: Decent quote but needs visual context to work
- 3-4: Too long or too context-dependent
- 1-2: Generic dialogue, no standalone impact"""


def _call_groq(prompt: str, api_key: str) -> str:
    """Call Groq API (free: 30 req/min, llama3-8b)."""
    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": "llama3-8b-8192",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 200,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _call_gemini(prompt: str, api_key: str) -> str:
    """Call Gemini API (free: 15 req/min, gemini-2.5-flash)."""
    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}",
        headers={"Content-Type": "application/json"},
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=30,
    )
    resp.raise_for_status()
    candidates = resp.json().get("candidates", [])
    if candidates:
        parts = candidates[0].get("content", {}).get("parts", [])
        if parts:
            return parts[0].get("text", "")
    return ""


def _call_ollama(prompt: str, model: str = "mistral") -> str:
    """Call Ollama local API (free, no limit)."""
    resp = requests.post(
        "http://localhost:11434/api/generate",
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json().get("response", "")


def _parse_llm_response(raw: str) -> dict | None:
    """Extract JSON from LLM response, handling markdown code blocks."""
    # Strip markdown code fences
    cleaned = re.sub(r"```json\s*", "", raw)
    cleaned = re.sub(r"```\s*", "", cleaned)
    cleaned = cleaned.strip()

    # Find the JSON object
    match = re.search(r"\{[^}]+\}", cleaned, re.DOTALL)
    if not match:
        return None

    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return None

    # Validate required fields
    valid_categories = {"villain", "romance", "motivational", "comedy", "action", "dramatic", "horror"}
    valid_emotions = {"anger", "joy", "sadness", "fear", "surprise", "disgust", "neutral"}
    valid_styles = {"zoom", "slowmo", "rapid_cut", "freeze_frame", "split_screen"}
    valid_scenes = {"dialogue", "monologue", "action", "reaction", "one_liner"}

    category = data.get("category", "").lower()
    if category not in valid_categories:
        category = "dramatic"

    emotion = data.get("emotion", "").lower()
    if emotion not in valid_emotions:
        emotion = "neutral"

    viral = data.get("viral_score", 5)
    if not isinstance(viral, (int, float)):
        viral = 5
    viral = max(1, min(10, int(viral)))

    style = data.get("edit_style", "").lower().replace(" ", "_")
    if style not in valid_styles:
        style = "zoom"

    scene = data.get("scene_type", "").lower().replace(" ", "_")
    if scene not in valid_scenes:
        scene = "one_liner"

    return {
        "category": category,
        "emotion": emotion,
        "viral_score": viral,
        "edit_style": style,
        "scene_type": scene,
    }


# ── Fallback heuristic (no LLM needed) ──────────────────────────────


def _classify_heuristic(text: str, character: str) -> dict:
    """Simple rule-based classification when no LLM is available."""
    text_lower = text.lower()
    word_count = len(text.split())

    # Category detection
    villain_words = {"kill", "destroy", "power", "die", "dead", "blood", "revenge", "fear", "hate"}
    romance_words = {"love", "heart", "kiss", "beautiful", "forever", "darling", "miss you"}
    motivational_words = {"believe", "never give up", "fight", "hope", "dream", "strong", "courage"}
    comedy_words = {"funny", "laugh", "joke", "stupid", "crazy", "dude", "seriously"}
    horror_words = {"scared", "horror", "scream", "nightmare", "dark", "demon", "evil"}

    words_set = set(re.findall(r"[a-z]+", text_lower))

    if words_set & villain_words:
        category = "villain"
    elif words_set & romance_words:
        category = "romance"
    elif words_set & motivational_words:
        category = "motivational"
    elif words_set & comedy_words:
        category = "comedy"
    elif words_set & horror_words:
        category = "horror"
    elif "!" in text:
        category = "action"
    else:
        category = "dramatic"

    # Emotion from punctuation and keywords
    if "!" in text and any(w in text_lower for w in ("kill", "die", "hate", "no")):
        emotion = "anger"
    elif "?" in text:
        emotion = "surprise"
    elif any(w in text_lower for w in ("sad", "cry", "tears", "miss", "gone", "lost")):
        emotion = "sadness"
    elif any(w in text_lower for w in ("love", "happy", "beautiful", "smile")):
        emotion = "joy"
    elif any(w in text_lower for w in ("afraid", "scared", "fear", "dark")):
        emotion = "fear"
    else:
        emotion = "neutral"

    # Viral score heuristic
    viral = 5
    if word_count <= 6:
        viral += 2  # Short = more viral
    elif word_count <= 12:
        viral += 1
    elif word_count > 20:
        viral -= 2  # Too long

    if "!" in text:
        viral += 1
    if category in ("villain", "motivational"):
        viral += 1

    viral = max(1, min(10, viral))

    # Edit style
    if category == "action":
        style = "rapid_cut"
    elif category == "villain":
        style = "slowmo"
    elif category in ("romance", "dramatic"):
        style = "zoom"
    else:
        style = "zoom"

    # Scene type
    if word_count <= 5:
        scene_type = "one_liner"
    elif "..." in text or word_count > 25:
        scene_type = "monologue"
    else:
        scene_type = "dialogue"

    return {
        "category": category,
        "emotion": emotion,
        "viral_score": viral,
        "edit_style": style,
        "scene_type": scene_type,
    }


# ── Scene context detection ──────────────────────────────────────────


def _detect_scene_context(conn, quote_id: int, movie_id: int, start_ms: int, end_ms: int) -> tuple[int, int]:
    """
    Suggest extended context window by looking at neighboring quotes.

    If there are other quotes from the same movie within 10s of this one,
    extend the window to include them (for scene breathing room).
    """
    cur = conn.execute(
        """SELECT start_ms, end_ms FROM quotes
           WHERE movie_id = ? AND id != ? AND start_ms IS NOT NULL
           ORDER BY start_ms""",
        (movie_id, quote_id),
    )
    neighbors = cur.fetchall()

    context_start = start_ms
    context_end = end_ms
    margin = 10000  # 10 seconds

    for n in neighbors:
        n_start = n["start_ms"]
        n_end = n["end_ms"]
        # If neighbor is within 10s before/after, extend
        if n_end >= start_ms - margin and n_start <= end_ms + margin:
            context_start = min(context_start, n_start)
            context_end = max(context_end, n_end)

    # Add 2s padding for scene breathing
    context_start = max(0, context_start - 2000)
    context_end = context_end + 2000

    return context_start, context_end


# ── Entry point ──────────────────────────────────────────────────────


def run(
    settings: Settings,
    provider: str = "auto",
    ollama_model: str = "mistral",
    batch_size: int = 50,
) -> Path:
    log = build_logger("ex10", settings.output_dir / "logs" / "ex10.log")
    conn = get_db(settings.data_dir)

    # Migrate: add new columns if they don't exist
    _migrate_schema(conn)

    # Get quotes with timestamps but without classification
    cur = conn.execute(
        """SELECT q.*, m.title as movie_title, m.year, m.genre
           FROM quotes q
           JOIN movies m ON q.movie_id = m.id
           WHERE q.start_ms IS NOT NULL AND q.category IS NULL
           ORDER BY q.confidence DESC
           LIMIT ?""",
        (batch_size,),
    )
    quotes = [dict(r) for r in cur.fetchall()]

    if not quotes:
        log.info("All quotes already classified.")
        report_path = settings.output_dir / "logs" / "ex10_classify_report.txt"
        report_path.write_text("ex10 - All quotes already classified.\n", encoding="utf-8")
        conn.close()
        return report_path

    log.info(f"Classifying {len(quotes)} quotes...")

    # Detect provider - unified LLM provider with project context
    from common.llm_provider import LLMProvider
    llm = LLMProvider(settings, conn=conn, preferred_provider=provider if provider != "auto" else "auto")

    call_fn = None
    provider_name = provider

    if provider == "heuristic":
        provider_name = "heuristic"
    elif provider == "ollama":
        call_fn = lambda p: _call_ollama(p, ollama_model)
        provider_name = "ollama"
    elif llm.is_available():
        # Use unified provider (airllm → groq → gemini cascade)
        call_fn = lambda p: llm.generate(p, task_type="classification", max_tokens=300)
        available = llm.available_providers()
        provider_name = available[0] if available else "heuristic"
        if not available:
            call_fn = None
            provider_name = "heuristic"
    else:
        provider_name = "heuristic"

    log.info(f"Using provider: {provider_name}")

    classified = 0
    errors = 0
    report_lines = [
        "ex10 - Quote Classification Report",
        "=" * 50,
        f"Provider: {provider_name}",
        f"Quotes to classify: {len(quotes)}",
        "",
    ]

    # Rate limiting: Groq = 30/min, Gemini = 15/min
    delay = 0
    if provider_name == "groq":
        delay = 2.1  # ~28 req/min (safe under 30)
    elif provider_name == "gemini":
        delay = 4.1  # ~14 req/min (safe under 15)

    for q in quotes:
        prompt = CLASSIFY_PROMPT.format(
            movie_title=q.get("movie_title", "Unknown"),
            year=q.get("year", ""),
            character=q.get("character_name") or "Unknown",
            text=q["text"][:300],
        )

        result = None
        if call_fn:
            try:
                raw = call_fn(prompt)
                result = _parse_llm_response(raw)
                if delay > 0:
                    time.sleep(delay)
            except Exception as e:
                log.warning(f"LLM error for quote {q['id']}: {e}")
                errors += 1

        # Fallback to heuristic
        if not result:
            result = _classify_heuristic(q["text"], q.get("character_name", ""))

        # Detect scene context
        ctx_start, ctx_end = _detect_scene_context(
            conn, q["id"], q["movie_id"], q["start_ms"], q["end_ms"]
        )

        # Update DB
        conn.execute(
            """UPDATE quotes SET
                category = ?, emotion = ?, viral_score = ?,
                edit_style = ?, scene_type = ?,
                context_before_ms = ?, context_after_ms = ?
               WHERE id = ?""",
            (
                result["category"],
                result["emotion"],
                result["viral_score"],
                result["edit_style"],
                result["scene_type"],
                ctx_start,
                ctx_end,
                q["id"],
            ),
        )
        conn.commit()
        classified += 1

        report_lines.append(
            f"[{result['viral_score']:2d}/10] {result['category']:12s} | "
            f"{result['emotion']:8s} | {result['scene_type']:10s} | "
            f"{q.get('movie_title', '')}: \"{q['text'][:60]}\""
        )

    report_lines.insert(4, f"Classified: {classified} | Errors: {errors}")

    # Stats summary
    report_lines.append("")
    report_lines.append("Category distribution:")
    cur = conn.execute(
        "SELECT category, COUNT(*) as cnt FROM quotes WHERE category IS NOT NULL GROUP BY category ORDER BY cnt DESC"
    )
    for row in cur.fetchall():
        report_lines.append(f"  {row['category']}: {row['cnt']}")

    report_lines.append("")
    report_lines.append("Viral score distribution:")
    cur = conn.execute(
        "SELECT viral_score, COUNT(*) as cnt FROM quotes WHERE viral_score IS NOT NULL GROUP BY viral_score ORDER BY viral_score DESC"
    )
    for row in cur.fetchall():
        report_lines.append(f"  Score {row['viral_score']}: {row['cnt']} quotes")

    # Re-index classified quotes in ChromaDB with enriched metadata
    _update_chromadb_metadata(conn, settings.data_dir, log)

    report_path = settings.output_dir / "logs" / "ex10_classify_report.txt"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    log.info(f"Report saved: {report_path}")

    conn.close()
    return report_path


def _update_chromadb_metadata(conn, data_dir: Path, log) -> None:
    """Re-index quotes in ChromaDB with classification metadata."""
    try:
        import chromadb
    except ImportError:
        log.info("ChromaDB not installed, skipping vector re-index.")
        return

    db_path = data_dir / "chromadb"
    if not db_path.exists():
        log.info("No ChromaDB directory found, skipping.")
        return

    client = chromadb.PersistentClient(path=str(db_path))
    try:
        collection = client.get_or_create_collection(
            name="movie_quotes",
            metadata={"hnsw:space": "cosine"},
        )
    except Exception as e:
        log.warning(f"ChromaDB error: {e}")
        return

    cur = conn.execute(
        """SELECT q.*, m.title as movie_title
           FROM quotes q JOIN movies m ON q.movie_id = m.id
           WHERE q.start_ms IS NOT NULL AND q.category IS NOT NULL"""
    )
    quotes = [dict(r) for r in cur.fetchall()]

    if not quotes:
        return

    updated = 0
    for q in quotes:
        doc_id = f"quote_{q['id']}"
        meta = {
            "movie_title": q.get("movie_title", ""),
            "movie_id": q["movie_id"],
            "start_ms": q["start_ms"],
            "end_ms": q["end_ms"],
            "character": q.get("character_name") or "",
            "confidence": q.get("confidence", 0),
            "category": q.get("category", ""),
            "emotion": q.get("emotion", ""),
            "viral_score": q.get("viral_score", 0),
            "edit_style": q.get("edit_style", ""),
            "scene_type": q.get("scene_type", ""),
        }
        try:
            collection.upsert(
                documents=[q["text"]],
                metadatas=[meta],
                ids=[doc_id],
            )
            updated += 1
        except Exception:
            pass

    log.info(f"ChromaDB: updated {updated} quotes with classification metadata")


def _migrate_schema(conn):
    """Add new columns to quotes table if they don't exist."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(quotes)").fetchall()}
    new_cols = {
        "category": "TEXT",
        "emotion": "TEXT",
        "viral_score": "INTEGER",
        "edit_style": "TEXT",
        "context_before_ms": "INTEGER",
        "context_after_ms": "INTEGER",
        "scene_type": "TEXT",
    }
    for col, typ in new_cols.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE quotes ADD COLUMN {col} {typ}")
    conn.commit()
