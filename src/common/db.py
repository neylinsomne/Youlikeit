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
    -- Metadata fields
    category TEXT,           -- action, dramatic, philosophical, villain, etc
    emotion TEXT,            -- dark, epic, tragic, hopeful
    hashtags TEXT,           -- comma-separated hashtags
    song_suggestion TEXT,    -- recommended song for platform selection
    narration_intro TEXT,    -- intro narration text
    narration_outro TEXT,    -- outro narration text
    narration_segments TEXT, -- JSON: [{text, emotion, duration_s}]
    voice TEXT DEFAULT 'andrew',  -- tts voice used
    series_name TEXT,        -- e.g. Berserk, One Piece
    arc_name TEXT,           -- e.g. Golden Age
    part_number INTEGER,     -- part X of the series
    description TEXT,        -- YouTube description
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
-- Phase 2: Retention curves (ex24)
CREATE TABLE IF NOT EXISTS retention_curves (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analytics_id INTEGER NOT NULL,
    second INTEGER NOT NULL,
    audience_retention REAL NOT NULL,
    quote_id INTEGER,
    category TEXT,
    edit_style TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (analytics_id) REFERENCES analytics(id),
    FOREIGN KEY (quote_id) REFERENCES quotes(id)
);

-- Phase 2: Retention events (ex24)
CREATE TABLE IF NOT EXISTS retention_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analytics_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,          -- cliff, plateau, recovery, hook_pass
    second_start INTEGER NOT NULL,
    second_end INTEGER,
    magnitude REAL,
    content_at_event TEXT,            -- JSON: {quote_id, category, emotion, scene_type}
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (analytics_id) REFERENCES analytics(id)
);

-- Phase 2: Audience demographics (ex26)
CREATE TABLE IF NOT EXISTS audience_demographics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date TEXT NOT NULL,
    dimension TEXT NOT NULL,           -- age_group, gender, country
    dimension_value TEXT NOT NULL,     -- "25-34", "female", "CO"
    viewer_percentage REAL NOT NULL,
    watch_time_minutes REAL DEFAULT 0,
    views INTEGER DEFAULT 0,
    avg_engagement REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Phase 2: Audience segments from DBSCAN (ex26)
CREATE TABLE IF NOT EXISTS audience_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    segment_name TEXT NOT NULL,
    core_points TEXT NOT NULL,         -- JSON: list of core point indices
    size INTEGER DEFAULT 0,
    noise_count INTEGER DEFAULT 0,     -- outliers detected
    characteristics TEXT,              -- JSON: what defines this segment
    preferred_categories TEXT,         -- JSON: top content categories
    preferred_times TEXT,              -- JSON: best upload times
    eps_used REAL,                    -- DBSCAN eps parameter used
    min_samples_used INTEGER,         -- DBSCAN min_samples used
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Phase 2: API authentication tokens (ex29)
CREATE TABLE IF NOT EXISTS user_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    token TEXT UNIQUE NOT NULL,
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Phase 2: Curriculum plan (ex33)
CREATE TABLE IF NOT EXISTS curriculum_plan (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position INTEGER NOT NULL,
    suggested_query TEXT NOT NULL,
    target_learning_type TEXT,
    target_category TEXT,
    target_emotion TEXT,
    rationale TEXT,
    status TEXT DEFAULT 'planned',     -- planned, in_progress, completed, skipped
    short_id INTEGER,
    planned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (short_id) REFERENCES shorts(id)
);

-- Phase 2: Random Forest model snapshots (ex25)
CREATE TABLE IF NOT EXISTS model_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_type TEXT NOT NULL,          -- random_forest, dbscan, linear_regression
    target TEXT NOT NULL,              -- engagement_rate, impressions, retention_avg
    feature_importances TEXT,          -- JSON: {feature: importance_score}
    r_squared REAL,
    r_squared_cv REAL,                -- cross-validated R²
    residual_pattern TEXT,            -- JSON: {has_pattern, description}
    variance_explained REAL,
    variance_unexplained REAL,
    n_samples INTEGER,
    n_features INTEGER,
    hyperparameters TEXT,             -- JSON: {n_trees, max_depth, ...}
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_agent ON audit_log(agent_name);
CREATE INDEX IF NOT EXISTS idx_knowledge_topic ON knowledge_base(topic);
CREATE INDEX IF NOT EXISTS idx_knowledge_category ON knowledge_base(category);
CREATE INDEX IF NOT EXISTS idx_ab_tests_status ON ab_tests(status);
CREATE INDEX IF NOT EXISTS idx_retention_analytics ON retention_curves(analytics_id);
CREATE INDEX IF NOT EXISTS idx_retention_second ON retention_curves(second);
CREATE INDEX IF NOT EXISTS idx_retention_events_type ON retention_events(event_type);
CREATE INDEX IF NOT EXISTS idx_demographics_date ON audience_demographics(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_demographics_dim ON audience_demographics(dimension, dimension_value);
CREATE INDEX IF NOT EXISTS idx_user_tokens ON user_tokens(token);
CREATE INDEX IF NOT EXISTS idx_curriculum_status ON curriculum_plan(status);
CREATE INDEX IF NOT EXISTS idx_model_snapshots_type ON model_snapshots(model_type);

-- Trending topics (daily snapshots from Google Trends)
CREATE TABLE IF NOT EXISTS trending_topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    interest INTEGER DEFAULT 0,          -- 0-100 Google Trends score
    rising INTEGER DEFAULT 0,            -- 1 if breakout/rising topic
    geo TEXT DEFAULT '',                  -- country code
    source TEXT DEFAULT 'pytrends',       -- pytrends, manual
    snapshot_date TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_trending_date ON trending_topics(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_trending_topic ON trending_topics(topic);

-- Clip library: tracks every reusable clip/panel across verticals
CREATE TABLE IF NOT EXISTS clip_library (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Source identification
    source_type TEXT NOT NULL,             -- 'movie', 'anime', 'manga_panel'
    source_id INTEGER,                     -- movie_id or manga_series_id
    quote_id INTEGER,                      -- quotes.id or manga_quotes.id
    -- Content
    file_path TEXT,                         -- path to video clip or panel image
    thumbnail_path TEXT,
    audio_path TEXT,                        -- narration audio for this clip
    duration_s REAL,
    -- Text content
    quote_text TEXT,                        -- the quote/dialogue text
    character_name TEXT,                   -- who said it
    ocr_text TEXT,                         -- raw OCR text from panel
    -- Semantic metadata
    title TEXT,                            -- "Griffith betrayal speech"
    description TEXT,                      -- longer description for search
    tags TEXT,                             -- JSON array: ["villain", "dark", "betrayal"]
    category TEXT,                         -- villain, motivational, philosophical...
    emotion TEXT,
    themes TEXT,                           -- JSON array: ["power", "ambition", "sacrifice"]
    -- Source reference
    chapter TEXT,                          -- manga chapter number
    page_number INTEGER,                   -- page within chapter
    panel_index INTEGER,                   -- panel within page
    -- ChromaDB reference
    chroma_id TEXT,                        -- ID in ChromaDB collection for semantic search
    -- Usage tracking
    times_used INTEGER DEFAULT 0,
    last_used_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Junction: which clips are used in which shorts
CREATE TABLE IF NOT EXISTS short_clips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    short_id INTEGER NOT NULL,
    clip_id INTEGER NOT NULL,
    position INTEGER DEFAULT 0,            -- order in the short
    start_s REAL DEFAULT 0,                -- start time in the short
    end_s REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (short_id) REFERENCES shorts(id),
    FOREIGN KEY (clip_id) REFERENCES clip_library(id)
);

-- Pipeline runs: track automated executions
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline TEXT NOT NULL,                 -- 'manga', 'movies', 'learn'
    status TEXT DEFAULT 'running',          -- running, completed, failed
    trigger TEXT DEFAULT 'manual',          -- manual, github_action, frontend, scheduled
    params TEXT,                            -- JSON: parameters used
    steps_completed TEXT,                   -- JSON array of completed steps
    steps_failed TEXT,                      -- JSON array of failed steps
    shorts_produced INTEGER DEFAULT 0,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_clip_source ON clip_library(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_clip_category ON clip_library(category);
CREATE INDEX IF NOT EXISTS idx_clip_chroma ON clip_library(chroma_id);
CREATE INDEX IF NOT EXISTS idx_short_clips_short ON short_clips(short_id);
CREATE INDEX IF NOT EXISTS idx_short_clips_clip ON short_clips(clip_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status ON pipeline_runs(status);

CREATE TABLE IF NOT EXISTS short_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    short_id INTEGER NOT NULL,
    issue_type TEXT DEFAULT 'other',  -- voice, image, timing, other
    start_s REAL DEFAULT 0,
    end_s REAL DEFAULT 0,
    note TEXT,
    reported_by TEXT,
    resolved INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (short_id) REFERENCES shorts(id)
);
CREATE INDEX IF NOT EXISTS idx_short_issues_short ON short_issues(short_id);
"""


def get_db(data_dir: Path) -> sqlite3.Connection:
    """Get or create the SQLite database connection."""
    db_path = data_dir / "shorts_pipeline.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate_columns(conn)
    return conn


class db_context:
    """Context manager for safe database connections. Closes on exit."""
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.conn = None

    def __enter__(self) -> sqlite3.Connection:
        self.conn = get_db(self.data_dir)
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            if exc_type:
                self.conn.rollback()
            self.conn.close()
        return False


def _migrate_columns(conn: sqlite3.Connection):
    """Add columns to existing tables (ALTER TABLE IF NOT EXISTS workaround)."""
    migrations = [
        # Phase 2: Lesson taxonomy columns on quotes (ex31)
        ("quotes", "learning_type", "TEXT"),
        ("quotes", "life_lesson", "TEXT"),
        ("quotes", "curriculum_area", "TEXT"),
        # Phase 2: Extra analytics columns (ex24)
        ("analytics", "retention_curve_fetched", "INTEGER DEFAULT 0"),
        ("analytics", "watch_time_minutes", "REAL DEFAULT 0"),
        ("analytics", "avg_view_duration_s", "REAL DEFAULT 0"),
        ("analytics", "subscriber_gained", "INTEGER DEFAULT 0"),
        ("analytics", "subscriber_lost", "INTEGER DEFAULT 0"),
        # Clip library extra columns
        ("clip_library", "audio_path", "TEXT"),
        ("clip_library", "quote_text", "TEXT"),
        ("clip_library", "character_name", "TEXT"),
        ("clip_library", "ocr_text", "TEXT"),
        ("clip_library", "chapter", "TEXT"),
        ("clip_library", "page_number", "INTEGER"),
        ("clip_library", "panel_index", "INTEGER"),
    ]
    for table, column, col_type in migrations:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        except sqlite3.OperationalError:
            pass  # Column already exists


def register_clip(conn: sqlite3.Connection, **kwargs) -> int:
    """Register a clip in the library for reuse. Returns clip id.

    Deduplicates by file_path — same file won't be registered twice.
    """
    file_path = kwargs.get("file_path", "")
    if file_path:
        cur = conn.execute("SELECT id FROM clip_library WHERE file_path = ?", (file_path,))
        row = cur.fetchone()
        if row:
            return row["id"]

    cur = conn.execute(
        """INSERT INTO clip_library
           (source_type, source_id, quote_id, file_path, thumbnail_path, audio_path,
            duration_s, quote_text, character_name, ocr_text, title, description,
            tags, category, emotion, themes, chapter, page_number, panel_index)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            kwargs.get("source_type", "manga_panel"),
            kwargs.get("source_id"),
            kwargs.get("quote_id"),
            file_path,
            kwargs.get("thumbnail_path"),
            kwargs.get("audio_path"),
            kwargs.get("duration_s"),
            kwargs.get("quote_text"),
            kwargs.get("character_name"),
            kwargs.get("ocr_text"),
            kwargs.get("title"),
            kwargs.get("description"),
            kwargs.get("tags"),
            kwargs.get("category"),
            kwargs.get("emotion"),
            kwargs.get("themes"),
            kwargs.get("chapter"),
            kwargs.get("page_number"),
            kwargs.get("panel_index"),
        ),
    )
    conn.commit()
    return cur.lastrowid


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
