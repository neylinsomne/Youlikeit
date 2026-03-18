"""SQLite database for storing movies, quotes, and timestamps."""

import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS movies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tmdb_id INTEGER UNIQUE,
    title TEXT NOT NULL,
    original_title TEXT,
    year INTEGER,
    genre TEXT,
    popularity REAL DEFAULT 0,
    poster_path TEXT,
    overview TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS quotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    movie_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    character_name TEXT,
    start_ms INTEGER,
    end_ms INTEGER,
    source TEXT,  -- 'wikiquote', 'imsdb', 'opensubtitles', 'manual'
    confidence REAL DEFAULT 0,  -- match confidence from rapidfuzz (0-100)
    used_count INTEGER DEFAULT 0,
    -- Classification fields (populated by ex10)
    category TEXT,          -- villain, romance, motivational, comedy, action, dramatic, horror
    emotion TEXT,           -- anger, joy, sadness, fear, surprise, disgust, neutral
    viral_score INTEGER,    -- 1-10 estimated viral potential
    edit_style TEXT,         -- zoom, slowmo, rapid_cut, freeze_frame, split_screen
    context_before_ms INTEGER,  -- suggested start including context (scene breathing room)
    context_after_ms INTEGER,   -- suggested end including context
    scene_type TEXT,         -- dialogue, monologue, action, reaction, one_liner
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (movie_id) REFERENCES movies(id)
);

CREATE TABLE IF NOT EXISTS subtitles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    movie_id INTEGER NOT NULL,
    language TEXT DEFAULT 'en',
    srt_path TEXT,
    source TEXT,  -- 'opensubtitles', 'subdl', 'manual'
    downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (movie_id) REFERENCES movies(id)
);

CREATE TABLE IF NOT EXISTS shorts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    theme_query TEXT,
    quote_ids TEXT,  -- JSON array of quote IDs used
    template TEXT,
    output_file TEXT,
    status TEXT DEFAULT 'pending',  -- pending, rendered, uploaded
    youtube_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS youtube_existing (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    movie_id INTEGER,
    video_id TEXT UNIQUE,
    title TEXT,
    views INTEGER DEFAULT 0,
    scene_description TEXT,
    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (movie_id) REFERENCES movies(id)
);

CREATE TABLE IF NOT EXISTS url_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    movie_title TEXT NOT NULL,
    quote_snippet TEXT,
    youtube_url TEXT,
    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_quotes_movie ON quotes(movie_id);
CREATE INDEX IF NOT EXISTS idx_quotes_text ON quotes(text);
CREATE INDEX IF NOT EXISTS idx_movies_tmdb ON movies(tmdb_id);
CREATE INDEX IF NOT EXISTS idx_url_cache_movie ON url_cache(movie_title);
"""


def get_db(data_dir: Path) -> sqlite3.Connection:
    """Get or create the SQLite database connection."""
    db_path = data_dir / "shorts_pipeline.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def insert_movie(conn: sqlite3.Connection, **kwargs) -> int:
    """Insert a movie, skip if tmdb_id already exists. Returns movie id."""
    cur = conn.execute(
        "SELECT id FROM movies WHERE tmdb_id = ?", (kwargs.get("tmdb_id"),)
    )
    row = cur.fetchone()
    if row:
        return row["id"]

    cur = conn.execute(
        """INSERT INTO movies (tmdb_id, title, original_title, year, genre, popularity, poster_path, overview)
           VALUES (:tmdb_id, :title, :original_title, :year, :genre, :popularity, :poster_path, :overview)""",
        kwargs,
    )
    conn.commit()
    return cur.lastrowid


def insert_quote(conn: sqlite3.Connection, **kwargs) -> int:
    """Insert a quote. Returns quote id."""
    cur = conn.execute(
        """INSERT INTO quotes (movie_id, text, character_name, start_ms, end_ms, source, confidence)
           VALUES (:movie_id, :text, :character_name, :start_ms, :end_ms, :source, :confidence)""",
        kwargs,
    )
    conn.commit()
    return cur.lastrowid


def insert_subtitle(conn: sqlite3.Connection, **kwargs) -> int:
    """Insert a subtitle record. Returns id."""
    cur = conn.execute(
        """INSERT INTO subtitles (movie_id, language, srt_path, source)
           VALUES (:movie_id, :language, :srt_path, :source)""",
        kwargs,
    )
    conn.commit()
    return cur.lastrowid


def get_movies_without_subtitles(conn: sqlite3.Connection) -> list:
    """
    Get movies without subtitles, RANKED by download priority.

    Score = (num_quotes * 10) + popularity + genre_bonus
    Movies with more Wikiquote quotes get downloaded first,
    so we don't waste the 20 free daily downloads on movies
    that have no usable quotes.
    """
    cur = conn.execute(
        """SELECT m.*,
                  COUNT(q.id) as quote_count,
                  (COUNT(q.id) * 10 + m.popularity +
                   CASE WHEN m.genre LIKE '%28%'   THEN 20   -- Action
                        WHEN m.genre LIKE '%18%'   THEN 15   -- Drama
                        WHEN m.genre LIKE '%53%'   THEN 15   -- Thriller
                        WHEN m.genre LIKE '%80%'   THEN 10   -- Crime
                        WHEN m.genre LIKE '%878%'  THEN 10   -- Sci-Fi
                        ELSE 0
                   END
                  ) as download_priority
           FROM movies m
           LEFT JOIN subtitles s ON m.id = s.movie_id
           LEFT JOIN quotes q ON m.id = q.movie_id
           WHERE s.id IS NULL
           GROUP BY m.id
           ORDER BY download_priority DESC"""
    )
    return cur.fetchall()


def get_quotes_without_timestamps(conn: sqlite3.Connection) -> list:
    """Get quotes that don't have timestamps yet."""
    cur = conn.execute(
        """SELECT q.*, m.title as movie_title, m.tmdb_id
           FROM quotes q
           JOIN movies m ON q.movie_id = m.id
           WHERE q.start_ms IS NULL
           ORDER BY m.popularity DESC"""
    )
    return cur.fetchall()


def get_quotes_with_timestamps(conn: sqlite3.Connection, movie_id: int = None) -> list:
    """Get quotes that have timestamps assigned."""
    if movie_id:
        cur = conn.execute(
            """SELECT q.*, m.title as movie_title
               FROM quotes q JOIN movies m ON q.movie_id = m.id
               WHERE q.start_ms IS NOT NULL AND q.movie_id = ?
               ORDER BY q.confidence DESC""",
            (movie_id,),
        )
    else:
        cur = conn.execute(
            """SELECT q.*, m.title as movie_title
               FROM quotes q JOIN movies m ON q.movie_id = m.id
               WHERE q.start_ms IS NOT NULL
               ORDER BY q.confidence DESC"""
        )
    return cur.fetchall()
