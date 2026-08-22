from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}


def _remove_watchlist(db: sqlite3.Connection) -> None:
    show_columns = _columns(db, "shows")
    if "watchlist_at" not in show_columns:
        return

    db.commit()
    db.execute("PRAGMA foreign_keys = OFF")
    try:
        db.executescript(
            """
            BEGIN IMMEDIATE;
            CREATE TABLE shows_migrated (
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
                added_at TEXT NOT NULL,
                watching_at TEXT,
                archived_at TEXT,
                updated_at TEXT,
                tmdb_refreshed_at TEXT,
                tmdb_payload TEXT NOT NULL DEFAULT '{}'
            );

            INSERT INTO shows_migrated (
                id, tmdb_id, name, original_name, overview, tagline, poster_path,
                backdrop_path, first_air_date, status, genres, original_language,
                state, added_at, watching_at, archived_at, updated_at
            )
            SELECT id, tmdb_id, name, original_name, overview, tagline, poster_path,
                   backdrop_path, first_air_date, status, genres, original_language,
                   CASE WHEN state IN ('WATCHLIST', 'ACTIVE') THEN 'WATCHING' ELSE state END,
                   added_at,
                   CASE WHEN state = 'WATCHLIST'
                        THEN COALESCE(active_at, watchlist_at, added_at)
                        ELSE active_at END,
                   archived_at, updated_at
            FROM shows;

            CREATE TABLE show_state_history_migrated (
                id INTEGER PRIMARY KEY,
                show_id INTEGER NOT NULL REFERENCES shows(id) ON DELETE CASCADE,
                state TEXT NOT NULL CHECK (state IN ('WATCHING', 'ARCHIVED')),
                entered_at TEXT NOT NULL
            );

            INSERT INTO show_state_history_migrated (id, show_id, state, entered_at)
            SELECT id, show_id,
                   CASE WHEN state IN ('WATCHLIST', 'ACTIVE') THEN 'WATCHING' ELSE state END,
                   entered_at
            FROM show_state_history;

            DROP TABLE show_state_history;
            DROP TABLE shows;
            ALTER TABLE shows_migrated RENAME TO shows;
            ALTER TABLE show_state_history_migrated RENAME TO show_state_history;
            COMMIT;
            """
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.execute("PRAGMA foreign_keys = ON")


def _add_tmdb_metadata(db: sqlite3.Connection) -> None:
    additions = {
        "shows": {
            "tmdb_refreshed_at": "TEXT",
            "tmdb_payload": "TEXT NOT NULL DEFAULT '{}'",
        },
        "seasons": {
            "is_progress_counted": (
                "INTEGER NOT NULL DEFAULT 1 CHECK (is_progress_counted IN (0, 1))"
            ),
            "tmdb_payload": "TEXT NOT NULL DEFAULT '{}'",
        },
        "episodes": {"tmdb_payload": "TEXT NOT NULL DEFAULT '{}'"},
    }
    for table, definitions in additions.items():
        existing = _columns(db, table)
        for column, definition in definitions.items():
            if column not in existing:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    db.execute("UPDATE seasons SET is_progress_counted = 0 WHERE season_number <= 0")


def _add_tracking_flag(db: sqlite3.Connection) -> None:
    if "is_tracked" not in _columns(db, "shows"):
        db.execute(
            """
            ALTER TABLE shows
            ADD COLUMN is_tracked INTEGER NOT NULL DEFAULT 1
                CHECK (is_tracked IN (0, 1))
            """
        )


def _rename_active_to_watching(db: sqlite3.Connection) -> None:
    columns = _columns(db, "shows")
    show_sql = db.execute(
        "SELECT sql FROM sqlite_schema WHERE type = 'table' AND name = 'shows'"
    ).fetchone()[0]
    if "active_at" in columns and "'WATCHING'" not in show_sql:
        return
    if "watching_at" in columns and "'ACTIVE'" not in show_sql:
        return

    timestamp_source = "watching_at" if "watching_at" in columns else "active_at"
    db.commit()
    db.execute("PRAGMA foreign_keys = OFF")
    try:
        db.executescript(
            f"""
            BEGIN IMMEDIATE;
            CREATE TABLE shows_watching_migrated (
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
                tmdb_payload TEXT NOT NULL DEFAULT '{{}}'
            );

            INSERT INTO shows_watching_migrated (
                id, tmdb_id, name, original_name, overview, tagline, poster_path,
                backdrop_path, first_air_date, status, genres, original_language,
                state, is_tracked, added_at, watching_at, archived_at, updated_at,
                tmdb_refreshed_at, tmdb_payload
            )
            SELECT id, tmdb_id, name, original_name, overview, tagline, poster_path,
                   backdrop_path, first_air_date, status, genres, original_language,
                   CASE state WHEN 'ACTIVE' THEN 'WATCHING' ELSE state END,
                   is_tracked, added_at, {timestamp_source}, archived_at, updated_at,
                   tmdb_refreshed_at, tmdb_payload
            FROM shows;

            CREATE TABLE show_state_history_watching_migrated (
                id INTEGER PRIMARY KEY,
                show_id INTEGER NOT NULL REFERENCES shows(id) ON DELETE CASCADE,
                state TEXT NOT NULL CHECK (state IN ('WATCHING', 'ARCHIVED')),
                entered_at TEXT NOT NULL
            );

            INSERT INTO show_state_history_watching_migrated (id, show_id, state, entered_at)
            SELECT id, show_id,
                   CASE state WHEN 'ACTIVE' THEN 'WATCHING' ELSE state END,
                   entered_at
            FROM show_state_history;

            DROP TABLE show_state_history;
            DROP TABLE shows;
            ALTER TABLE shows_watching_migrated RENAME TO shows;
            ALTER TABLE show_state_history_watching_migrated RENAME TO show_state_history;
            COMMIT;
            """
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.execute("PRAGMA foreign_keys = ON")


def _add_image_cache(db: sqlite3.Connection) -> None:
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS image_cache (
            id INTEGER PRIMARY KEY,
            tmdb_path TEXT NOT NULL,
            image_type TEXT NOT NULL,
            size TEXT NOT NULL,
            local_filename TEXT NOT NULL,
            content_type TEXT NOT NULL,
            downloaded_at TEXT NOT NULL,
            UNIQUE (tmdb_path, image_type, size)
        )
        """
    )


def _rename_watching_to_active(db: sqlite3.Connection) -> None:
    columns = _columns(db, "shows")
    show_sql = db.execute(
        "SELECT sql FROM sqlite_schema WHERE type = 'table' AND name = 'shows'"
    ).fetchone()[0]
    if "active_at" in columns and "'WATCHING'" not in show_sql:
        return

    timestamp_source = "active_at" if "active_at" in columns else "watching_at"
    db.commit()
    db.execute("PRAGMA foreign_keys = OFF")
    try:
        db.executescript(
            f"""
            BEGIN IMMEDIATE;
            CREATE TABLE shows_active_migrated (
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
                state TEXT NOT NULL CHECK (state IN ('ACTIVE', 'ARCHIVED')),
                is_tracked INTEGER NOT NULL DEFAULT 1 CHECK (is_tracked IN (0, 1)),
                added_at TEXT NOT NULL,
                active_at TEXT,
                archived_at TEXT,
                updated_at TEXT,
                tmdb_refreshed_at TEXT,
                tmdb_payload TEXT NOT NULL DEFAULT '{{}}'
            );

            INSERT INTO shows_active_migrated (
                id, tmdb_id, name, original_name, overview, tagline, poster_path,
                backdrop_path, first_air_date, status, genres, original_language,
                state, is_tracked, added_at, active_at, archived_at, updated_at,
                tmdb_refreshed_at, tmdb_payload
            )
            SELECT id, tmdb_id, name, original_name, overview, tagline, poster_path,
                   backdrop_path, first_air_date, status, genres, original_language,
                   CASE state WHEN 'WATCHING' THEN 'ACTIVE' ELSE state END,
                   is_tracked, added_at, {timestamp_source}, archived_at, updated_at,
                   tmdb_refreshed_at, tmdb_payload
            FROM shows;

            CREATE TABLE show_state_history_active_migrated (
                id INTEGER PRIMARY KEY,
                show_id INTEGER NOT NULL REFERENCES shows(id) ON DELETE CASCADE,
                state TEXT NOT NULL CHECK (state IN ('ACTIVE', 'ARCHIVED')),
                entered_at TEXT NOT NULL
            );

            INSERT INTO show_state_history_active_migrated (id, show_id, state, entered_at)
            SELECT id, show_id,
                   CASE state WHEN 'WATCHING' THEN 'ACTIVE' ELSE state END,
                   entered_at
            FROM show_state_history;

            DROP TABLE show_state_history;
            DROP TABLE shows;
            ALTER TABLE shows_active_migrated RENAME TO shows;
            ALTER TABLE show_state_history_active_migrated RENAME TO show_state_history;
            COMMIT;
            """
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.execute("PRAGMA foreign_keys = ON")


def _migrate_watch_history_tables(db: sqlite3.Connection) -> None:
    table_definitions = {
        "episode_watch_history": ("episode_id", "episodes"),
        "season_watch_history": ("season_id", "seasons"),
    }
    for table, (parent_column, parent_table) in table_definitions.items():
        exists = db.execute(
            "SELECT 1 FROM sqlite_schema WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        if exists is None:
            continue
        columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
        if {"added_at", "watch_date"}.issubset(columns) and not {
            "watched_at",
            "unwatched_at",
        }.intersection(columns):
            continue

        legacy_table = f"{table}_legacy"
        db.execute(f"ALTER TABLE {table} RENAME TO {legacy_table}")
        db.execute(
            f"""
            CREATE TABLE {table} (
                id INTEGER PRIMARY KEY,
                {parent_column} INTEGER NOT NULL
                    REFERENCES {parent_table}(id) ON DELETE CASCADE,
                added_at TEXT NOT NULL,
                watch_date TEXT
            )
            """
        )
        added_source = "added_at" if "added_at" in columns else "watched_at"
        date_source = "watch_date" if "watch_date" in columns else "NULL"
        active_filter = "WHERE unwatched_at IS NULL" if "unwatched_at" in columns else ""
        db.execute(
            f"""
            INSERT INTO {table} (id, {parent_column}, added_at, watch_date)
            SELECT id, {parent_column}, {added_source}, {date_source}
            FROM {legacy_table}
            {active_filter}
            """
        )
        db.execute(f"DROP TABLE {legacy_table}")


def migrate_database(db: sqlite3.Connection) -> None:
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    migrations = (
        (1, _remove_watchlist),
        (2, _add_tmdb_metadata),
        (3, _add_tracking_flag),
        (4, _rename_active_to_watching),
        (5, _add_image_cache),
        (6, _rename_watching_to_active),
        (7, _migrate_watch_history_tables),
    )
    applied = {
        row[0] for row in db.execute("SELECT version FROM schema_migrations")
    }
    for version, migration in migrations:
        if version in applied:
            continue
        migration(db)
        db.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (version, _now()),
        )
        db.commit()
