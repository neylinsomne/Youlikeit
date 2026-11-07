"""Guion de una lección: gancho, narración y texto en pantalla por tramo, cierre.

Con IA: `llm_json.complete_json` con esquema validado (lessons.SCRIPT_SCHEMA).
Los HECHOS (títulos, años) salen SOLO de la DB: van en el prompt como datos y
la respuesta se rechaza si menciona un año que no está entre las obras.
Tono: empatía y alfabetización emocional (nombrar lo que se siente, notar el
cuerpo, sin juicios ni diagnósticos), frases cortas.

Sin IA: plantilla armada con el vocabulario (data/vocab). `generate_script`
guarda la plantilla (si la lección no tenía un guion propio) y levanta
ScriptUnavailable → la API responde 502 y la lección queda con la plantilla.
"""
from __future__ import annotations

import logging
import re
import sqlite3

from apps.moments import vocab
from apps.supercut import lessons
from integrations.ai import llm_json

log = logging.getLogger(__name__)

WORDS_PER_SECOND = 2.2          # ritmo cómodo de edge-tts en español (≈ 2.5 palabras/s)
MAX_CAPTION_WORDS = 7
_YEAR_RE = re.compile(r"\b(1[89]\d\d|20\d\d)\b")


class ScriptUnavailable(RuntimeError):
    """No hubo LLM (o devolvió datos inventados): la lección queda con la plantilla."""


_PROMPTS = {
    "es": ["¿Dónde lo sientes en el cuerpo?", "Nómbralo: {label}.", "Observa sin juzgar.",
           "No estás solo en esto.", "Respira y vuelve a mirar."],
    "en": ["Where do you feel it in your body?", "Name it: {label}.", "Notice without judging.",
           "You are not alone in this.", "Breathe and look again."],
}
_OUTRO = {"es": "Ponerle nombre a lo que sientes ya es un primer paso.",
          "en": "Naming what you feel is already a first step."}

SYSTEM = {
    "es": (
        "Eres guionista de micro-lecciones de alfabetización emocional hechas con escenas de cine. "
        "Tono: empático, cálido, sin juicios, sin diagnósticos ni consejos médicos. Frases cortas y claras, "
        "en español neutro.\n"
        "Reglas:\n"
        "- Usa SOLO los títulos y años que te doy. No inventes actores, directores, fechas ni datos.\n"
        "- No reveles el final de las películas.\n"
        "- hook: una pregunta o frase de máximo 12 palabras que invite a mirar.\n"
        "- segments: uno por tramo, con el mismo idx. narration nombra la emoción y qué se nota en el cuerpo "
        "o en la conducta, sin pasar de max_palabras. caption: texto en pantalla de máximo 7 palabras.\n"
        "- outro: máximo 8 palabras; invita a pausar y respirar.\n"
        "Responde SOLO con JSON."),
    "en": (
        "You write emotional-literacy micro-lessons built from film scenes. Tone: empathetic, warm, "
        "non-judgmental, no diagnoses or medical advice. Short, clear sentences.\n"
        "Rules:\n"
        "- Use ONLY the titles and years given. Do not invent actors, directors, dates or facts.\n"
        "- No spoilers about endings.\n"
        "- hook: a question or line of at most 12 words that invites the viewer to watch.\n"
        "- segments: one per clip, same idx. narration names the emotion and what shows in the body or "
        "behaviour, within max_words. caption: on-screen text of at most 7 words.\n"
        "- outro: at most 8 words; invites a pause and a slow breath.\n"
        "Reply with JSON ONLY."),
}


def _lang(lang: str) -> str:
    return "es" if (lang or "es").lower().startswith("es") else "en"


def _first_sentence(text: str | None) -> str:
    if not text:
        return ""
    return re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0]


def _work(title: str | None, year: int | None) -> str:
    title = title or "?"
    return f"{title} ({year})" if year else title


def template_script(dimension: str, value: str, items: list[dict], *, lang: str = "es") -> dict:
    """Guion sin IA a partir del vocabulario. items: [{work_title, work_year}] en orden."""
    lg = _lang(lang)
    entry = vocab.entry(dimension, value) or {}
    label = entry.get(lg) or entry.get("es") or value.replace("_", " ")
    desc = _first_sentence(entry.get(f"desc_{lg}") or entry.get("desc_es"))
    if lg == "es":
        hook = f"{label}. {desc}" if desc else f"{label}: mira cómo lo muestra el cine."
    else:
        hook = f"{label}. {desc}" if desc else f"{label}: see how film shows it."
    prompts = _PROMPTS[lg]
    segments = []
    for i, it in enumerate(items):
        prompt = prompts[i % len(prompts)].format(label=label.lower())
        title, year = it.get("work_title"), it.get("work_year")
        lead = f"{title}, {year}." if year else f"{title}."
        segments.append({"idx": i, "narration": f"{lead} {prompt}", "caption": prompt})
    return {"hook": hook, "outro": _OUTRO[lg], "segments": segments}


def build_prompt(lesson: dict, items: list[dict], label: str, desc: str) -> str:
    lg = _lang(lesson["lang"])
    lines = []
    for it in items:
        secs = max(1.0, (it["out_ms"] - it["in_ms"]) / 1000)
        dialog = (it.get("text") or "").strip().replace("\n", " ")[:300] or "(sin diálogo)"
        summary = (it.get("summary_es") or "").strip()[:200]
        key = "max_palabras" if lg == "es" else "max_words"
        lines.append(f'- idx={it["idx"]} | obra: {_work(it["work_title"], it["work_year"])} | '
                     f'duración: {secs:.1f} s | {key}: {max(4, int(secs * WORDS_PER_SECOND))} | '
                     f'diálogo: "{dialog}"' + (f" | resumen: {summary}" if summary else ""))
    if lg == "es":
        head = f"Tema de la lección: {label}" + (f" ({desc})" if desc else "") + "\nTramos (en orden):\n"
    else:
        head = f"Lesson theme: {label}" + (f" ({desc})" if desc else "") + "\nClips (in order):\n"
    return head + "\n".join(lines)


def _facts_ok(data: dict, allowed_years: set[int]) -> bool:
    texts = [data.get("hook", ""), data.get("outro", "")]
    for s in data.get("segments", []):
        texts += [s.get("narration", ""), s.get("caption", "")]
    found = {int(y) for t in texts for y in _YEAR_RE.findall(t or "")}
    return found <= allowed_years


def _normalize(data: dict, template: dict, n_items: int) -> dict:
    """Un segmento por tramo (idx 0..n-1). Los que falten salen de la plantilla."""
    by_idx = {}
    for s in data.get("segments", []):
        try:
            idx = int(s["idx"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= idx < n_items and idx not in by_idx:
            by_idx[idx] = {"idx": idx, "narration": str(s.get("narration", "")).strip(),
                           "caption": str(s.get("caption", "")).strip()}
    segments = []
    for i in range(n_items):
        seg = by_idx.get(i) or template["segments"][i]
        if not seg["caption"]:
            seg = {**seg, "caption": template["segments"][i]["caption"]}
        segments.append(seg)
    return {"hook": str(data.get("hook", "")).strip() or template["hook"],
            "outro": str(data.get("outro", "")).strip() or template["outro"], "segments": segments}


def generate_script(conn: sqlite3.Connection, lesson_id: int, provider: str | None = None) -> dict:
    """Genera el guion con el LLM y actualiza captions. Devuelve el Lesson.

    Levanta ScriptUnavailable si no hay LLM o inventó datos (queda la plantilla),
    InvalidState si la lección está rendering/published.
    """
    lesson = lessons.get_lesson(conn, lesson_id)
    if lesson["status"] in lessons.LOCKED:
        raise lessons.InvalidState(f"La lección está '{lesson['status']}': no se puede editar")
    items = lessons.get_items(conn, lesson_id)
    if not items:
        raise lessons.InvalidState("La lección no tiene tramos")
    dimension, _, value = lesson["spec"].partition(":")
    lg = _lang(lesson["lang"])
    entry = vocab.entry(dimension, value) if dimension in vocab.DIMENSIONS else None
    label = (entry or {}).get(lg) or value.replace("_", " ")
    desc = _first_sentence((entry or {}).get(f"desc_{lg}"))
    template = template_script(dimension, value, items, lang=lg)

    def keep_template(reason: str) -> ScriptUnavailable:
        if lesson["script"] is None or lesson["script_source"] == "template":
            lessons.update_lesson(conn, lesson_id, script=template, script_source="template")
            lessons.set_item_captions(conn, lesson_id, {s["idx"]: s["caption"] for s in template["segments"]},
                                      only_empty=True)
        return ScriptUnavailable(reason)

    try:
        data, used = llm_json.complete_json(
            build_prompt(lesson, items, label, desc), schema=lessons.SCRIPT_SCHEMA, system=SYSTEM[lg],
            provider=provider, temperature=0.5, max_tokens=300 + 160 * len(items))
    except llm_json.LLMUnavailable as e:
        log.warning("Guion sin LLM (queda la plantilla): %s", e)
        raise keep_template(f"Sin LLM disponible: {e}") from e
    allowed_years = {int(it["work_year"]) for it in items if it.get("work_year")}
    if not _facts_ok(data, allowed_years):
        log.warning("El LLM mencionó años que no están en la DB; se descarta su guion")
        raise keep_template("El LLM mencionó datos que no están en la base de datos")
    final = _normalize(data, template, len(items))
    lessons.update_lesson(conn, lesson_id, script=final, script_source=f"llm:{used}")
    lessons.set_item_captions(conn, lesson_id, {s["idx"]: s["caption"] for s in final["segments"]})
    return lessons.get_lesson(conn, lesson_id)
