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
    is_favorite INTEGER NOT NULL DEFAULT 0 CHECK (is_favorite IN (0, 1)),
    liked INTEGER NOT NULL DEFAULT 0 CHECK (liked IN (0, 1)),
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
    is_watched_without_diary INTEGER NOT NULL DEFAULT 0 CHECK (is_watched_without_diary IN (0, 1)),
    tmdb_payload TEXT NOT NULL DEFAULT '{}',
    UNIQUE (season_id, episode_number)
);

CREATE TABLE IF NOT EXISTS episode_watch_history (
    id INTEGER PRIMARY KEY,
    episode_id INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    added_at TEXT NOT NULL,
    watch_date TEXT,
    show_in_diary INTEGER NOT NULL DEFAULT 1 CHECK (show_in_diary IN (0, 1))
);

CREATE TABLE IF NOT EXISTS season_watch_history (
    id INTEGER PRIMARY KEY,
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    added_at TEXT NOT NULL,
    watch_date TEXT,
    show_in_diary INTEGER NOT NULL DEFAULT 1 CHECK (show_in_diary IN (0, 1))
);

CREATE TABLE IF NOT EXISTS episode_skips (
    id INTEGER PRIMARY KEY,
    episode_id INTEGER NOT NULL UNIQUE
        REFERENCES episodes(id) ON DELETE CASCADE,
    skipped_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS show_notes (
    id INTEGER PRIMARY KEY,
    show_id INTEGER NOT NULL REFERENCES shows(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    added_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS episode_notes (
    id INTEGER PRIMARY KEY,
    episode_id INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    added_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS episode_external_ids (
    id INTEGER PRIMARY KEY,
    episode_id INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    UNIQUE (source, external_id)
);

CREATE INDEX IF NOT EXISTS idx_seasons_show ON seasons(show_id);
CREATE INDEX IF NOT EXISTS idx_episodes_season ON episodes(season_id);
CREATE INDEX IF NOT EXISTS idx_watch_history_episode ON episode_watch_history(episode_id);
CREATE INDEX IF NOT EXISTS idx_season_watch_history_season ON season_watch_history(season_id);
CREATE INDEX IF NOT EXISTS idx_episode_skips_episode ON episode_skips(episode_id);
CREATE INDEX IF NOT EXISTS idx_show_state_history_show ON show_state_history(show_id);
CREATE INDEX IF NOT EXISTS idx_show_notes_show ON show_notes(show_id);
CREATE INDEX IF NOT EXISTS idx_episode_notes_episode ON episode_notes(episode_id);
CREATE INDEX IF NOT EXISTS idx_episode_external_ids_episode ON episode_external_ids(episode_id);

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
    state TEXT NOT NULL CHECK (state IN ('ACTIVE', 'ARCHIVED')),
    is_tracked INTEGER NOT NULL DEFAULT 1 CHECK (is_tracked IN (0, 1)),
    liked INTEGER NOT NULL DEFAULT 0 CHECK (liked IN (0, 1)),
    is_watched_without_diary INTEGER NOT NULL DEFAULT 0 CHECK (is_watched_without_diary IN (0, 1)),
    added_at TEXT NOT NULL,
    active_at TEXT,
    archived_at TEXT,
    updated_at TEXT,
    tmdb_refreshed_at TEXT,
    tmdb_payload TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS movie_watch_history (
    id INTEGER PRIMARY KEY,
    movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    added_at TEXT NOT NULL,
    watch_date TEXT,
    show_in_diary INTEGER NOT NULL DEFAULT 1 CHECK (show_in_diary IN (0, 1))
);

CREATE TABLE IF NOT EXISTS movie_state_history (
    id INTEGER PRIMARY KEY,
    movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    state TEXT NOT NULL CHECK (state IN ('ACTIVE', 'ARCHIVED')),
    entered_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_movie_watch_history_movie ON movie_watch_history(movie_id);
CREATE INDEX IF NOT EXISTS idx_movie_state_history_movie ON movie_state_history(movie_id);

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
