"""Recuperación ENTRE obras: los mejores momentos de un tropo/tema/emoción.

Puntaje = importancia × confianza de la etiqueta. Selección MMR (Maximal
Marginal Relevance): cada paso elige el que más aporta restando su parecido
con lo ya elegido (misma obra = parecido 1; si no, coseno TF-IDF del texto).
Así el supercut junta obras distintas en vez de 5 clips de la misma película.
Solo entran assets con derechos usables (public_domain / open_license / owned).
"""
from __future__ import annotations

import sqlite3

from apps.media.models import USABLE_RIGHTS
from apps.moments.text import Tfidf, cosine_matrix


def find_moments(conn: sqlite3.Connection, dimension: str, value: str, *, limit: int = 6,
                 min_works: int = 3, max_per_work: int = 1, min_confidence: float = 0.5,
                 diversity: float = 0.35, usable_only: bool = True) -> dict:
    rights = tuple(sorted(USABLE_RIGHTS))
    sql = f"""
        SELECT m.id, m.asset_id, m.start_ms, m.end_ms, m.text, m.summary_es, m.importance, m.position,
               MAX(l.confidence) AS confidence, GROUP_CONCAT(DISTINCT l.source) AS sources,
               w.id AS work_id, w.title, w.year, a.rights, a.season, a.episode
        FROM moment_labels l
        JOIN moments m ON m.id = l.moment_id
        JOIN media_assets a ON a.id = m.asset_id
        JOIN works w ON w.id = a.work_id
        WHERE l.dimension = ? AND l.value = ? AND l.confidence >= ? AND m.status != 'rejected'
          {"AND a.rights IN (" + ",".join("?" * len(rights)) + ")" if usable_only else ""}
        GROUP BY m.id"""
    params = (dimension, value, min_confidence, *(rights if usable_only else ()))
    prev = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.row_factory = prev
    for r in rows:
        r["score"] = round((r["importance"] or 0) * r["confidence"], 4)

    picked = mmr(rows, limit=limit, max_per_work=max_per_work, diversity=diversity)
    works = {r["work_id"] for r in picked}
    out = {"dimension": dimension, "value": value, "items": picked, "distinct_works": len(works),
           "candidates": len(rows)}
    if len(works) < min_works:
        out["warning"] = (f"Solo {len(works)} obra(s) con '{value}' (mínimo {min_works}). "
                          "Indexa y etiqueta más obras o baja --min-confidence.")
    return out


def mmr(rows: list[dict], *, limit: int, max_per_work: int, diversity: float) -> list[dict]:
    if not rows:
        return []
    tf = Tfidf([r.get("summary_es") or r.get("text") or "" for r in rows])
    sim = cosine_matrix(tf.matrix, tf.matrix)
    chosen: list[int] = []
    per_work: dict[int, int] = {}
    while len(chosen) < limit:
        best, best_val = None, float("-inf")
        for i, r in enumerate(rows):
            if i in chosen or per_work.get(r["work_id"], 0) >= max_per_work:
                continue
            redund = max((1.0 if rows[c]["work_id"] == r["work_id"] else float(sim[i, c]) for c in chosen),
                         default=0.0)
            val = (1 - diversity) * r["score"] - diversity * redund
            if val > best_val:
                best, best_val = i, val
        if best is None:
            break
        chosen.append(best)
        per_work[rows[best]["work_id"]] = per_work.get(rows[best]["work_id"], 0) + 1
    return [rows[i] for i in chosen]
