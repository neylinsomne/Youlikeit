"""Tablas del dominio supercut (registradas en core.db._DOMAIN_SCHEMA_ENSURERS).

lessons ─┬─ lesson_items   (moment_id, in/out, caption): la RECETA del Short
         ├─ lesson_issues  (revisión: problema en [start_s, end_s])
         └─ publications   (tiktok | youtube: estado, id externo, url)

Máquina de estados de `lessons.status`:

    draft → rendering → rendered → approved → published
                            └────→ rejected
    editar una lección rendered | approved | rejected  → draft
    render fallido                                      → draft

Las fechas se guardan como texto ISO-8601 UTC (`2026-11-04T05:12:00Z`), el
formato del contrato de la API, para no convertir en cada lectura.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, UTC

STATUSES = ("draft", "rendering", "rendered", "approved", "rejected", "published")
ISSUE_TYPES = ("voice", "caption", "timing", "image", "rights", "other")
PLATFORMS = ("tiktok", "youtube")
PUBLICATION_STATUSES = ("pending", "sent", "published", "failed")

SCHEMA_SUPERCUT = """
CREATE TABLE IF NOT EXISTS lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    spec TEXT NOT NULL,                      -- dimension:valor (p. ej. emotion:fear)
    format TEXT NOT NULL DEFAULT 'essay',
    lang TEXT NOT NULL DEFAULT 'es',
    status TEXT NOT NULL DEFAULT 'draft',    -- draft|rendering|rendered|approved|rejected|published
    script_json TEXT,                        -- {hook, outro, segments[{idx, narration, caption}]}
    script_source TEXT,                      -- llm:<proveedor> | template | manual
    output_path TEXT,
    duration_s REAL,
    reject_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lessons_status ON lessons(status, updated_at);

CREATE TABLE IF NOT EXISTS lesson_items (
    lesson_id INTEGER NOT NULL REFERENCES lessons(id),
    idx INTEGER NOT NULL,
    moment_id INTEGER NOT NULL,
    in_ms INTEGER NOT NULL,
    out_ms INTEGER NOT NULL,
    caption TEXT,
    PRIMARY KEY (lesson_id, idx)
);

CREATE TABLE IF NOT EXISTS lesson_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lesson_id INTEGER NOT NULL REFERENCES lessons(id),
    issue_type TEXT NOT NULL DEFAULT 'other',
    start_s REAL NOT NULL DEFAULT 0,
    end_s REAL NOT NULL DEFAULT 0,
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lesson_issues_lesson ON lesson_issues(lesson_id);

CREATE TABLE IF NOT EXISTS publications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lesson_id INTEGER NOT NULL REFERENCES lessons(id),
    platform TEXT NOT NULL,                  -- tiktok | youtube
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | sent | published | failed
    external_id TEXT,                        -- publish_id (TikTok) o video_id (YouTube)
    url TEXT,
    detail TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_publications_lesson ON publications(lesson_id, created_at);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Crea las tablas del dominio supercut. Idempotente."""
    conn.executescript(SCHEMA_SUPERCUT)
    conn.commit()


def now_iso() -> str:
    """Fecha actual ISO-8601 UTC con 'Z' (formato del contrato)."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
