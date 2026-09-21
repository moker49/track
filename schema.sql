CREATE TABLE IF NOT EXISTS shows (
    id INTEGER PRIMARY KEY,
    tmdb_id INTEGER UNIQUE NOT NULL,
    tvdb_id INTEGER UNIQUE,
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
    state TEXT NOT NULL CHECK (state IN ('ACTIVE', 'ARCHIVED')),
    is_tracked INTEGER NOT NULL DEFAULT 1 CHECK (is_tracked IN (0, 1)),
    liked_at TEXT,
    watch_again INTEGER NOT NULL DEFAULT 0 CHECK (watch_again IN (0, 1)),
    watch_again_baseline INTEGER,
    added_at TEXT NOT NULL,
    active_at TEXT,
    archived_at TEXT,
    updated_at TEXT,
    tmdb_refreshed_at TEXT,
    tmdb_payload TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS show_state_history (
    id INTEGER PRIMARY KEY,
    show_id INTEGER NOT NULL REFERENCES shows(id) ON DELETE CASCADE,
    state TEXT NOT NULL CHECK (state IN ('ACTIVE', 'ARCHIVED')),
    entered_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS show_metadata_refresh_failures (
    show_id INTEGER PRIMARY KEY REFERENCES shows(id) ON DELETE CASCADE,
    failure_count INTEGER NOT NULL CHECK (failure_count > 0),
    last_attempt_at TEXT NOT NULL,
    retry_after TEXT NOT NULL,
    error TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_show_metadata_refresh_failures_retry_after
    ON show_metadata_refresh_failures(retry_after);

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
    tvdb_id INTEGER UNIQUE,
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
    diary_date TEXT,
    batch_id TEXT
);

CREATE TABLE IF NOT EXISTS season_watch_history (
    id INTEGER PRIMARY KEY,
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    added_at TEXT NOT NULL,
    diary_date TEXT,
    batch_id TEXT NOT NULL REFERENCES season_log_batches(id)
);

CREATE TABLE IF NOT EXISTS episode_skips (
    id INTEGER PRIMARY KEY,
    episode_id INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    skipped_at TEXT NOT NULL,
    diary_date TEXT,
    batch_id TEXT
);

CREATE TABLE IF NOT EXISTS season_skip_history (
    id INTEGER PRIMARY KEY,
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    added_at TEXT NOT NULL,
    diary_date TEXT,
    batch_id TEXT NOT NULL REFERENCES season_log_batches(id)
);

CREATE TABLE IF NOT EXISTS season_log_batches (
    id TEXT PRIMARY KEY,
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    action_kind TEXT NOT NULL CHECK (action_kind IN ('watch', 'skip')),
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_seasons_show ON seasons(show_id);
CREATE INDEX IF NOT EXISTS idx_episodes_season ON episodes(season_id);
CREATE INDEX IF NOT EXISTS idx_watch_history_episode ON episode_watch_history(episode_id);
CREATE INDEX IF NOT EXISTS idx_season_watch_history_season ON season_watch_history(season_id);
CREATE INDEX IF NOT EXISTS idx_episode_skips_episode ON episode_skips(episode_id);
CREATE INDEX IF NOT EXISTS idx_show_state_history_show ON show_state_history(show_id);
CREATE INDEX IF NOT EXISTS idx_episode_watch_history_batch ON episode_watch_history(batch_id);
CREATE INDEX IF NOT EXISTS idx_episode_skips_batch ON episode_skips(batch_id);
CREATE INDEX IF NOT EXISTS idx_season_watch_history_batch ON season_watch_history(batch_id);
CREATE INDEX IF NOT EXISTS idx_season_skip_history_batch ON season_skip_history(batch_id);

CREATE TABLE IF NOT EXISTS movies (
    id INTEGER PRIMARY KEY,
    tmdb_id INTEGER UNIQUE NOT NULL,
    title TEXT NOT NULL,
    original_title TEXT,
    overview TEXT,
    poster_path TEXT,
    backdrop_path TEXT,
    release_date TEXT,
    runtime_minutes INTEGER,
    status TEXT,
    genres TEXT,
    original_language TEXT,
    is_tracked INTEGER NOT NULL DEFAULT 1 CHECK (is_tracked IN (0, 1)),
    liked_at TEXT,
    watch_again INTEGER NOT NULL DEFAULT 0 CHECK (watch_again IN (0, 1)),
    added_at TEXT NOT NULL,
    updated_at TEXT,
    tmdb_refreshed_at TEXT,
    tmdb_payload TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS movie_watch_history (
    id INTEGER PRIMARY KEY,
    movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    added_at TEXT NOT NULL,
    diary_date TEXT
);

CREATE INDEX IF NOT EXISTS idx_movie_watch_history_movie ON movie_watch_history(movie_id);

CREATE TABLE IF NOT EXISTS actors (
    id INTEGER PRIMARY KEY,
    tmdb_person_id INTEGER UNIQUE NOT NULL,
    name TEXT NOT NULL,
    profile_path TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS show_cast (
    show_id INTEGER NOT NULL REFERENCES shows(id) ON DELETE CASCADE,
    actor_id INTEGER NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
    character_name TEXT,
    cast_order INTEGER,
    PRIMARY KEY (show_id, actor_id, character_name)
);

CREATE TABLE IF NOT EXISTS movie_cast (
    movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    actor_id INTEGER NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
    character_name TEXT,
    cast_order INTEGER,
    PRIMARY KEY (movie_id, actor_id, character_name)
);

CREATE INDEX IF NOT EXISTS idx_show_cast_show_order ON show_cast(show_id, cast_order);
CREATE INDEX IF NOT EXISTS idx_movie_cast_movie_order ON movie_cast(movie_id, cast_order);

CREATE TABLE IF NOT EXISTS show_cast_sync (
    show_id INTEGER PRIMARY KEY REFERENCES shows(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('pending', 'ready', 'failed')),
    updated_at TEXT NOT NULL,
    error TEXT
);

CREATE TABLE IF NOT EXISTS movie_cast_sync (
    movie_id INTEGER PRIMARY KEY REFERENCES movies(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('pending', 'ready', 'failed')),
    updated_at TEXT NOT NULL,
    error TEXT
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
