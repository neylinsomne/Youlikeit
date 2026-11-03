"""SQLite database for storing movies, quotes, and timestamps."""

import logging
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)


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

-- ============================================================
-- Phase: Trends and Multi-Topic ETL
-- ============================================================

-- Main multi-topic trend storage
CREATE TABLE IF NOT EXISTS trend_topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    cluster TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'google_trends',
    interest INTEGER DEFAULT 0,
    rising BOOLEAN DEFAULT 0,
    geo TEXT DEFAULT '',
    snapshot_date TEXT NOT NULL,
    snapshot_hour INTEGER,
    embedding BLOB,
    sentiment REAL,
    related_hashtags TEXT,
    related_people TEXT,
    media_urls TEXT,
    source_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_trend_topic ON trend_topics(topic);
CREATE INDEX IF NOT EXISTS idx_trend_cluster_date ON trend_topics(cluster, snapshot_date);
CREATE INDEX IF NOT EXISTS idx_trend_geo ON trend_topics(geo);
CREATE INDEX IF NOT EXISTS idx_trend_source ON trend_topics(source);

-- Configurable topic clusters
CREATE TABLE IF NOT EXISTS topic_clusters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cluster_name TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    priority INTEGER DEFAULT 5,
    seeds_json TEXT NOT NULL DEFAULT '[]',
    rss_feeds_json TEXT NOT NULL DEFAULT '[]',
    interval_minutes INTEGER DEFAULT 240,
    enabled BOOLEAN DEFAULT 1,
    last_scraped_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Cross-reference: trends linked to content
CREATE TABLE IF NOT EXISTS trend_content_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trend_id INTEGER NOT NULL,
    content_type TEXT NOT NULL,
    content_id INTEGER NOT NULL,
    relevance_score REAL DEFAULT 0.5,
    match_method TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (trend_id) REFERENCES trend_topics(id)
);

CREATE INDEX IF NOT EXISTS idx_tcl_trend ON trend_content_links(trend_id);
CREATE INDEX IF NOT EXISTS idx_tcl_content ON trend_content_links(content_type, content_id);

-- Trending people and celebrities
CREATE TABLE IF NOT EXISTS trending_people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'google_trends',
    image_url TEXT,
    wikipedia_summary TEXT,
    tmdb_person_id INTEGER,
    trend_score REAL DEFAULT 0,
    snapshot_date TEXT NOT NULL,
    related_works TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tp_name ON trending_people(name);
CREATE INDEX IF NOT EXISTS idx_tp_date ON trending_people(snapshot_date);

-- ETL run tracking
CREATE TABLE IF NOT EXISTS etl_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline_name TEXT NOT NULL,
    cluster_name TEXT,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP,
    status TEXT DEFAULT 'running',
    topics_found INTEGER DEFAULT 0,
    topics_new INTEGER DEFAULT 0,
    topics_linked INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    error_log TEXT,
    geo TEXT DEFAULT ''
);

-- Scraper health metrics
CREATE TABLE IF NOT EXISTS scraper_health (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scraper_name TEXT NOT NULL,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    avg_latency_ms REAL DEFAULT 0,
    last_success_at TIMESTAMP,
    last_failure_at TIMESTAMP,
    last_error TEXT,
    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Raw entertainment/gaming/forum signals ingested by market_signals.py.
-- One row per (source, normalized_title). Bounded by retention window via
-- delete-where-fetched_at < N days in the distiller.
CREATE TABLE IF NOT EXISTS market_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,            -- 'steam_charts', 'reddit_r_anime', etc.
    source_type TEXT NOT NULL,       -- 'gaming_chart', 'reddit_thread', 'editorial_rss', 'release_tracker', 'letterboxd', 'forum'
    domain TEXT,                     -- 'gaming', 'anime_manga', 'movies_tv', 'music', 'latam'
    title TEXT NOT NULL,
    normalized_title TEXT NOT NULL,  -- lowercased, punct-stripped, for dedupe
    url TEXT,
    summary TEXT,                    -- short blurb / RSS description
    raw_score REAL DEFAULT 0,        -- source-native score (upvotes, viewers, position)
    raw_meta TEXT,                   -- JSON: subreddit, num_comments, rank, etc.
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source, normalized_title)
);
CREATE INDEX IF NOT EXISTS idx_market_signals_fetched ON market_signals(fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_market_signals_domain ON market_signals(domain, fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_market_signals_norm ON market_signals(normalized_title);

-- Distilled briefs per persona — one row per (persona, cluster_key) per run.
-- The distiller writes this; content_rotator / script_generator read it.
CREATE TABLE IF NOT EXISTS persona_briefs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    persona TEXT NOT NULL,           -- 'deep_mind', 'pop_oracle', 'latam'
    cluster_key TEXT NOT NULL,       -- normalized topic identifier
    headline TEXT NOT NULL,          -- best representative title
    domain TEXT,                     -- 'gaming', 'anime_manga', 'movies_tv', 'latam'
    score REAL DEFAULT 0,            -- distilled score (freq * recency * persona_alignment)
    frequency INTEGER DEFAULT 1,     -- count of sources that mentioned it
    sources_json TEXT,               -- JSON array of signal IDs that fed this brief
    suggested_angle TEXT,            -- LLM-generated 1-sentence framing hook
    consumed_at TIMESTAMP,           -- set when content_rotator picks it up
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(persona, cluster_key, created_at)
);
CREATE INDEX IF NOT EXISTS idx_briefs_persona_score ON persona_briefs(persona, score DESC);
CREATE INDEX IF NOT EXISTS idx_briefs_unconsumed ON persona_briefs(persona, consumed_at, score DESC);

-- Hook quality scores (post-render gate). Schema duplicado en
-- apps.scoring.hook_scorer.SCHEMA_HOOK_SCORES (ensure_schema) para que el módulo
-- funcione standalone; aquí se incluye para inicialización del DB principal.
CREATE TABLE IF NOT EXISTS hook_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_path TEXT NOT NULL,
    persona TEXT,
    vtype TEXT,
    series_slug TEXT,
    audio_energy_score REAL,
    cps_score REAL,
    accent_word_score REAL,
    llm_score REAL,
    overall_score REAL,
    raw_rms_peak REAL,
    raw_cps_observed REAL,
    raw_cps_target REAL,
    raw_first_sub_text TEXT,
    raw_llm_reasoning TEXT,
    passed INTEGER,
    notes TEXT,
    scored_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_hook_scores_path ON hook_scores(video_path);
CREATE INDEX IF NOT EXISTS idx_hook_scores_passed ON hook_scores(passed, scored_at DESC);

-- Iconic scene moments per series (themes/emotion classified).
-- Tambien creada por apps.content.thematic_classifier (IF NOT EXISTS, idempotente);
-- se incluye aqui para que el SCHEMA central la tenga (la lee content_rotator._is_classified).
CREATE TABLE IF NOT EXISTS scene_moments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    series_slug TEXT NOT NULL,
    season_number INTEGER,
    episode_number INTEGER,
    episode_name TEXT,
    iconic_score REAL DEFAULT 0.5,
    themes TEXT,              -- JSON list
    emotion TEXT,
    moment_description TEXT,
    quote TEXT,
    still_url TEXT,
    local_still_path TEXT
);
CREATE INDEX IF NOT EXISTS idx_scene_moments_slug ON scene_moments(series_slug);

-- Work-level cross references (Berserk <-> Dark Souls, ...). Antes solo la creaba
-- scripts/setup/seed_cross_refs.py, así que en una DB fresca fallaban culture_feed,
-- ab_testing, clean_and_produce y /api/cross-references. Mismo DDL que el seed.
CREATE TABLE IF NOT EXISTS cross_references (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_work TEXT NOT NULL,
    source_type TEXT NOT NULL,
    target_work TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_creator TEXT,
    reference_type TEXT NOT NULL,
    description_deep_mind TEXT,
    description_cinephile TEXT,
    description_pop_oracle TEXT,
    themes TEXT,
    strength REAL DEFAULT 0.7,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_cross_refs_source ON cross_references(source_work);
CREATE INDEX IF NOT EXISTS idx_cross_refs_target ON cross_references(target_work);

-- ============================================================
-- Analytics — Plausible (owner: docs/agents/ANALYTICS_AGENT.md)
-- Writes: scripts/analytics/*, src/apps/analytics/plausible_client.py
-- Privacy: no IPs, no user agents, no PII persisted (GDPR end-to-end).
-- ============================================================

-- Stats API response cache (1h TTL) so we don't hammer Plausible.
CREATE TABLE IF NOT EXISTS plausible_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint TEXT NOT NULL,          -- 'aggregate' | 'breakdown' | 'timeseries'
    params_hash TEXT NOT NULL,       -- sha256 of (endpoint + sorted params)
    json TEXT NOT NULL,              -- raw Stats API JSON response
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(endpoint, params_hash)
);
CREATE INDEX IF NOT EXISTS idx_plausible_cache_lookup ON plausible_cache(endpoint, params_hash, fetched_at DESC);

-- Aggregated page-level traffic snapshots (one row per page+period).
CREATE TABLE IF NOT EXISTS plausible_pageviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page TEXT NOT NULL,              -- normalized path: '/', '/dashboard.html', '/persona/deep_mind'
    visitors INTEGER DEFAULT 0,
    pageviews INTEGER DEFAULT 0,
    bounce_rate REAL,
    visit_duration REAL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    source TEXT DEFAULT 'plausible',
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(page, period_start, period_end)
);
CREATE INDEX IF NOT EXISTS idx_plausible_pageviews_page ON plausible_pageviews(page, period_end DESC);

-- Custom/goal events (persona_click, cta_click, ...). No PII in raw_props.
CREATE TABLE IF NOT EXISTS plausible_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_name TEXT NOT NULL,        -- 'persona_click', 'cta_click', 'pdf_view'
    page TEXT,
    count INTEGER DEFAULT 0,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    raw_props TEXT,                  -- JSON of extra props (no PII)
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(event_name, page, period_start, period_end)
);
CREATE INDEX IF NOT EXISTS idx_plausible_events_name ON plausible_events(event_name, period_end DESC);

-- Seed the default topic clusters
INSERT OR IGNORE INTO topic_clusters (cluster_name, display_name, priority, seeds_json, interval_minutes) VALUES
('movies_tv', 'Movies & TV', 9, '["movie release","tv series","streaming","netflix","peliculas","movie quotes","escenas de cine"]', 60),
('anime_manga_otaku', 'Anime & Manga', 9, '["anime release","manga chapter","cosplay","anime convention","anime trending","manga release"]', 60),
('music_entertainment', 'Music & Entertainment', 8, '["music charts","new album","concert","festival","billboard","trending song","viral music"]', 120),
('news_politics', 'News & Politics', 8, '["breaking news","politics today","world news","trending news","current events"]', 60),
('technology', 'Technology', 7, '["tech news","AI","startup","gadgets","cybersecurity","new technology"]', 120),
('sports', 'Sports', 6, '["sports highlights","football","NBA","UFC","motorsport","sports news"]', 180),
('gaming', 'Gaming', 9, '["gaming news","new game release","esports","indie game","steam sale","tier list","speedrun","videojuegos","game review","metacritic"]', 120),
('community_forums', 'Community & Forums', 8, '["reddit hot","fan reaction","tier list","fan theory","discussion thread","letterboxd review"]', 120),
('releases_tracker', 'Release Tracking', 8, '["anime release","manga chapter","new movie","trakt trending","letterboxd weekly","mangaupdates"]', 180),
('memes_viral', 'Memes & Viral', 6, '["viral meme","trending hashtag","viral video","internet challenge","trending meme"]', 120),
('fashion_lifestyle', 'Fashion & Lifestyle', 3, '["fashion week","streetwear","sneakers","beauty trends","fashion trends"]', 360),
('science_health', 'Science & Health', 5, '["science news","space","medical breakthrough","climate change","health news"]', 240),
('business_finance', 'Business & Finance', 3, '["stock market","crypto","business news","economy","finance tips"]', 360),
('latam_culture', 'LatAm Culture', 6, '["novela trending","musica latina","regueton","famosos latinos","telenovela","cine latino"]', 180);
"""

def get_db(data_dir: Path) -> sqlite3.Connection:
    """Get or create the SQLite database connection."""
    db_path = data_dir / "shorts_pipeline.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate_columns(conn)
    _ensure_domain_schemas(conn)
    return conn


# Tablas cuya definición vive en módulos de dominio (init_*/ensure_*). Las
# enganchamos aquí para que una DB fresca (`get_db`) tenga TODO el esquema en
# un solo punto — evita "no such table" cuando un módulo consulta una tabla
# que otro módulo debía crear. Imports diferidos: se resuelven en runtime,
# cuando `core.db` ya está cargado, así no hay ciclos de import.
_DOMAIN_SCHEMA_ENSURERS: list[tuple[str, str]] = [
    ("apps.production.content_rotator", "init_rotation_db"),      # content_produced
    ("apps.signals.brief_resolver",     "ensure_unresolved_schema"),  # unresolved_briefs_queue
    ("apps.content.personas",           "init_personas_db"),      # personas, persona_*
    ("apps.content.thematic_classifier", "init_db"),              # series_themes/arcs/scene_moments
    ("apps.production.treatment_tones", "init_crossover_db"),     # content_variants, crossover_metrics
    ("apps.scoring.hook_scorer",        "ensure_schema"),         # hook_scores (idempotente)
]


def _ensure_domain_schemas(conn: sqlite3.Connection) -> None:
    """Crea tablas definidas en módulos de dominio. Best-effort e idempotente.

    Cada `init_*` usa `CREATE TABLE IF NOT EXISTS`, así que llamarlas de más es
    inofensivo. Un fallo de import (módulo ausente en un runtime mínimo, p.ej.
    la cron de GHA que solo instala `requests`) no debe romper `get_db`.
    """
    import importlib
    for module_path, fn_name in _DOMAIN_SCHEMA_ENSURERS:
        try:
            mod = importlib.import_module(module_path)
        except ImportError as e:
            # Módulo ausente en un runtime mínimo (p.ej. cron con solo requests):
            # esperado, no es un error. DB sigue usable sin esas tablas.
            log.debug("domain schema skip (import) %s: %s", module_path, e)
            continue
        try:
            getattr(mod, fn_name)(conn)
        except Exception as e:  # noqa: BLE001
            # Un fallo AQUÍ (typo en un SCHEMA, init roto) NO debe romper get_db,
            # pero sí es un bug real: lo logueamos en WARNING para que sea visible
            # en vez de aparecer luego como "no such table" sin causa rastreable.
            log.warning("domain schema ensure FAILED %s.%s: %s", module_path, fn_name, e)
    conn.commit()


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
        # Phase: Trends additional columns
        ("trend_topics", "sentiment", "REAL"),
        ("trend_topics", "related_hashtags", "TEXT"),
        ("trend_topics", "related_people", "TEXT"),
        ("trend_topics", "media_urls", "TEXT"),
        ("trend_topics", "source_url", "TEXT"),
        ("trending_people", "wikipedia_summary", "TEXT"),
        ("trending_people", "related_works", "TEXT"),
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
