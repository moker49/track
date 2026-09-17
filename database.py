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


def normalize_unknown_log_timestamps(db: sqlite3.Connection) -> int:
    """Keep hidden/unknown logs immediately after their media's add event."""
    sources = (
        (
            "episode_watch_history",
            "added_at",
            """
            SELECT h.id, s.added_at AS media_added_at
            FROM episode_watch_history h
            JOIN episodes e ON e.id = h.episode_id
            JOIN seasons sn ON sn.id = e.season_id
            JOIN shows s ON s.id = sn.show_id
            WHERE h.diary_date IS NULL
            """,
        ),
        (
            "episode_skips",
            "skipped_at",
            """
            SELECT h.id, s.added_at AS media_added_at
            FROM episode_skips h
            JOIN episodes e ON e.id = h.episode_id
            JOIN seasons sn ON sn.id = e.season_id
            JOIN shows s ON s.id = sn.show_id
            WHERE h.diary_date IS NULL
            """,
        ),
        (
            "season_watch_history",
            "added_at",
            """
            SELECT h.id, s.added_at AS media_added_at
            FROM season_watch_history h
            JOIN seasons sn ON sn.id = h.season_id
            JOIN shows s ON s.id = sn.show_id
            WHERE h.diary_date IS NULL
            """,
        ),
        (
            "season_skip_history",
            "added_at",
            """
            SELECT h.id, s.added_at AS media_added_at
            FROM season_skip_history h
            JOIN seasons sn ON sn.id = h.season_id
            JOIN shows s ON s.id = sn.show_id
            WHERE h.diary_date IS NULL
            """,
        ),
        (
            "movie_watch_history",
            "added_at",
            """
            SELECT h.id, m.added_at AS media_added_at
            FROM movie_watch_history h
            JOIN movies m ON m.id = h.movie_id
            WHERE h.diary_date IS NULL
            """,
        ),
    )
    changed = 0
    for table, timestamp_column, source in sources:
        rows = db.execute(source).fetchall()
        db.executemany(
            f"UPDATE {table} SET {timestamp_column} = ? WHERE id = ?",
            [(unknown_log_timestamp(row["media_added_at"]), row["id"]) for row in rows],
        )
        changed += len(rows)
    return changed


def initialize_database(db: sqlite3.Connection, schema_path: str | Path) -> None:
    schema = Path(schema_path).read_text(encoding="utf-8")
    db.executescript(schema)
    normalize_unknown_log_timestamps(db)
    db.execute("PRAGMA optimize")
    db.commit()
