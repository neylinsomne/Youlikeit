"""Planificador: de `find_moments` a la receta (EDL) de una lección.

    spec "emotion:fear"
      → find_moments(min_works=2, max_per_work=1)   una escena por obra (MMR)
      → recorte para que la suma quepa en max_duration_s − tarjeta final (4 s)
      → orden por año de la obra (de la más antigua a la más nueva)
      → lessons + lesson_items (draft) con guion de plantilla (render posible sin IA)

Recorte justo ("water-filling"): los tramos cortos entran completos y lo que
sobra del presupuesto se reparte en partes iguales entre los largos. Se
conserva el INICIO del momento (ahí arranca el diálogo que lo ancló).
"""
from __future__ import annotations

import sqlite3

from apps.moments import vocab
from apps.moments.retrieval import find_moments
from apps.supercut import lessons, script

END_CARD_MS = 4_000
MIN_CLIP_MS = 2_500
MIN_WORKS = 2


class PlanError(RuntimeError):
    """No hay material suficiente (menos de 2 obras) para armar la lección."""


def allocate(durations: list[int], budget_ms: int) -> list[int]:
    """Reparte budget_ms entre los tramos: cortos completos, el resto en partes iguales."""
    alloc = [0] * len(durations)
    remaining, left = max(0, int(budget_ms)), len(durations)
    for i in sorted(range(len(durations)), key=lambda k: durations[k]):
        share = remaining // left
        alloc[i] = max(0, min(int(durations[i]), share))
        remaining -= alloc[i]
        left -= 1
    return alloc


def build_plan(conn: sqlite3.Connection, spec: str, *, max_works: int = 5, max_duration_s: float = 58,
               min_confidence: float = 0.5) -> dict:
    """EDL sin escribir en la DB: {dimension, value, items[{moment_id, in_ms, out_ms, work_*}], ...}."""
    dimension, value = vocab.parse_spec(spec)                  # ValueError → 422
    budget = int(max_duration_s * 1000) - END_CARD_MS
    if budget < MIN_WORKS * MIN_CLIP_MS:
        raise ValueError(f"max_duration_s={max_duration_s} no deja espacio para {MIN_WORKS} tramos")
    res = find_moments(conn, dimension, value, limit=max(MIN_WORKS, int(max_works)), min_works=MIN_WORKS,
                       max_per_work=1, min_confidence=min_confidence)
    if res["distinct_works"] < MIN_WORKS:
        raise PlanError(f"Solo {res['distinct_works']} obra(s) con '{spec}' (mínimo {MIN_WORKS}). "
                        "Indexa y etiqueta más obras o baja la confianza mínima.")
    picked = list(res["items"])
    # Demasiados tramos para el presupuesto: fuera los de menor puntaje.
    while len(picked) > MIN_WORKS and len(picked) * MIN_CLIP_MS > budget:
        picked.remove(min(picked, key=lambda r: r["score"]))
    alloc = allocate([r["end_ms"] - r["start_ms"] for r in picked], budget)
    items = [{"moment_id": r["id"], "in_ms": int(r["start_ms"]), "out_ms": int(r["start_ms"]) + a,
              "work_id": r["work_id"], "work_title": r["title"], "work_year": r["year"], "score": r["score"],
              "text": r.get("text"), "summary_es": r.get("summary_es")}
             for r, a in zip(picked, alloc, strict=True) if a > 0]
    items.sort(key=lambda it: (it["work_year"] is None, it["work_year"] or 0, -it["score"]))
    return {"dimension": dimension, "value": value, "spec": f"{dimension}:{value}", "items": items,
            "total_ms": sum(it["out_ms"] - it["in_ms"] for it in items) + END_CARD_MS,
            "candidates": res["candidates"], "distinct_works": len({it["work_id"] for it in items})}


def label_for(dimension: str, value: str, lang: str = "es") -> str:
    e = vocab.entry(dimension, value) or {}
    return e.get(lang) or e.get("es") or e.get("en") or value.replace("_", " ")


def default_title(label: str, items: list[dict], lang: str = "es") -> str:
    years = sorted(y for y in (it.get("work_year") for it in items) if y)
    span = f", {years[0]}–{years[-1]}" if len(years) >= 2 and years[0] != years[-1] else ""
    if lang == "es":
        return f"{label}: {len(items)} películas{span}"
    return f"{label} across {len(items)} films{span}"


def plan_lesson(conn: sqlite3.Connection, spec: str, *, title: str | None = None, max_works: int = 5,
                max_duration_s: float = 58, lang: str = "es", min_confidence: float = 0.5) -> dict:
    """Arma y guarda una lección draft. Devuelve el Lesson del contrato."""
    plan = build_plan(conn, spec, max_works=max_works, max_duration_s=max_duration_s,
                      min_confidence=min_confidence)
    label = label_for(plan["dimension"], plan["value"], lang)
    tpl = script.template_script(plan["dimension"], plan["value"], plan["items"], lang=lang)
    captions = {s["idx"]: s["caption"] for s in tpl["segments"]}
    items = [{**it, "caption": captions.get(i)} for i, it in enumerate(plan["items"])]
    lesson_id = lessons.create_lesson(
        conn, title=(title or "").strip() or default_title(label, items, lang), spec=plan["spec"],
        items=items, lang=lang, script=tpl, script_source="template")
    return lessons.get_lesson(conn, lesson_id)
