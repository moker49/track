from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone


VALID_STATES = {"ACTIVE", "ARCHIVED"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _required_id(payload: dict, label: str) -> int:
    value = payload.get("id")
    if not isinstance(value, int):
        raise ValueError(f"{label} is missing a TMDB id")
    return value


def _genres(payload: dict) -> str:
    return ", ".join(
        genre["name"] for genre in payload.get("genres", []) if genre.get("name")
    )


def import_or_refresh_show(
    db: sqlite3.Connection,
    show: dict,
    seasons: list[dict],
    target_state: str,
    refreshed_at: str | None = None,
) -> tuple[int, bool]:
    if target_state not in VALID_STATES:
        raise ValueError("target_state must be ACTIVE or ARCHIVED")
    tmdb_id = _required_id(show, "show")
    refreshed_at = refreshed_at or _now()
    existing = db.execute(
        "SELECT id, state FROM shows WHERE tmdb_id = ?", (tmdb_id,)
    ).fetchone()

    try:
        db.execute("BEGIN")
        if existing is None:
            cursor = db.execute(
                """
                INSERT INTO shows (
                    tmdb_id, name, original_name, overview, tagline, poster_path,
                    backdrop_path, first_air_date, status, genres,
                    original_language, state, added_at, active_at, archived_at,
                    updated_at, tmdb_refreshed_at, tmdb_payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tmdb_id,
                    show.get("name") or show.get("original_name") or "Untitled show",
                    show.get("original_name"),
                    show.get("overview"),
                    show.get("tagline"),
                    show.get("poster_path"),
                    show.get("backdrop_path"),
                    show.get("first_air_date"),
                    show.get("status"),
                    _genres(show),
                    show.get("original_language"),
                    target_state,
                    refreshed_at,
                    refreshed_at if target_state == "ACTIVE" else None,
                    refreshed_at if target_state == "ARCHIVED" else None,
                    refreshed_at,
                    refreshed_at,
                    json.dumps(show, separators=(",", ":")),
                ),
            )
            show_id = cursor.lastrowid
            db.execute(
                "INSERT INTO show_state_history (show_id, state, entered_at) VALUES (?, ?, ?)",
                (show_id, target_state, refreshed_at),
            )
            created = True
        else:
            show_id = existing["id"]
            db.execute(
                """
                UPDATE shows
                SET name = ?, original_name = ?, overview = ?, tagline = ?,
                    poster_path = ?, backdrop_path = ?, first_air_date = ?,
                    status = ?, genres = ?, original_language = ?, updated_at = ?,
                    tmdb_refreshed_at = ?, tmdb_payload = ?
                WHERE id = ?
                """,
                (
                    show.get("name") or show.get("original_name") or "Untitled show",
                    show.get("original_name"),
                    show.get("overview"),
                    show.get("tagline"),
                    show.get("poster_path"),
                    show.get("backdrop_path"),
                    show.get("first_air_date"),
                    show.get("status"),
                    _genres(show),
                    show.get("original_language"),
                    refreshed_at,
                    refreshed_at,
                    json.dumps(show, separators=(",", ":")),
                    show_id,
                ),
            )
            created = False

        for season in seasons:
            season_tmdb_id = _required_id(season, "season")
            season_number = season.get("season_number")
            if not isinstance(season_number, int):
                raise ValueError("season is missing a season number")
            progress_counted = int(season_number > 0 and not season.get("is_special", False))
            db.execute(
                """
                INSERT INTO seasons (
                    show_id, tmdb_id, season_number, name, overview, air_date,
                    poster_path, episode_count, is_progress_counted, tmdb_payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tmdb_id) DO UPDATE SET
                    show_id = excluded.show_id,
                    season_number = excluded.season_number,
                    name = excluded.name,
                    overview = excluded.overview,
                    air_date = excluded.air_date,
                    poster_path = excluded.poster_path,
                    episode_count = excluded.episode_count,
                    is_progress_counted = excluded.is_progress_counted,
                    tmdb_payload = excluded.tmdb_payload
                """,
                (
                    show_id,
                    season_tmdb_id,
                    season_number,
                    season.get("name") or f"Season {season_number}",
                    season.get("overview"),
                    season.get("air_date"),
                    season.get("poster_path"),
                    len(season.get("episodes", [])),
                    progress_counted,
                    json.dumps(season, separators=(",", ":")),
                ),
            )
            season_id = db.execute(
                "SELECT id FROM seasons WHERE tmdb_id = ?", (season_tmdb_id,)
            ).fetchone()[0]

            for episode in season.get("episodes", []):
                episode_tmdb_id = _required_id(episode, "episode")
                episode_number = episode.get("episode_number")
                if not isinstance(episode_number, int):
                    raise ValueError("episode is missing an episode number")
                runtime = episode.get("runtime")
                db.execute(
                    """
                    INSERT INTO episodes (
                        season_id, tmdb_id, episode_number, name, overview,
                        air_date, runtime_minutes, still_path, tmdb_payload
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(tmdb_id) DO UPDATE SET
                        season_id = excluded.season_id,
                        episode_number = excluded.episode_number,
                        name = excluded.name,
                        overview = excluded.overview,
                        air_date = excluded.air_date,
                        runtime_minutes = excluded.runtime_minutes,
                        still_path = excluded.still_path,
                        tmdb_payload = excluded.tmdb_payload
                    """,
                    (
                        season_id,
                        episode_tmdb_id,
                        episode_number,
                        episode.get("name") or f"Episode {episode_number}",
                        episode.get("overview"),
                        episode.get("air_date"),
                        runtime,
                        episode.get("still_path"),
                        json.dumps(episode, separators=(",", ":")),
                    ),
                )
        db.commit()
        return show_id, created
    except Exception:
        db.rollback()
        raise
