"""Tablas del dominio moments.

media_assets ─ moments ─┬─ moment_labels (dimension, value, confidence, source)
                        └─ features_json / anchors_json (señales interpretables)
works ─ work_texts (Wikiquote, trama de Wikipedia: caché de fuentes externas)
vocab (copia del vocabulario controlado para joins)
"""
from __future__ import annotations

import json
import sqlite3

SCHEMA_MOMENTS = """
CREATE TABLE IF NOT EXISTS vocab (
    dimension TEXT NOT NULL,
    value TEXT NOT NULL,
    label_es TEXT,
    label_en TEXT,
    desc_es TEXT,
    desc_en TEXT,
    PRIMARY KEY (dimension, value)
);

CREATE TABLE IF NOT EXISTS work_texts (
    work_id INTEGER NOT NULL,
    kind TEXT NOT NULL,                      -- wikiquote | plot
    lang TEXT NOT NULL DEFAULT 'en',
    source_url TEXT,
    items_json TEXT NOT NULL,                -- lista de citas / frases de trama
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (work_id, kind, lang)
);

CREATE TABLE IF NOT EXISTS moments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    shot_in INTEGER,
    shot_out INTEGER,
    text TEXT,
    position REAL,                           -- 0 inicio … 1 final de la obra
    importance REAL DEFAULT 0,               -- final (señales + LLM)
    signal_score REAL DEFAULT 0,             -- solo señales interpretables
    features_json TEXT,                      -- señales normalizadas + contribuciones
    anchors_json TEXT,                       -- cita / frase de trama que la respalda
    summary_es TEXT,
    status TEXT NOT NULL DEFAULT 'candidate',  -- candidate | labeled | rejected
    labeled_by TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(asset_id, start_ms, end_ms)
);
CREATE INDEX IF NOT EXISTS idx_moments_asset ON moments(asset_id, importance DESC);

CREATE TABLE IF NOT EXISTS moment_labels (
    moment_id INTEGER NOT NULL REFERENCES moments(id),
    dimension TEXT NOT NULL,                 -- trope | beat | emotion | role | theme
    value TEXT NOT NULL,
    confidence REAL NOT NULL,
    source TEXT NOT NULL,                    -- llm:<proveedor> | lexical | position | quote | manual
    PRIMARY KEY (moment_id, dimension, value, source)
);
CREATE INDEX IF NOT EXISTS idx_moment_labels_lookup ON moment_labels(dimension, value, confidence DESC);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_MOMENTS)
    conn.commit()


def save_candidates(conn: sqlite3.Connection, asset_id: int, moments: list[dict]) -> int:
    """Reemplaza los candidatos NO etiquetados del asset (los etiquetados se conservan)."""
    labeled = {(r[0], r[1]) for r in conn.execute(
        "SELECT start_ms, end_ms FROM moments WHERE asset_id = ? AND status != 'candidate'", (asset_id,))}
    conn.execute("DELETE FROM moment_labels WHERE moment_id IN "
                 "(SELECT id FROM moments WHERE asset_id = ? AND status = 'candidate')", (asset_id,))
    conn.execute("DELETE FROM moments WHERE asset_id = ? AND status = 'candidate'", (asset_id,))
    n = 0
    for m in moments:
        if (m["start_ms"], m["end_ms"]) in labeled:
            continue
        cur = conn.execute(
            """INSERT INTO moments (asset_id, start_ms, end_ms, shot_in, shot_out, text, position,
                                    importance, signal_score, features_json, anchors_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (asset_id, m["start_ms"], m["end_ms"], m.get("shot_in"), m.get("shot_out"), m.get("text"),
             m.get("position"), m.get("signal_score", 0), m.get("signal_score", 0),
             json.dumps(m.get("features") or {}, ensure_ascii=False),
             json.dumps(m.get("anchors") or {}, ensure_ascii=False)))
        m["id"] = cur.lastrowid
        for dim, value, conf, src in m.get("labels", []):
            add_label(conn, cur.lastrowid, dim, value, conf, src, commit=False)
        n += 1
    conn.commit()
    return n


def add_label(conn: sqlite3.Connection, moment_id: int, dimension: str, value: str,
              confidence: float, source: str, *, commit: bool = True) -> None:
    conn.execute(
        """INSERT INTO moment_labels (moment_id, dimension, value, confidence, source) VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(moment_id, dimension, value, source) DO UPDATE SET confidence = excluded.confidence""",
        (moment_id, dimension, value, round(float(confidence), 4), source))
    if commit:
        conn.commit()


def save_work_texts(conn: sqlite3.Connection, work_id: int, kind: str, items: list,
                    *, lang: str = "en", source_url: str | None = None) -> None:
    conn.execute(
        """INSERT INTO work_texts (work_id, kind, lang, source_url, items_json) VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(work_id, kind, lang) DO UPDATE SET items_json = excluded.items_json,
             source_url = excluded.source_url, fetched_at = CURRENT_TIMESTAMP""",
        (work_id, kind, lang, source_url, json.dumps(items, ensure_ascii=False)))
    conn.commit()


def get_work_texts(conn: sqlite3.Connection, work_id: int, kind: str, lang: str = "en",
                   *, empty_ttl_days: float = 7.0) -> list | None:
    """Ítems cacheados, o None si hay que (re)bajarlos.

    Un resultado VACÍO caduca a los `empty_ttl_days`: suele ser un fallo de
    búsqueda o de red, no la ausencia real de la página.
    """
    row = conn.execute(
        "SELECT items_json, julianday('now') - julianday(fetched_at) FROM work_texts "
        "WHERE work_id = ? AND kind = ? AND lang = ?", (work_id, kind, lang)).fetchone()
    if not row:
        return None
    items = json.loads(row[0])
    if not items and (row[1] is None or row[1] > empty_ttl_days):
        return None
    return items
