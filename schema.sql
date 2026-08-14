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
    state TEXT NOT NULL CHECK (state IN ('WATCHLIST', 'ACTIVE', 'ARCHIVED')),
    added_at TEXT NOT NULL,
    watchlist_at TEXT,
    active_at TEXT,
    archived_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS show_state_history (
    id INTEGER PRIMARY KEY,
    show_id INTEGER NOT NULL REFERENCES shows(id) ON DELETE CASCADE,
    state TEXT NOT NULL CHECK (state IN ('WATCHLIST', 'ACTIVE', 'ARCHIVED')),
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
    UNIQUE (season_id, episode_number)
);

CREATE TABLE IF NOT EXISTS episode_watch_history (
    id INTEGER PRIMARY KEY,
    episode_id INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    watched_at TEXT NOT NULL,
    unwatched_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_seasons_show ON seasons(show_id);
CREATE INDEX IF NOT EXISTS idx_episodes_season ON episodes(season_id);
CREATE INDEX IF NOT EXISTS idx_watch_history_episode ON episode_watch_history(episode_id);
CREATE INDEX IF NOT EXISTS idx_show_state_history_show ON show_state_history(show_id);

CREATE TABLE IF NOT EXISTS popular_show_stubs (
    id INTEGER PRIMARY KEY,
    tmdb_id INTEGER UNIQUE NOT NULL,
    name TEXT NOT NULL,
    subtitle TEXT,
    popularity_rank INTEGER NOT NULL
);
