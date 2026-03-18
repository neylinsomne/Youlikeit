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

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    short_id INTEGER NOT NULL,
    status TEXT DEFAULT 'pending',  -- pending, approved, rejected, needs_edit
    reviewer_notes TEXT,            -- qué hizo bien o mal
    rating INTEGER,                -- 1-5 estrellas
    -- Frame-level issues (JSON array of {frame_ms, issue_type, description})
    frame_issues TEXT,
    -- What the reviewer thinks should change
    suggested_category TEXT,
    suggested_emotion TEXT,
    suggested_edit_style TEXT,
    -- Metadata
    reviewed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (short_id) REFERENCES shorts(id)
);

CREATE TABLE IF NOT EXISTS review_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    short_id INTEGER NOT NULL,
    action TEXT NOT NULL,           -- created, submitted_review, approved, rejected, uploaded, reedited
    details TEXT,                   -- JSON with context
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (short_id) REFERENCES shorts(id)
);

CREATE TABLE IF NOT EXISTS url_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    movie_title TEXT NOT NULL,
    quote_snippet TEXT,
    youtube_url TEXT,
    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS analytics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    short_id INTEGER NOT NULL,
    platform TEXT NOT NULL,           -- youtube, tiktok
    platform_video_id TEXT,           -- YouTube video ID or TikTok video ID
    views INTEGER DEFAULT 0,
    likes INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    shares INTEGER DEFAULT 0,
    retention_avg REAL DEFAULT 0,     -- 0-100 avg % watched
    retention_3s REAL DEFAULT 0,      -- % viewers still at 3s (hook effectiveness)
    ctr REAL DEFAULT 0,               -- click-through rate from impressions
    impressions INTEGER DEFAULT 0,
    -- Derived metrics
    engagement_rate REAL DEFAULT 0,   -- (likes+comments+shares) / views
    viral_ratio REAL DEFAULT 0,       -- shares / views (how shareable)
    -- Context
    hashtags_used TEXT,               -- JSON array of hashtags actually used
    song_used TEXT,                   -- song selected on platform
    upload_time TEXT,                 -- when it was posted
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (short_id) REFERENCES shorts(id)
);

CREATE TABLE IF NOT EXISTS competitor_videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    platform_video_id TEXT UNIQUE,
    channel_name TEXT,
    title TEXT,
    views INTEGER DEFAULT 0,
    likes INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    duration_s REAL DEFAULT 0,
    hashtags TEXT,                     -- JSON array
    song TEXT,
    -- Analysis from VLM or heuristic
    detected_theme TEXT,
    detected_style TEXT,              -- edit style: rapid_cut, slowmo, etc
    detected_hook_type TEXT,          -- text, action, question, shock
    text_on_screen INTEGER DEFAULT 0, -- 1 if has text overlay
    face_present INTEGER DEFAULT 0,   -- 1 if face is visible
    -- Scoring
    engagement_rate REAL DEFAULT 0,
    estimated_quality INTEGER DEFAULT 0,  -- 1-10
    -- Learning
    what_works TEXT,                   -- JSON: insights extracted
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS learning_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle INTEGER DEFAULT 1,          -- learning cycle number
    metric TEXT NOT NULL,              -- what was measured
    old_value REAL,                   -- previous value
    new_value REAL,                   -- new value
    adjustment TEXT,                  -- what was changed
    reason TEXT,                      -- why
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    role TEXT DEFAULT 'reviewer',     -- admin, reviewer, agent
    display_name TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    agent_name TEXT,                  -- 'claude:ab_tester', 'claude:comment_analyst', 'system'
    action TEXT NOT NULL,             -- create, update, delete, approve, reject, test_start, test_end
    entity_type TEXT NOT NULL,        -- short, quote, review, ab_test, goal, knowledge
    entity_id INTEGER,
    old_value TEXT,                   -- JSON snapshot before change
    new_value TEXT,                   -- JSON snapshot after change
    reason TEXT,                      -- why this action was taken
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS ab_tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    hypothesis TEXT,                  -- "hashtags de emocion > hashtags de genero"
    status TEXT DEFAULT 'running',    -- running, completed, cancelled
    variant_a TEXT NOT NULL,          -- JSON: config for variant A
    variant_b TEXT NOT NULL,          -- JSON: config for variant B
    metric TEXT DEFAULT 'engagement_rate',  -- what we measure
    -- Results
    variant_a_results TEXT,           -- JSON: {n, mean, std, values}
    variant_b_results TEXT,
    winner TEXT,                      -- 'a', 'b', 'inconclusive'
    p_value REAL,                     -- statistical significance
    effect_size REAL,                 -- Cohen's d
    confidence_interval TEXT,         -- JSON: [lower, upper]
    -- Config
    min_samples INTEGER DEFAULT 5,
    significance_level REAL DEFAULT 0.05,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP,
    created_by INTEGER,
    FOREIGN KEY (created_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    metric TEXT NOT NULL,             -- views_avg, engagement_rate, followers, uploads_count
    target_value REAL NOT NULL,
    current_value REAL DEFAULT 0,
    baseline_value REAL DEFAULT 0,    -- where we started
    deadline TEXT,                    -- ISO date
    status TEXT DEFAULT 'active',     -- active, achieved, missed, revised
    trend_slope REAL,                 -- from linear regression
    projected_date TEXT,              -- when trend says we'll hit target
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS knowledge_base (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,           -- insight, rule, pattern, mistake, success
    topic TEXT NOT NULL,              -- hashtags, timing, editing, audience, content
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    confidence REAL DEFAULT 0.5,      -- 0-1, how sure we are
    source TEXT,                      -- analytics, ab_test, review, competitor, manual
    source_id INTEGER,                -- reference to the source entity
    times_validated INTEGER DEFAULT 0,
    times_contradicted INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP
);

-- Seed default admin user
INSERT OR IGNORE INTO users (username, role, display_name) VALUES ('admin', 'admin', 'Admin');
INSERT OR IGNORE INTO users (username, role, display_name) VALUES ('claude:ab_tester', 'agent', 'Claude A/B Tester');
INSERT OR IGNORE INTO users (username, role, display_name) VALUES ('claude:analyst', 'agent', 'Claude Analyst');
INSERT OR IGNORE INTO users (username, role, display_name) VALUES ('claude:reviewer', 'agent', 'Claude Comment Reviewer');

CREATE INDEX IF NOT EXISTS idx_quotes_movie ON quotes(movie_id);
CREATE INDEX IF NOT EXISTS idx_quotes_text ON quotes(text);
CREATE INDEX IF NOT EXISTS idx_movies_tmdb ON movies(tmdb_id);
CREATE INDEX IF NOT EXISTS idx_url_cache_movie ON url_cache(movie_title);
CREATE INDEX IF NOT EXISTS idx_analytics_short ON analytics(short_id);
CREATE INDEX IF NOT EXISTS idx_analytics_platform ON analytics(platform);
CREATE INDEX IF NOT EXISTS idx_competitor_hashtags ON competitor_videos(hashtags);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_agent ON audit_log(agent_name);
CREATE INDEX IF NOT EXISTS idx_knowledge_topic ON knowledge_base(topic);
CREATE INDEX IF NOT EXISTS idx_knowledge_category ON knowledge_base(category);
CREATE INDEX IF NOT EXISTS idx_ab_tests_status ON ab_tests(status);
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
