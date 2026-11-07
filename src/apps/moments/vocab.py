"""Vocabulario controlado: tropos, beats, emociones, roles y temas.

Fuente de verdad: data/vocab/*.json (versionado con el código, NO bajo
DATA_DIR) + `thematic_classifier.DEEP_THEMES` para los temas. Todo lo que
devuelva un LLM se valida contra estos ids.
"""
from __future__ import annotations

import functools
import json
import sqlite3
from pathlib import Path

from apps.moments.text import normalize

VOCAB_DIR = Path(__file__).resolve().parents[3] / "data" / "vocab"
DIMENSIONS = ("trope", "beat", "emotion", "role", "theme")


@functools.lru_cache(maxsize=1)
def load_vocab() -> dict[str, list[dict]]:
    tropes = json.loads((VOCAB_DIR / "tropes.json").read_text(encoding="utf-8"))["items"]
    tax = json.loads((VOCAB_DIR / "taxonomy.json").read_text(encoding="utf-8"))
    from apps.content.thematic_classifier import DEEP_THEMES
    themes = [{"id": k, "en": k.replace("_", " "), "es": k.replace("_", " "), **v}
              for k, v in DEEP_THEMES.items()]
    return {"trope": tropes, "beat": tax["beat"], "emotion": tax["emotion"],
            "role": tax["role"], "theme": themes}


def ids(dimension: str) -> list[str]:
    return [e["id"] for e in load_vocab()[dimension]]


def entry(dimension: str, value: str) -> dict | None:
    return next((e for e in load_vocab()[dimension] if e["id"] == value), None)


def parse_spec(spec: str) -> tuple[str, str]:
    """'trope:mentor_betrayal' → ('trope', 'mentor_betrayal'), validado."""
    dim, _, value = spec.partition(":")
    if dim not in DIMENSIONS or not value:
        raise ValueError(f"Usa dimension:valor con dimension en {DIMENSIONS} (recibido {spec!r})")
    if value not in ids(dim):
        raise ValueError(f"{value!r} no existe en {dim}. Opciones: {', '.join(ids(dim)[:12])}…")
    return dim, value


@functools.lru_cache(maxsize=1)
def _cue_index() -> list[tuple[str, str]]:
    out = []
    for t in load_vocab()["trope"]:
        for cue in t.get("cues_en", []) + t.get("cues_es", []):
            n = normalize(cue)
            if n:
                out.append((t["id"], n))
    return out


def trope_cue_hits(text: str) -> dict[str, int]:
    """Cuántas frases clave de cada tropo aparecen en el texto (pista débil)."""
    norm = f" {normalize(text)} "
    hits: dict[str, int] = {}
    for trope_id, cue in _cue_index():
        if f" {cue} " in norm:
            hits[trope_id] = hits.get(trope_id, 0) + 1
    return hits


def beat_prior(position: float) -> dict[str, float]:
    """Afinidad 0-1 de cada beat con la posición narrativa (1 dentro del rango)."""
    out = {}
    for b in load_vocab()["beat"]:
        if b["id"] == "none":
            continue
        lo, hi = b["pos"]
        if lo <= position <= hi:
            out[b["id"]] = 1.0
        else:
            dist = min(abs(position - lo), abs(position - hi))
            out[b["id"]] = max(0.0, 1.0 - dist / 0.15)
    return out


def sync_vocab_table(conn: sqlite3.Connection) -> int:
    """Copia el vocabulario a la tabla `vocab` (para joins y dashboards)."""
    rows = []
    for dim, entries in load_vocab().items():
        for e in entries:
            rows.append((dim, e["id"], e.get("es") or e["id"], e.get("en") or e["id"],
                         e.get("desc_es"), e.get("desc_en")))
    conn.executemany(
        """INSERT INTO vocab (dimension, value, label_es, label_en, desc_es, desc_en)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(dimension, value) DO UPDATE SET label_es = excluded.label_es,
             label_en = excluded.label_en, desc_es = excluded.desc_es, desc_en = excluded.desc_en""",
        rows)
    conn.commit()
    return len(rows)
