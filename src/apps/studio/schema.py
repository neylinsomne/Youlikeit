"""Tabla de la cola de trabajos del estudio (registrada en core.db._DOMAIN_SCHEMA_ENSURERS)."""
from __future__ import annotations

import sqlite3

JOB_TYPES = ("index", "detect", "label", "render", "publish_tiktok", "publish_youtube")
JOB_STATUSES = ("queued", "running", "done", "error")

SCHEMA_STUDIO = """
CREATE TABLE IF NOT EXISTS studio_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,                      -- index | detect | label | render | publish_tiktok | publish_youtube
    status TEXT NOT NULL DEFAULT 'queued',   -- queued | running | done | error
    params_json TEXT NOT NULL DEFAULT '{}',
    progress_json TEXT,                      -- {stage, pct, detail}
    result_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_studio_jobs_status ON studio_jobs(status, id);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_STUDIO)
    conn.commit()
