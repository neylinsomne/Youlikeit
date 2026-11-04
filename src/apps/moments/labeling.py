"""Etiquetado de momentos con vocabulario controlado.

Solo se etiqueta el top-K por importancia de señales (+ todo lo anclado a una
cita célebre): el LLM es la parte cara, las señales baratas filtran primero.
Lotes de N momentos por llamada (menos requests → cabe en los límites gratis
de Groq/Gemini). La salida se valida contra los ids del vocabulario; lo que
no valida se descarta (llm_json.complete_json pasa al siguiente proveedor).

Sin LLM disponible quedan las etiquetas débiles de la detección (léxicas y de
posición, confianza ≤ 0.6) y el reporte lo dice explícitamente.
"""
from __future__ import annotations

import json
import logging
import sqlite3

from apps.moments import schema, vocab
from apps.moments.features import load_weights
from integrations.ai import llm_json

log = logging.getLogger(__name__)

SYSTEM = (
    "Eres analista de cine y narrativa. Clasificas momentos de películas y series usando SOLO los ids "
    "del catálogo. Basa cada etiqueta en el diálogo y el contexto de trama dados; si un tropo no es claro, "
    "no lo pongas. 'importance' = qué tan memorable/central es el momento para la obra (0-1). "
    "'confidence' = qué tan seguro estás de las etiquetas (0-1). 'summary_es' = una frase en español "
    "neutro describiendo qué pasa (sin spoilers innecesarios). Responde SOLO JSON."
)


def build_schema() -> dict:
    enum = {d: vocab.ids(d) for d in ("trope", "beat", "emotion", "role", "theme")}
    item = {
        "type": "object",
        "required": ["id", "tropes", "beat", "emotion", "summary_es", "importance", "confidence"],
        "properties": {
            "id": {"type": "integer"},
            "tropes": {"type": "array", "items": {"type": "string", "enum": enum["trope"]}},
            "beat": {"type": "string", "enum": enum["beat"]},
            "emotion": {"type": "string", "enum": enum["emotion"]},
            "roles": {"type": "array", "items": {"type": "string", "enum": enum["role"]}},
            "themes": {"type": "array", "items": {"type": "string", "enum": enum["theme"]}},
            "summary_es": {"type": "string"},
            "importance": {"type": "number"},
            "confidence": {"type": "number"},
        },
    }
    return {"type": "object", "required": ["items"],
            "properties": {"items": {"type": "array", "items": item}}}


def sanitize_items(data):
    """Descarta valores fuera del vocabulario POR ÍTEM en vez de rechazar el lote.

    Visto en producción: el modelo puso un tropo ('standoff') en `beat`, y el
    lote entero (6 momentos) se perdía y el etiquetado se detenía.
    """
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return data
    allowed = {d: set(vocab.ids(d)) for d in ("trope", "beat", "emotion", "role", "theme")}
    for it in data["items"]:
        if not isinstance(it, dict):
            continue
        for key, dim in (("tropes", "trope"), ("roles", "role"), ("themes", "theme")):
            if isinstance(it.get(key), list):
                it[key] = [v for v in it[key] if v in allowed[dim]]
        if it.get("beat") not in allowed["beat"]:
            it["beat"] = "none"
        if it.get("emotion") not in allowed["emotion"]:
            it.pop("emotion", None)
    data["items"] = [it for it in data["items"] if isinstance(it, dict) and "emotion" in it]
    return data


def _catalog() -> str:
    v = vocab.load_vocab()
    tropes = "\n".join(f"- {t['id']}: {t['desc_es']}" for t in v["trope"])
    other = "\n".join(f"{d}: {', '.join(vocab.ids(d))}" for d in ("beat", "emotion", "role", "theme"))
    return f"TROPOS:\n{tropes}\n\n{other}"


def _fmt_time(ms: int) -> str:
    s = ms // 1000
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def build_prompt(work_title: str, year: int | None, moments: list[dict]) -> str:
    parts = [_catalog(), "", f"OBRA: {work_title} ({year or 's/a'})", "MOMENTOS:"]
    for m in moments:
        anchors = m.get("anchors") or {}
        lines = [f"### id={m['id']} | posición {round((m.get('position') or 0) * 100)}% | "
                 f"{_fmt_time(m['start_ms'])}–{_fmt_time(m['end_ms'])}"]
        if anchors.get("plot"):
            lines.append(f"Trama cercana: {anchors['plot']}")
        if anchors.get("quote"):
            lines.append(f"Cita célebre (Wikiquote): \"{anchors['quote']}\"")
        lines.append(f"Diálogo: \"{(m.get('text') or '(sin diálogo: pico de sonido/acción)')[:600]}\"")
        if (m.get("features") or {}).get("cue_tropes"):
            lines.append(f"Pistas léxicas (débiles): {', '.join(m['features']['cue_tropes'])}")
        parts.append("\n".join(lines))
    parts.append('\nDevuelve {"items": [...]} con un objeto por momento, mismo id.')
    return "\n\n".join(parts)


def _clamp(x, lo=0.0, hi=1.0) -> float:
    try:
        return max(lo, min(hi, float(x)))
    except (TypeError, ValueError):
        return lo


def apply_labels(conn: sqlite3.Connection, items: list[dict], provider: str,
                 signal_scores: dict[int, float]) -> int:
    """Guarda etiquetas del LLM y recalcula la importancia final (mezcla señales + LLM)."""
    _, blend = load_weights()
    src = f"llm:{provider}"
    n = 0
    for it in items:
        mid = int(it["id"])
        if mid not in signal_scores:
            continue                                       # id inventado por el modelo
        conf = _clamp(it.get("confidence", 0.5))
        for t in dict.fromkeys(it.get("tropes") or []):
            schema.add_label(conn, mid, "trope", t, conf, src, commit=False)
        for r in dict.fromkeys(it.get("roles") or []):
            schema.add_label(conn, mid, "role", r, conf * 0.9, src, commit=False)
        for th in dict.fromkeys(it.get("themes") or []):
            schema.add_label(conn, mid, "theme", th, conf * 0.9, src, commit=False)
        if it.get("beat") and it["beat"] != "none":
            schema.add_label(conn, mid, "beat", it["beat"], conf * 0.9, src, commit=False)
        if it.get("emotion"):
            schema.add_label(conn, mid, "emotion", it["emotion"], conf, src, commit=False)
        final = round((1 - blend) * signal_scores[mid] + blend * _clamp(it.get("importance", 0)), 4)
        conn.execute("UPDATE moments SET importance = ?, summary_es = ?, status = 'labeled', labeled_by = ? "
                     "WHERE id = ?", (final, (it.get("summary_es") or "")[:400], src, mid))
        n += 1
    conn.commit()
    return n


def select_for_labeling(conn: sqlite3.Connection, asset_id: int, top_k: int) -> list[dict]:
    rows = conn.execute(
        """SELECT id, start_ms, end_ms, text, position, signal_score, features_json, anchors_json
           FROM moments WHERE asset_id = ? AND status = 'candidate'
           ORDER BY (anchors_json LIKE '%"quote"%') DESC, signal_score DESC LIMIT ?""",
        (asset_id, top_k)).fetchall()
    return [{"id": r[0], "start_ms": r[1], "end_ms": r[2], "text": r[3], "position": r[4],
             "signal_score": r[5], "features": json.loads(r[6] or "{}"), "anchors": json.loads(r[7] or "{}")}
            for r in rows]


def label_moments(conn: sqlite3.Connection, asset_id: int, *, work_title: str, year: int | None,
                  top_k: int = 40, batch_size: int = 6, provider: str | None = None) -> dict:
    todo = select_for_labeling(conn, asset_id, top_k)
    report = {"asset_id": asset_id, "selected": len(todo), "labeled": 0, "providers": {}, "errors": []}
    sch = build_schema()
    for k in range(0, len(todo), batch_size):
        batch = todo[k:k + batch_size]
        try:
            data, used = llm_json.complete_json(build_prompt(work_title, year, batch), schema=sch,
                                                system=SYSTEM, provider=provider,
                                                max_tokens=350 * len(batch), temperature=0.2,
                                                sanitize=sanitize_items)
        except llm_json.LLMUnavailable as e:
            report["errors"].append(str(e)[:300])
            if "no disponible" in str(e) and "esquema" not in str(e):
                log.warning("Sin LLM disponible: quedan solo etiquetas léxicas/posición (%s)", e)
                break                          # ningún proveedor: no tiene sentido seguir
            log.warning("Lote %d descartado (%s); sigo con el siguiente", k // batch_size, e)
            continue
        n = apply_labels(conn, data["items"], used, {m["id"]: m["signal_score"] for m in batch})
        report["labeled"] += n
        report["providers"][used] = report["providers"].get(used, 0) + n
    return report
