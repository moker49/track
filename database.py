from __future__ import annotations

import sqlite3
from pathlib import Path


def connect_database(path: str | Path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def initialize_database(db: sqlite3.Connection, schema_path: str | Path) -> None:
    schema = Path(schema_path).read_text(encoding="utf-8")
    db.executescript(schema)
    # SQLite does not add columns when CREATE TABLE IF NOT EXISTS sees an older
    # table, so keep existing personal libraries compatible with new fields.
    for table, column, definition in (
        ("shows", "liked", "INTEGER NOT NULL DEFAULT 0 CHECK (liked IN (0, 1))"),
        ("movies", "liked", "INTEGER NOT NULL DEFAULT 0 CHECK (liked IN (0, 1))"),
        ("movies", "is_watched_without_diary", "INTEGER NOT NULL DEFAULT 0 CHECK (is_watched_without_diary IN (0, 1))"),
        ("episodes", "is_watched_without_diary", "INTEGER NOT NULL DEFAULT 0 CHECK (is_watched_without_diary IN (0, 1))"),
        ("episode_watch_history", "show_in_diary", "INTEGER NOT NULL DEFAULT 1 CHECK (show_in_diary IN (0, 1))"),
        ("season_watch_history", "show_in_diary", "INTEGER NOT NULL DEFAULT 1 CHECK (show_in_diary IN (0, 1))"),
        ("movie_watch_history", "show_in_diary", "INTEGER NOT NULL DEFAULT 1 CHECK (show_in_diary IN (0, 1))"),
    ):
        columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    # Convert the short-lived undated-movie marker into a normal watch record
    # that is intentionally hidden from the diary.
    db.execute(
        """
        INSERT INTO movie_watch_history (movie_id, added_at, watch_date, show_in_diary)
        SELECT m.id, m.added_at, NULL, 0
        FROM movies m
        WHERE m.is_watched_without_diary = 1
          AND NOT EXISTS (SELECT 1 FROM movie_watch_history h WHERE h.movie_id = m.id)
        """
    )
    db.execute("UPDATE movies SET is_watched_without_diary = 0 WHERE is_watched_without_diary = 1")
    db.execute(
        """
        INSERT INTO movie_state_history (movie_id, state, entered_at)
        SELECT id, state, COALESCE(archived_at, active_at, added_at)
        FROM movies m
        WHERE is_tracked = 1
          AND NOT EXISTS (SELECT 1 FROM movie_state_history h WHERE h.movie_id = m.id)
        """
    )
    db.execute("PRAGMA optimize")
