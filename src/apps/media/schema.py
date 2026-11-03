"""Tablas del dominio media + acceso a datos.

works ─┬─ media_assets ─┬─ shots
       │                ├─ transcript_segments
       │                └─ transcript_words

`works` unifica películas y series (antes `movies` por tmdb_id y
`scene_moments` por series_slug vivían en sistemas de claves separados).
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable

from apps.media.models import MediaCandidate

SCHEMA_MEDIA = """
CREATE TABLE IF NOT EXISTS works (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL DEFAULT 'movie',      -- movie | series
    title TEXT NOT NULL,
    year INTEGER,
    tmdb_id INTEGER,
    imdb_id TEXT,
    lang TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(kind, title, year)
);

CREATE TABLE IF NOT EXISTS media_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_id INTEGER NOT NULL REFERENCES works(id),
    season INTEGER,
    episode INTEGER,
    provider TEXT NOT NULL,                  -- archive_org | local | jellyfin
    external_id TEXT NOT NULL,               -- IA identifier / ruta / item id
    master_uri TEXT NOT NULL,
    proxy_uri TEXT,
    proxy_path TEXT,                         -- copia local del proxy (análisis)
    audio_path TEXT,                         -- wav 16 kHz mono para ASR
    duration_ms INTEGER,
    width INTEGER,
    height INTEGER,
    fps REAL,
    size_bytes INTEGER,
    rights TEXT NOT NULL DEFAULT 'unknown',
    license_url TEXT,
    accept_ranges INTEGER,                   -- 1 si el master soporta HTTP Range
    extra_json TEXT,
    transcribed_at TIMESTAMP,
    shots_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(provider, external_id, master_uri)
);
CREATE INDEX IF NOT EXISTS idx_media_assets_work ON media_assets(work_id);

CREATE TABLE IF NOT EXISTS shots (
    asset_id INTEGER NOT NULL REFERENCES media_assets(id),
    idx INTEGER NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    detector TEXT,
    PRIMARY KEY (asset_id, idx)
);

CREATE TABLE IF NOT EXISTS transcript_segments (
    asset_id INTEGER NOT NULL REFERENCES media_assets(id),
    idx INTEGER NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    text TEXT NOT NULL,
    lang TEXT,
    avg_logprob REAL,
    no_speech_prob REAL,
    PRIMARY KEY (asset_id, idx)
);

CREATE TABLE IF NOT EXISTS transcript_words (
    asset_id INTEGER NOT NULL REFERENCES media_assets(id),
    segment_idx INTEGER NOT NULL,
    idx INTEGER NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    word TEXT NOT NULL,
    prob REAL,
    PRIMARY KEY (asset_id, segment_idx, idx)
);
CREATE INDEX IF NOT EXISTS idx_transcript_words_time ON transcript_words(asset_id, start_ms);

-- Observabilidad del ETL: cuánto tarda cada etapa por asset (para optimizar con datos).
CREATE TABLE IF NOT EXISTS media_index_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL,
    step TEXT NOT NULL,                      -- probe | proxy | analyze | asr | ...
    status TEXT NOT NULL,                    -- ok | error | skipped
    seconds REAL,
    detail_json TEXT,
    finished_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_media_index_runs_asset ON media_index_runs(asset_id, finished_at);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Crea las tablas del dominio media. Idempotente."""
    conn.executescript(SCHEMA_MEDIA)
    conn.commit()


# ── works / assets ──────────────────────────────────────────────────


def upsert_work(conn: sqlite3.Connection, *, title: str, year: int | None,
                kind: str = "movie", tmdb_id: int | None = None,
                imdb_id: str | None = None, lang: str | None = None) -> int:
    # Búsqueda explícita: en SQLite los NULL no chocan en UNIQUE, así que una
    # obra sin año se duplicaría con ON CONFLICT.
    title = title.strip()
    row = conn.execute(
        "SELECT id FROM works WHERE kind = ? AND title = ? COLLATE NOCASE AND year IS ?",
        (kind, title, year),
    ).fetchone()
    if row:
        conn.execute(
            """UPDATE works SET tmdb_id = COALESCE(?, tmdb_id), imdb_id = COALESCE(?, imdb_id),
                                lang = COALESCE(?, lang) WHERE id = ?""",
            (tmdb_id, imdb_id, lang, row[0]),
        )
        return int(row[0])
    cur = conn.execute(
        "INSERT INTO works (kind, title, year, tmdb_id, imdb_id, lang) VALUES (?, ?, ?, ?, ?, ?)",
        (kind, title, year, tmdb_id, imdb_id, lang),
    )
    return int(cur.lastrowid)


def upsert_asset(conn: sqlite3.Connection, work_id: int, cand: MediaCandidate,
                 *, accept_ranges: bool | None = None) -> int:
    conn.execute(
        """INSERT INTO media_assets
             (work_id, season, episode, provider, external_id, master_uri, proxy_uri,
              duration_ms, width, height, size_bytes, rights, license_url,
              accept_ranges, extra_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(provider, external_id, master_uri) DO UPDATE SET
             proxy_uri = excluded.proxy_uri,
             duration_ms = COALESCE(NULLIF(excluded.duration_ms, 0), media_assets.duration_ms),
             width = COALESCE(NULLIF(excluded.width, 0), media_assets.width),
             height = COALESCE(NULLIF(excluded.height, 0), media_assets.height),
             size_bytes = COALESCE(NULLIF(excluded.size_bytes, 0), media_assets.size_bytes),
             rights = excluded.rights,
             license_url = excluded.license_url,
             accept_ranges = COALESCE(excluded.accept_ranges, media_assets.accept_ranges),
             extra_json = excluded.extra_json""",
        (work_id, cand.season, cand.episode, cand.provider, cand.external_id,
         cand.master_uri, cand.proxy_uri or None, cand.duration_ms or None,
         cand.width or None, cand.height or None, cand.size_bytes or None,
         cand.rights, cand.license_url or None,
         None if accept_ranges is None else int(accept_ranges),
         json.dumps(cand.extra, ensure_ascii=False) if cand.extra else None),
    )
    row = conn.execute(
        "SELECT id FROM media_assets WHERE provider = ? AND external_id = ? AND master_uri = ?",
        (cand.provider, cand.external_id, cand.master_uri),
    ).fetchone()
    conn.commit()
    return int(row[0])


def get_asset(conn: sqlite3.Connection, asset_id: int) -> sqlite3.Row | None:
    prev = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            """SELECT a.*, w.title AS work_title, w.year AS work_year, w.kind AS work_kind
               FROM media_assets a JOIN works w ON w.id = a.work_id WHERE a.id = ?""",
            (asset_id,),
        ).fetchone()
    finally:
        conn.row_factory = prev


def update_asset(conn: sqlite3.Connection, asset_id: int, **fields) -> None:
    allowed = {"proxy_path", "audio_path", "duration_ms", "width", "height", "fps",
               "size_bytes", "accept_ranges", "transcribed_at", "shots_at"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"Campos no permitidos: {sorted(bad)}")
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE media_assets SET {cols} WHERE id = ?", (*fields.values(), asset_id))
    conn.commit()


# ── shots / transcript ──────────────────────────────────────────────


def save_shots(conn: sqlite3.Connection, asset_id: int,
               shots: Iterable[tuple[int, int]], detector: str) -> int:
    rows = [(asset_id, i, int(s), int(e), detector) for i, (s, e) in enumerate(shots)]
    conn.execute("DELETE FROM shots WHERE asset_id = ?", (asset_id,))
    conn.executemany("INSERT INTO shots VALUES (?, ?, ?, ?, ?)", rows)
    conn.execute("UPDATE media_assets SET shots_at = CURRENT_TIMESTAMP WHERE id = ?", (asset_id,))
    conn.commit()
    return len(rows)


def save_transcript(conn: sqlite3.Connection, asset_id: int, segments: list[dict]) -> tuple[int, int]:
    """segments: [{start_ms, end_ms, text, lang, avg_logprob, no_speech_prob,
    words: [{start_ms, end_ms, word, prob}]}]"""
    conn.execute("DELETE FROM transcript_words WHERE asset_id = ?", (asset_id,))
    conn.execute("DELETE FROM transcript_segments WHERE asset_id = ?", (asset_id,))
    n_words = 0
    for i, seg in enumerate(segments):
        conn.execute(
            "INSERT INTO transcript_segments VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (asset_id, i, int(seg["start_ms"]), int(seg["end_ms"]), seg["text"].strip(),
             seg.get("lang"), seg.get("avg_logprob"), seg.get("no_speech_prob")),
        )
        words = seg.get("words") or []
        conn.executemany(
            "INSERT INTO transcript_words VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(asset_id, i, j, int(w["start_ms"]), int(w["end_ms"]), w["word"].strip(), w.get("prob"))
             for j, w in enumerate(words)],
        )
        n_words += len(words)
    conn.execute("UPDATE media_assets SET transcribed_at = CURRENT_TIMESTAMP WHERE id = ?", (asset_id,))
    conn.commit()
    return len(segments), n_words


def log_step(conn: sqlite3.Connection, asset_id: int, step: str, status: str,
             seconds: float | None = None, detail: dict | None = None) -> None:
    conn.execute(
        "INSERT INTO media_index_runs (asset_id, step, status, seconds, detail_json) VALUES (?, ?, ?, ?, ?)",
        (asset_id, step, status, None if seconds is None else round(seconds, 3),
         json.dumps(detail, ensure_ascii=False, default=str) if detail else None),
    )
    conn.commit()
