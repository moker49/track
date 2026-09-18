from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def replace_media_cast(
    db: sqlite3.Connection,
    *,
    media_type: str,
    media_id: int,
    credits: dict,
) -> int:
    """Replace one local media item's TMDB cast credits atomically."""
    if media_type not in {"show", "movie"}:
        raise ValueError("media_type must be show or movie")
    cast_table = "show_cast" if media_type == "show" else "movie_cast"
    media_column = "show_id" if media_type == "show" else "movie_id"
    refreshed_at = _now()
    seen: set[tuple[int, str | None]] = set()
    saved = 0

    try:
        db.execute("BEGIN")
        db.execute(f"DELETE FROM {cast_table} WHERE {media_column} = ?", (media_id,))
        for position, credit in enumerate(credits.get("cast", [])):
            person_id = credit.get("id")
            name = credit.get("name")
            if not isinstance(person_id, int) or not isinstance(name, str) or not name.strip():
                continue
            character_name = credit.get("character")
            if not isinstance(character_name, str) or not character_name.strip():
                character_name = None
            unique_credit = (person_id, character_name)
            if unique_credit in seen:
                continue
            seen.add(unique_credit)
            cast_order = credit.get("order")
            if not isinstance(cast_order, int):
                cast_order = position
            db.execute(
                """
                INSERT INTO actors (tmdb_person_id, name, profile_path, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(tmdb_person_id) DO UPDATE SET
                    name = excluded.name,
                    profile_path = excluded.profile_path,
                    updated_at = excluded.updated_at
                """,
                (person_id, name.strip(), credit.get("profile_path"), refreshed_at),
            )
            actor_id = db.execute(
                "SELECT id FROM actors WHERE tmdb_person_id = ?", (person_id,)
            ).fetchone()[0]
            db.execute(
                f"""
                INSERT INTO {cast_table} ({media_column}, actor_id, character_name, cast_order)
                VALUES (?, ?, ?, ?)
                """,
                (media_id, actor_id, character_name, cast_order),
            )
            saved += 1
        db.commit()
    except Exception:
        db.rollback()
        raise
    return saved
