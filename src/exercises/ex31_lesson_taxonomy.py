"""
ex31 - ETL: Taxonomía pedagógica de frases de cine.

Extract: quotes con categoría/emoción (de ex10)
Transform: Clasificar por tipo de aprendizaje + extraer lección de vida
Load: actualizar quotes con learning_type, life_lesson, curriculum_area

Tipos de aprendizaje:
  - critical_thinking: cuestionar, analizar, no aceptar lo dado
  - emotional_intelligence: entender emociones propias y ajenas
  - ethics: distinguir bien y mal, dilemas morales
  - creativity: pensar diferente, soluciones no obvias
  - resilience: superar adversidad, persistir
  - self_awareness: conocerse, aceptarse, mejorar
  - empathy: ponerse en el lugar del otro
  - decision_making: elegir bien bajo incertidumbre

Áreas curriculares:
  - character: desarrollo personal, identidad
  - relationships: amor, amistad, familia, traición
  - society: poder, justicia, sistema, corrupción
  - self: autoconocimiento, crecimiento, superación
  - conflict: guerra, rivalidad, venganza, confrontación

Usa LLM (Groq/Gemini gratis) o heurístico como fallback.

Uso:
  python src/main.py ex31
  python src/main.py ex31 --batch-size 50 --provider heuristic
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

import requests

from common.config import Settings
from common.db import get_db
from common.logger import build_logger
from common.websocket_hub import ETLTracker


# ---------------------------------------------------------------------------
# Heuristic mapping (no LLM needed)
# ---------------------------------------------------------------------------

# category + emotion → learning_type mapping
HEURISTIC_MAP: dict[tuple[str, str], list[str]] = {
    ("villain", "anger"): ["ethics", "critical_thinking"],
    ("villain", "fear"): ["ethics", "resilience"],
    ("villain", "neutral"): ["critical_thinking", "decision_making"],
    ("villain", "surprise"): ["critical_thinking"],
    ("romance", "joy"): ["emotional_intelligence", "empathy"],
    ("romance", "sadness"): ["emotional_intelligence", "self_awareness"],
    ("romance", "neutral"): ["empathy", "relationships"],
    ("motivational", "joy"): ["resilience", "self_awareness"],
    ("motivational", "neutral"): ["resilience", "decision_making"],
    ("motivational", "anger"): ["resilience", "critical_thinking"],
    ("comedy", "joy"): ["creativity", "self_awareness"],
    ("comedy", "surprise"): ["creativity", "critical_thinking"],
    ("action", "anger"): ["decision_making", "resilience"],
    ("action", "fear"): ["resilience", "decision_making"],
    ("action", "surprise"): ["decision_making", "critical_thinking"],
    ("dramatic", "sadness"): ["emotional_intelligence", "empathy"],
    ("dramatic", "anger"): ["ethics", "critical_thinking"],
    ("dramatic", "neutral"): ["critical_thinking", "self_awareness"],
    ("dramatic", "fear"): ["empathy", "resilience"],
    ("horror", "fear"): ["resilience", "self_awareness"],
    ("horror", "surprise"): ["critical_thinking"],
}

# category → curriculum_area
CURRICULUM_MAP: dict[str, str] = {
    "villain": "conflict",
    "romance": "relationships",
    "motivational": "self",
    "comedy": "character",
    "action": "conflict",
    "dramatic": "character",
    "horror": "self",
}

# Templates for life_lesson extraction (heuristic)
LESSON_TEMPLATES: dict[str, list[str]] = {
    "critical_thinking": [
        "No todo es lo que parece. Cuestiona antes de aceptar.",
        "Las verdades más incómodas son las más necesarias.",
        "Pensar diferente no es rebeldía, es inteligencia.",
    ],
    "emotional_intelligence": [
        "Las emociones no son debilidad, son información.",
        "Entender lo que sientes es el primer paso para decidir bien.",
        "A veces el silencio dice más que las palabras.",
    ],
    "ethics": [
        "El poder sin ética es destrucción.",
        "Hacer lo correcto rara vez es hacer lo fácil.",
        "Los límites entre el bien y el mal son más borrosos de lo que pensamos.",
    ],
    "creativity": [
        "Las mejores soluciones vienen de donde menos las esperas.",
        "Romper las reglas requiere primero entenderlas.",
        "La creatividad es ver conexiones donde otros ven caos.",
    ],
    "resilience": [
        "Caer no es fracasar. Quedarse en el suelo sí.",
        "La adversidad revela quién eres realmente.",
        "Lo que no te destruye te transforma.",
    ],
    "self_awareness": [
        "Conocerte es el viaje más largo y el más necesario.",
        "Aceptar lo que eres es diferente a conformarte.",
        "Tus peores enemigos viven dentro de ti.",
    ],
    "empathy": [
        "Entender al otro no significa estar de acuerdo.",
        "Todos son el héroe de su propia historia.",
        "Juzgar es fácil. Comprender requiere coraje.",
    ],
    "decision_making": [
        "Toda decisión tiene un costo. La inacción también.",
        "En la incertidumbre, decide con lo que tienes.",
        "Las mejores decisiones se toman con la cabeza fría y el corazón abierto.",
    ],
}


# ---------------------------------------------------------------------------
# EXTRACT
# ---------------------------------------------------------------------------

def _extract_unclassified_quotes(conn, batch_size: int = 50) -> list[dict]:
    """Get quotes that have category/emotion but no learning_type yet."""
    cur = conn.execute("""
        SELECT q.id, q.text, q.character_name, q.category, q.emotion,
               q.scene_type, q.viral_score, m.title as movie_title
        FROM quotes q
        JOIN movies m ON q.movie_id = m.id
        WHERE q.category IS NOT NULL
          AND q.learning_type IS NULL
        ORDER BY q.viral_score DESC, q.confidence DESC
        LIMIT ?
    """, (batch_size,))
    return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# TRANSFORM
# ---------------------------------------------------------------------------

def _classify_heuristic(quote: dict) -> dict:
    """Classify a quote using the heuristic mapping."""
    category = (quote.get("category") or "").lower()
    emotion = (quote.get("emotion") or "neutral").lower()

    key = (category, emotion)
    learning_types = HEURISTIC_MAP.get(key)

    if not learning_types:
        # Fallback: try just category with neutral
        key = (category, "neutral")
        learning_types = HEURISTIC_MAP.get(key, ["critical_thinking"])

    learning_type = learning_types[0]
    curriculum_area = CURRICULUM_MAP.get(category, "character")

    # Pick a life lesson template
    import random
    random.seed(hash(quote.get("text", "")) % 2**32)
    templates = LESSON_TEMPLATES.get(learning_type, LESSON_TEMPLATES["critical_thinking"])
    life_lesson = random.choice(templates)

    return {
        "learning_type": learning_type,
        "life_lesson": life_lesson,
        "curriculum_area": curriculum_area,
    }


def _classify_llm_batch(quotes: list[dict], provider: str = "auto") -> list[dict]:
    """Classify quotes using LLM (Groq or Gemini)."""
    groq_key = os.getenv("GROQ_API_KEY", "")
    gemini_key = os.getenv("GEMINI_API_KEY", "")

    if provider == "auto":
        if groq_key:
            provider = "groq"
        elif gemini_key:
            provider = "gemini"
        else:
            return [_classify_heuristic(q) for q in quotes]

    # Build prompt
    quotes_text = "\n".join(
        f'{i+1}. [{q.get("category","?")}|{q.get("emotion","?")}] '
        f'"{q.get("text","")[:100]}" - {q.get("movie_title","?")}'
        for i, q in enumerate(quotes[:10])
    )

    prompt = f"""Classify these movie quotes by learning type and extract a life lesson.

Quotes:
{quotes_text}

For each quote, respond in JSON array:
[
  {{
    "index": 1,
    "learning_type": "critical_thinking|emotional_intelligence|ethics|creativity|resilience|self_awareness|empathy|decision_making",
    "life_lesson": "One sentence life lesson this quote teaches (in Spanish)",
    "curriculum_area": "character|relationships|society|self|conflict"
  }},
  ...
]

Rules:
- learning_type must be one of the 8 options listed
- life_lesson should be a universal truth, not a movie summary
- Write life_lesson in Spanish
- Be concise"""

    result = None

    if provider == "groq" and groq_key:
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                json={
                    "model": "llama-3.1-8b-instant",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.5,
                    "max_tokens": 1000,
                },
                timeout=15,
            )
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                match = re.search(r"\[.*\]", content, re.DOTALL)
                if match:
                    result = json.loads(match.group())
        except Exception:
            pass

    if not result and provider == "gemini" and gemini_key:
        try:
            resp = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gemini_key}",
                headers={"Content-Type": "application/json"},
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=15,
            )
            if resp.status_code == 200:
                content = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                match = re.search(r"\[.*\]", content, re.DOTALL)
                if match:
                    result = json.loads(match.group())
        except Exception:
            pass

    if not result:
        return [_classify_heuristic(q) for q in quotes]

    # Map LLM results to quotes
    classifications = []
    for i, q in enumerate(quotes):
        llm_entry = next((r for r in result if r.get("index") == i + 1), None)
        if llm_entry:
            classifications.append({
                "learning_type": llm_entry.get("learning_type", "critical_thinking"),
                "life_lesson": llm_entry.get("life_lesson", ""),
                "curriculum_area": llm_entry.get("curriculum_area", "character"),
            })
        else:
            classifications.append(_classify_heuristic(q))

    # Fill remaining with heuristic
    while len(classifications) < len(quotes):
        classifications.append(_classify_heuristic(quotes[len(classifications)]))

    return classifications


# ---------------------------------------------------------------------------
# LOAD
# ---------------------------------------------------------------------------

def _load_classifications(conn, quotes: list[dict], classifications: list[dict]):
    """Update quotes with learning_type, life_lesson, curriculum_area."""
    for quote, clf in zip(quotes, classifications):
        conn.execute("""
            UPDATE quotes SET
                learning_type = ?,
                life_lesson = ?,
                curriculum_area = ?
            WHERE id = ?
        """, (
            clf["learning_type"],
            clf["life_lesson"],
            clf["curriculum_area"],
            quote["id"],
        ))


# ---------------------------------------------------------------------------
# Main ETL
# ---------------------------------------------------------------------------

def run(
    settings: Settings,
    batch_size: int = 50,
    provider: str = "auto",
) -> Path:
    log = build_logger("ex31", settings.output_dir / "logs" / "ex31.log")
    conn = get_db(settings.data_dir)
    tracker = ETLTracker("ex31")

    # Extract
    tracker.extract_start()
    quotes = _extract_unclassified_quotes(conn, batch_size)
    tracker.extract_done({"quotes_to_classify": len(quotes)})
    log.info("Extract: %d quotes to classify", len(quotes))

    if not quotes:
        out = settings.output_dir / "logs" / "ex31_no_quotes.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("ex31: All quotes already classified or none have category.\nRun ex10 first.", encoding="utf-8")
        conn.close()
        return out

    # Transform
    tracker.transform_start(f"Classifying {len(quotes)} quotes (provider: {provider})")

    # Process in batches of 10 for LLM
    all_classifications = []
    for batch_start in range(0, len(quotes), 10):
        batch = quotes[batch_start:batch_start + 10]
        tracker.transform_progress(batch_start, len(quotes), f"batch {batch_start//10 + 1}")

        if provider == "heuristic":
            clfs = [_classify_heuristic(q) for q in batch]
        else:
            clfs = _classify_llm_batch(batch, provider)

        all_classifications.extend(clfs)

    tracker.transform_done({"classified": len(all_classifications)})

    # Count by type
    type_counts: dict[str, int] = {}
    for clf in all_classifications:
        lt = clf.get("learning_type", "unknown")
        type_counts[lt] = type_counts.get(lt, 0) + 1

    log.info("Classification distribution: %s", type_counts)

    # Load
    tracker.load_start()
    _load_classifications(conn, quotes, all_classifications)
    conn.commit()
    tracker.load_done({"updated": len(quotes)})

    # Knowledge base: record distribution
    conn.execute("""
        INSERT INTO knowledge_base (category, topic, title, content, confidence, source)
        VALUES ('insight', 'pedagogy', ?, ?, 0.7, 'lesson_taxonomy')
    """, (
        f"Lesson distribution: {len(quotes)} quotes classified",
        json.dumps(type_counts, ensure_ascii=False),
    ))
    conn.commit()

    # Report
    tracker.complete({"quotes": len(quotes), "types": len(type_counts)})

    out_dir = settings.output_dir / "analytics"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    report_path = out_dir / f"ex31_lessons_{ts}.txt"
    lines = [
        "ex31 - Lesson Taxonomy Report",
        "=" * 50,
        f"Quotes classified: {len(quotes)}",
        f"Provider: {provider}",
        "",
        "Learning type distribution:",
    ]
    for lt, count in sorted(type_counts.items(), key=lambda x: x[1], reverse=True):
        bar = "█" * (count * 2)
        lines.append(f"  {lt:25s} {count:3d} {bar}")

    lines.append("")
    lines.append("Sample classifications:")
    for q, clf in zip(quotes[:5], all_classifications[:5]):
        lines.append(f"  \"{q.get('text', '')[:60]}...\"")
        lines.append(f"    → {clf['learning_type']} | {clf['curriculum_area']}")
        lines.append(f"    → {clf['life_lesson']}")
        lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    conn.close()
    log.info("Lesson taxonomy report: %s", report_path)
    return report_path
