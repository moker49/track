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


def initialize_database(db: sqlite3.Connection, schema_path: str | Path) -> None:
    schema = Path(schema_path).read_text(encoding="utf-8")
    db.executescript(schema)
    migrate_liked_at(db)
    db.execute("PRAGMA optimize")
    db.commit()


def migrate_liked_at(db: sqlite3.Connection) -> None:
    """Replace the legacy liked boolean with the timestamp used for sorting."""
    for table in ("shows", "movies"):
        columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
        if "liked_at" not in columns:
            db.execute(f"ALTER TABLE {table} ADD COLUMN liked_at TEXT")
        if "liked" not in columns:
            continue
        if table == "shows":
            db.execute(
                """
                UPDATE shows
                SET liked_at = COALESCE(
                    liked_at,
                    (SELECT MIN(wh.added_at)
                     FROM episode_watch_history wh
                     JOIN episodes e ON e.id = wh.episode_id
                     JOIN seasons sn ON sn.id = e.season_id
                     WHERE sn.show_id = shows.id),
                    added_at
                )
                WHERE liked = 1
                """
            )
        else:
            db.execute(
                """
                UPDATE movies
                SET liked_at = COALESCE(
                    liked_at,
                    (SELECT MIN(added_at)
                     FROM movie_watch_history
                     WHERE movie_id = movies.id),
                    added_at
                )
                WHERE liked = 1
                """
            )
        db.execute(f"ALTER TABLE {table} DROP COLUMN liked")
