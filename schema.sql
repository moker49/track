CREATE TABLE IF NOT EXISTS shows (
    id INTEGER PRIMARY KEY,
    tmdb_id INTEGER UNIQUE NOT NULL,
    name TEXT NOT NULL,
    original_name TEXT,
    overview TEXT,
    tagline TEXT,
    poster_path TEXT,
    backdrop_path TEXT,
    first_air_date TEXT,
    status TEXT,
    genres TEXT,
    original_language TEXT,
    state TEXT NOT NULL CHECK (state IN ('WATCHING', 'ARCHIVED')),
    is_tracked INTEGER NOT NULL DEFAULT 1 CHECK (is_tracked IN (0, 1)),
    added_at TEXT NOT NULL,
    watching_at TEXT,
    archived_at TEXT,
    updated_at TEXT,
    tmdb_refreshed_at TEXT,
    tmdb_payload TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS show_state_history (
    id INTEGER PRIMARY KEY,
    show_id INTEGER NOT NULL REFERENCES shows(id) ON DELETE CASCADE,
    state TEXT NOT NULL CHECK (state IN ('WATCHING', 'ARCHIVED')),
    entered_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS seasons (
    id INTEGER PRIMARY KEY,
    show_id INTEGER NOT NULL REFERENCES shows(id) ON DELETE CASCADE,
    tmdb_id INTEGER UNIQUE NOT NULL,
    season_number INTEGER NOT NULL,
    name TEXT NOT NULL,
    overview TEXT,
    air_date TEXT,
    poster_path TEXT,
    episode_count INTEGER,
    is_progress_counted INTEGER NOT NULL DEFAULT 1 CHECK (is_progress_counted IN (0, 1)),
    tmdb_payload TEXT NOT NULL DEFAULT '{}',
    UNIQUE (show_id, season_number)
);

CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY,
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    tmdb_id INTEGER UNIQUE NOT NULL,
    episode_number INTEGER NOT NULL,
    name TEXT NOT NULL,
    overview TEXT,
    air_date TEXT,
    runtime_minutes INTEGER,
    still_path TEXT,
    tmdb_payload TEXT NOT NULL DEFAULT '{}',
    UNIQUE (season_id, episode_number)
);

CREATE TABLE IF NOT EXISTS episode_watch_history (
    id INTEGER PRIMARY KEY,
    episode_id INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    added_at TEXT NOT NULL,
    watch_date TEXT
);

CREATE TABLE IF NOT EXISTS season_watch_history (
    id INTEGER PRIMARY KEY,
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    added_at TEXT NOT NULL,
    watch_date TEXT
);

CREATE INDEX IF NOT EXISTS idx_seasons_show ON seasons(show_id);
CREATE INDEX IF NOT EXISTS idx_episodes_season ON episodes(season_id);
CREATE INDEX IF NOT EXISTS idx_watch_history_episode ON episode_watch_history(episode_id);
CREATE INDEX IF NOT EXISTS idx_season_watch_history_season ON season_watch_history(season_id);
CREATE INDEX IF NOT EXISTS idx_show_state_history_show ON show_state_history(show_id);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tmdb_cache (
    cache_key TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    refreshed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS image_cache (
    id INTEGER PRIMARY KEY,
    tmdb_path TEXT NOT NULL,
    image_type TEXT NOT NULL,
    size TEXT NOT NULL,
    local_filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    downloaded_at TEXT NOT NULL,
    UNIQUE (tmdb_path, image_type, size)
);
