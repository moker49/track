from __future__ import annotations

import sqlite3
from pathlib import Path


def connect_database(path: str | Path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def normalize_movie_added_timestamps(
    db: sqlite3.Connection, movie_id: int | None = None
) -> int:
    """Ensure a movie's add event never follows its earliest watch date."""
    cursor = db.execute(
        """
        UPDATE movies
        SET added_at = (
            SELECT MIN(COALESCE(h.diary_date, h.watch_date, substr(h.added_at, 1, 10)))
                   || 'T00:00:00+00:00'
            FROM movie_watch_history h
            WHERE h.movie_id = movies.id
        )
        WHERE (? IS NULL OR movies.id = ?)
          AND EXISTS (
              SELECT 1
              FROM movie_watch_history h
              WHERE h.movie_id = movies.id
                AND COALESCE(h.diary_date, h.watch_date, substr(h.added_at, 1, 10))
                    < date(movies.added_at)
          )
        """,
        (movie_id, movie_id),
    )
    return cursor.rowcount


def initialize_database(db: sqlite3.Connection, schema_path: str | Path) -> None:
    schema = Path(schema_path).read_text(encoding="utf-8")
    db.executescript(schema)
    # Skips used to be a single mutable marker per episode. They are now dated,
    # repeatable resolution records, so preserve every existing marker while
    # replacing the old uniqueness constraint.
    skip_schema = db.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'episode_skips'"
    ).fetchone()
    if skip_schema and "episode_id INTEGER NOT NULL UNIQUE" in (skip_schema["sql"] or ""):
        db.execute("ALTER TABLE episode_skips RENAME TO episode_skips_legacy")
        db.execute(
            """
            CREATE TABLE episode_skips (
                id INTEGER PRIMARY KEY,
                episode_id INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
                skipped_at TEXT NOT NULL
            )
            """
        )
        db.execute(
            "INSERT INTO episode_skips (id, episode_id, skipped_at) SELECT id, episode_id, skipped_at FROM episode_skips_legacy"
        )
        db.execute("DROP TABLE episode_skips_legacy")
        db.execute("CREATE INDEX IF NOT EXISTS idx_episode_skips_episode ON episode_skips(episode_id)")
    # SQLite does not add columns when CREATE TABLE IF NOT EXISTS sees an older
    # table, so keep existing personal libraries compatible with new fields.
    for table, column, definition in (
        ("shows", "liked", "INTEGER NOT NULL DEFAULT 0 CHECK (liked IN (0, 1))"),
        ("shows", "watch_again", "INTEGER NOT NULL DEFAULT 0 CHECK (watch_again IN (0, 1))"),
        ("shows", "watch_again_baseline", "INTEGER"),
        ("movies", "liked", "INTEGER NOT NULL DEFAULT 0 CHECK (liked IN (0, 1))"),
        ("movies", "watch_again", "INTEGER NOT NULL DEFAULT 0 CHECK (watch_again IN (0, 1))"),
        ("episode_watch_history", "show_in_diary", "INTEGER NOT NULL DEFAULT 1 CHECK (show_in_diary IN (0, 1))"),
        ("season_watch_history", "show_in_diary", "INTEGER NOT NULL DEFAULT 1 CHECK (show_in_diary IN (0, 1))"),
        ("movie_watch_history", "show_in_diary", "INTEGER NOT NULL DEFAULT 1 CHECK (show_in_diary IN (0, 1))"),
        ("episode_watch_history", "batch_id", "TEXT"),
        ("season_watch_history", "batch_id", "TEXT"),
        ("episode_skips", "skip_date", "TEXT"),
        ("episode_skips", "batch_id", "TEXT"),
        ("episode_watch_history", "diary_date", "TEXT"),
        ("season_watch_history", "diary_date", "TEXT"),
        ("movie_watch_history", "diary_date", "TEXT"),
        ("episode_skips", "diary_date", "TEXT"),
        ("season_skip_history", "diary_date", "TEXT"),
    ):
        columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    # Favorites is no longer a library concept. Remove its retired storage from
    # existing databases as well as new installs.
    for table in ("shows", "movies"):
        columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
        if "is_favorite" in columns:
            db.execute(f"ALTER TABLE {table} DROP COLUMN is_favorite")
    db.execute("CREATE INDEX IF NOT EXISTS idx_episode_watch_history_batch ON episode_watch_history(batch_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_episode_skips_batch ON episode_skips(batch_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_season_watch_history_batch ON season_watch_history(batch_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_season_skip_history_batch ON season_skip_history(batch_id)")
    # A retired boolean marker represented a watch that should stay out of the
    # diary. Preserve it as a normal hidden history event, then remove the
    # obsolete column so all watch state has one source of truth.
    episode_columns = {
        row["name"] for row in db.execute("PRAGMA table_info(episodes)")
    }
    if "is_watched_without_diary" in episode_columns:
        db.execute(
            """
            INSERT INTO episode_watch_history (episode_id, added_at, watch_date, show_in_diary)
            SELECT e.id, s.added_at, NULL, 0
            FROM episodes e
            JOIN seasons sn ON sn.id = e.season_id
            JOIN shows s ON s.id = sn.show_id
            WHERE e.is_watched_without_diary = 1
              AND NOT EXISTS (
                  SELECT 1 FROM episode_watch_history h WHERE h.episode_id = e.id
              )
            """
        )
        db.execute("ALTER TABLE episodes DROP COLUMN is_watched_without_diary")

    movie_columns = {
        row["name"] for row in db.execute("PRAGMA table_info(movies)")
    }
    if "is_watched_without_diary" in movie_columns:
        db.execute(
            """
            INSERT INTO movie_watch_history (movie_id, added_at, watch_date, show_in_diary)
            SELECT m.id, m.added_at, NULL, 0
            FROM movies m
            WHERE m.is_watched_without_diary = 1
              AND NOT EXISTS (
                  SELECT 1 FROM movie_watch_history h WHERE h.movie_id = m.id
              )
            """
        )
        db.execute("ALTER TABLE movies DROP COLUMN is_watched_without_diary")
    normalize_movie_added_timestamps(db)
    db.execute("PRAGMA optimize")
    db.commit()
