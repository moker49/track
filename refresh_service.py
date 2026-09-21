from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta

from queries import get_library_show
from tmdb import TMDBError
from tmdb_import import import_or_refresh_show, refresh_movie_metadata


def _failure_table(media_type: str) -> tuple[str, str]:
    if media_type == "show":
        return "show_metadata_refresh_failures", "show_id"
    if media_type == "movie":
        return "movie_metadata_refresh_failures", "movie_id"
    raise ValueError(f"Unsupported media type: {media_type}")


def next_refresh_retry_after(
    attempted_at: str,
    failure_count: int,
    retry_delays: tuple[timedelta, ...],
) -> str:
    if not retry_delays:
        raise ValueError("retry_delays must not be empty")
    delay_index = min(max(0, failure_count - 1), len(retry_delays) - 1)
    return (datetime.fromisoformat(attempted_at) + retry_delays[delay_index]).isoformat(
        timespec="seconds"
    )


def refresh_retry_after(db: sqlite3.Connection, media_type: str, media_id: int) -> str | None:
    table, id_column = _failure_table(media_type)
    row = db.execute(
        f"SELECT retry_after FROM {table} WHERE {id_column} = ?",
        (media_id,),
    ).fetchone()
    return row["retry_after"] if row is not None else None


def record_refresh_failure(
    db: sqlite3.Connection,
    media_type: str,
    media_id: int,
    error: str,
    *,
    attempted_at: str,
    retry_delays: tuple[timedelta, ...],
) -> str:
    table, id_column = _failure_table(media_type)
    row = db.execute(
        f"SELECT failure_count FROM {table} WHERE {id_column} = ?",
        (media_id,),
    ).fetchone()
    failure_count = (row["failure_count"] if row is not None else 0) + 1
    retry_after = next_refresh_retry_after(attempted_at, failure_count, retry_delays)
    db.execute(
        f"""
        INSERT INTO {table} (
            {id_column}, failure_count, last_attempt_at, retry_after, error
        ) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT({id_column}) DO UPDATE SET
            failure_count = excluded.failure_count,
            last_attempt_at = excluded.last_attempt_at,
            retry_after = excluded.retry_after,
            error = excluded.error
        """,
        (media_id, failure_count, attempted_at, retry_after, error),
    )
    db.commit()
    return retry_after


def clear_refresh_failure(db: sqlite3.Connection, media_type: str, media_id: int) -> None:
    table, id_column = _failure_table(media_type)
    db.execute(f"DELETE FROM {table} WHERE {id_column} = ?", (media_id,))
    db.commit()


def refresh_stale_tracked_shows(
    db: sqlite3.Connection,
    *,
    client_factory: Callable,
    metadata_is_fresh: Callable[[str | None], bool],
    attempted_at: str,
    retry_delays: tuple[timedelta, ...],
    include_card_html: bool = False,
    render_card: Callable[[sqlite3.Row], str] | None = None,
) -> dict:
    tracked_show_count = db.execute(
        "SELECT COUNT(*) FROM shows WHERE is_tracked = 1"
    ).fetchone()[0]
    tracked_shows = db.execute(
        """
        SELECT s.id, s.tmdb_id, s.state, s.tmdb_refreshed_at
        FROM shows s
        LEFT JOIN show_metadata_refresh_failures f ON f.show_id = s.id
        WHERE s.is_tracked = 1
          AND LOWER(TRIM(COALESCE(s.status, ''))) != 'ended'
          AND (f.retry_after IS NULL OR f.retry_after <= ?)
        ORDER BY s.tmdb_refreshed_at IS NOT NULL, s.tmdb_refreshed_at ASC, s.id ASC
        """,
        (attempted_at,),
    ).fetchall()
    stale_shows = [
        show
        for show in tracked_shows
        if not metadata_is_fresh(show["tmdb_refreshed_at"])
    ]
    refreshed_shows = []
    failures = []
    client = client_factory() if stale_shows else None

    for local_show in stale_shows:
        try:
            show, seasons = client.show_bundle(local_show["tmdb_id"])
            if show.get("id") != local_show["tmdb_id"]:
                raise TMDBError("TMDB returned the wrong show")
            refreshed_id, _created, _newly_tracked = import_or_refresh_show(
                db, show, seasons, local_show["state"]
            )
            clear_refresh_failure(db, "show", refreshed_id)
            refreshed_show = get_library_show(db, refreshed_id)
            result = {
                "show_id": refreshed_id,
                "refreshed_at": refreshed_show["tmdb_refreshed_at"],
            }
            if include_card_html and render_card is not None:
                result["card_html"] = render_card(refreshed_show)
            refreshed_shows.append(result)
        except (TMDBError, ValueError, sqlite3.Error) as error:
            retry_after = record_refresh_failure(
                db,
                "show",
                local_show["id"],
                str(error),
                attempted_at=attempted_at,
                retry_delays=retry_delays,
            )
            failures.append(
                {
                    "show_id": local_show["id"],
                    "error": str(error),
                    "retry_after": retry_after,
                }
            )

    return {
        "refreshed": refreshed_shows,
        "failures": failures,
        "skipped": tracked_show_count - len(stale_shows),
    }


def refresh_stale_tracked_movies(
    db: sqlite3.Connection,
    *,
    client_factory: Callable,
    metadata_is_fresh: Callable[[str | None], bool],
    movie_is_refreshable: Callable[[str | None], bool],
    attempted_at: str,
    retry_delays: tuple[timedelta, ...],
) -> dict:
    tracked_movie_count = db.execute(
        "SELECT COUNT(*) FROM movies WHERE is_tracked = 1"
    ).fetchone()[0]
    tracked_movies = db.execute(
        """
        SELECT m.id, m.tmdb_id, m.release_date, m.tmdb_refreshed_at
        FROM movies m
        LEFT JOIN movie_metadata_refresh_failures f ON f.movie_id = m.id
        WHERE m.is_tracked = 1
          AND (f.retry_after IS NULL OR f.retry_after <= ?)
        ORDER BY m.tmdb_refreshed_at IS NOT NULL, m.tmdb_refreshed_at ASC, m.id ASC
        """,
        (attempted_at,),
    ).fetchall()
    stale_movies = [
        movie
        for movie in tracked_movies
        if not metadata_is_fresh(movie["tmdb_refreshed_at"])
        and movie_is_refreshable(movie["release_date"])
    ]
    refreshed_movies = []
    failures = []
    client = client_factory() if stale_movies else None

    for local_movie in stale_movies:
        try:
            movie = client.movie(local_movie["tmdb_id"])
            if movie.get("id") != local_movie["tmdb_id"]:
                raise TMDBError("TMDB returned the wrong movie")
            refreshed_at = refresh_movie_metadata(db, local_movie["id"], movie)
            clear_refresh_failure(db, "movie", local_movie["id"])
            refreshed_movies.append(
                {"movie_id": local_movie["id"], "refreshed_at": refreshed_at}
            )
        except (TMDBError, ValueError, sqlite3.Error) as error:
            retry_after = record_refresh_failure(
                db,
                "movie",
                local_movie["id"],
                str(error),
                attempted_at=attempted_at,
                retry_delays=retry_delays,
            )
            failures.append(
                {
                    "movie_id": local_movie["id"],
                    "error": str(error),
                    "retry_after": retry_after,
                }
            )

    return {
        "refreshed": refreshed_movies,
        "failures": failures,
        "skipped": tracked_movie_count - len(stale_movies),
    }
