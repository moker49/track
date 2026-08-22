from __future__ import annotations

import sqlite3
from pathlib import Path

from migrations import migrate_database


def connect_database(path: str | Path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def initialize_database(db: sqlite3.Connection, schema_path: str | Path) -> None:
    schema = Path(schema_path).read_text(encoding="utf-8")
    has_application_schema = db.execute(
        "SELECT 1 FROM sqlite_schema WHERE type = 'table' AND name = 'shows'"
    ).fetchone() is not None

    if not has_application_schema:
        db.executescript(schema)
    migrate_database(db)
    if has_application_schema:
        # Migrations that rebuild SQLite tables also remove their indexes.
        # Reapplying the idempotent canonical schema restores those definitions.
        db.executescript(schema)
    db.execute("PRAGMA optimize")
