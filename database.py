from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
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
            SELECT MIN(COALESCE(h.diary_date, substr(h.added_at, 1, 10)))
                   || 'T00:00:00+00:00'
            FROM movie_watch_history h
            WHERE h.movie_id = movies.id
        )
        WHERE (? IS NULL OR movies.id = ?)
          AND EXISTS (
              SELECT 1
              FROM movie_watch_history h
              WHERE h.movie_id = movies.id
                AND COALESCE(h.diary_date, substr(h.added_at, 1, 10))
                    < date(movies.added_at)
          )
        """,
        (movie_id, movie_id),
    )
    return cursor.rowcount


def unknown_log_timestamp(media_added_at: str) -> str:
    """Place an unknown-date log just after the media's add event."""
    added_at = datetime.fromisoformat(media_added_at)
    if added_at.tzinfo is None:
        added_at = added_at.replace(tzinfo=timezone.utc)
    timestamp = added_at + timedelta(hours=1)
    return timestamp.isoformat(timespec="microseconds" if timestamp.microsecond else "seconds")


def initialize_database(db: sqlite3.Connection, schema_path: str | Path) -> None:
    schema = Path(schema_path).read_text(encoding="utf-8")
    db.executescript(schema)
    movie_columns = {row["name"] for row in db.execute("PRAGMA table_info(movies)")}
    if "state" not in movie_columns:
        db.execute("ALTER TABLE movies ADD COLUMN state TEXT NOT NULL DEFAULT 'ARCHIVED' CHECK (state IN ('ACTIVE', 'ARCHIVED'))")
    migration_name = "movie_state_from_likes_and_watch_history"
    if db.execute(
        "SELECT 1 FROM schema_migrations WHERE name = ?", (migration_name,)
    ).fetchone() is None:
        liked_condition = "liked_at IS NOT NULL OR " if "liked_at" in movie_columns else ""
        db.execute(
            f"""UPDATE movies SET state = CASE
                WHEN {liked_condition}NOT EXISTS (
                    SELECT 1 FROM movie_watch_history h WHERE h.movie_id = movies.id
                ) THEN 'ACTIVE'
                ELSE 'ARCHIVED'
            END"""
        )
        db.execute(
            "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
            (migration_name, datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )
    db.execute("PRAGMA optimize")
    db.commit()
