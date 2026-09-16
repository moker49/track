from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from datetime import date, timedelta

from domain import (
    PROGRESS_FINISHED,
    TRACKING_ACTIVE,
    TRACKING_ARCHIVED,
    effective_diary_date_sql,
    progress_presentation,
)


def natural_title_key(value: str) -> tuple:
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in re.split(r"(\d+)", value)
        if part
    )


def get_show_progress(db: sqlite3.Connection, show_id: int) -> sqlite3.Row:
    return db.execute(
        """
        WITH episode_counts AS (
            SELECT e.id,
                   (SELECT COUNT(*) FROM episode_watch_history wh WHERE wh.episode_id = e.id)
                   + (SELECT COUNT(*) FROM episode_skips sk WHERE sk.episode_id = e.id) AS watch_count
            FROM seasons sn
            JOIN episodes e ON e.season_id = sn.id AND e.air_date <= date('now')
            WHERE sn.show_id = ? AND sn.is_progress_counted = 1
        )
        SELECT COUNT(*) AS episode_count,
               COALESCE(SUM(CASE WHEN watch_count > 0 THEN 1 ELSE 0 END), 0) AS watched_count,
               COALESCE(SUM(watch_count), 0) AS total_watch_count,
               COALESCE(MIN(watch_count), 0) AS completed_watch_count
        FROM episode_counts
        """,
        (show_id,),
    ).fetchone()


def get_episode_watch_count(db: sqlite3.Connection, episode_id: int) -> int:
    return db.execute(
        """
        SELECT (SELECT COUNT(*) FROM episode_watch_history WHERE episode_id = ?)
             + (SELECT COUNT(*) FROM episode_skips WHERE episode_id = ?)
        """,
        (episode_id, episode_id),
    ).fetchone()[0]


def watch_payload(
    db: sqlite3.Connection,
    show_id: int,
    episode_id: int | None = None,
    previous_watched_count: int | None = None,
) -> dict:
    progress = get_show_progress(db, show_id)
    episode_count = progress["episode_count"]
    watched_count = progress["watched_count"]
    show = db.execute(
        "SELECT name, state, status FROM shows WHERE id = ?",
        (show_id,),
    ).fetchone()
    presentation = progress_presentation(
        show["state"], watched_count, episode_count, show["status"]
    )
    payload = {
        "show_id": show_id,
        "show_name": show["name"],
        "tracking_state": show["state"],
        "show_status": show["status"],
        "progress_state": presentation.state,
        "watched_count": watched_count,
        "episode_count": episode_count,
        "total_watch_count": progress["total_watch_count"],
        "completed_watch_count": progress["completed_watch_count"],
        "percent": round(watched_count / episode_count * 100) if episode_count else 0,
        "last_watched_at": db.execute(
            """
            SELECT MAX(wh.diary_date)
            FROM episode_watch_history wh
            JOIN episodes e ON e.id = wh.episode_id
            JOIN seasons sn ON sn.id = e.season_id
            WHERE sn.show_id = ?
            """,
            (show_id,),
        ).fetchone()[0],
        "latest_resolution_kind": db.execute(
            """
            SELECT COALESCE((
                SELECT resolution_kind FROM (
                    SELECT 'watch' AS resolution_kind,
                           COALESCE(diary_date, substr(added_at, 1, 10)) AS resolved_at, id
                    FROM episode_watch_history WHERE episode_id = ?
                    UNION ALL
                    SELECT 'skip' AS resolution_kind, COALESCE(diary_date, substr(skipped_at, 1, 10)) AS resolved_at, id
                    FROM episode_skips WHERE episode_id = ?
                ) ORDER BY resolved_at DESC, id DESC LIMIT 1
            ), '')
            """,
            (episode_id, episode_id),
        ).fetchone()[0] if episode_id is not None else None,
        "became_finished": (
            previous_watched_count is not None
            and previous_watched_count < episode_count
            and watched_count >= episode_count
            and show["state"] == TRACKING_ACTIVE
            and presentation.state == PROGRESS_FINISHED
        ),
    }
    if episode_id is not None:
        count = get_episode_watch_count(db, episode_id)
        payload.update(episode_id=episode_id, watched=count > 0, watch_count=count)
    return payload


def get_library_show(
    db: sqlite3.Connection, show_id: int
) -> sqlite3.Row | None:
    return db.execute(
        """
        WITH episode_counts AS (
            SELECT e.id AS episode_id, sn.show_id,
                   (SELECT COUNT(*) FROM episode_watch_history wh WHERE wh.episode_id = e.id)
                   + (SELECT COUNT(*) FROM episode_skips sk WHERE sk.episode_id = e.id) AS watch_count,
                   MAX(wh.diary_date) AS last_watched_at
            FROM seasons sn
            JOIN episodes e ON e.season_id = sn.id
              AND sn.is_progress_counted = 1
              AND e.air_date <= date('now')
            LEFT JOIN episode_watch_history wh ON wh.episode_id = e.id
            GROUP BY e.id
        )
        SELECT s.*, COUNT(ec.episode_id) AS episode_count,
               COALESCE(SUM(CASE WHEN ec.watch_count > 0 THEN 1 ELSE 0 END), 0) AS watched_count,
               COALESCE(SUM(ec.watch_count), 0) AS total_watch_count,
               COALESCE(MIN(ec.watch_count), 0) AS completed_watch_count,
               MAX(ec.last_watched_at) AS last_watched_at
        FROM shows s
        LEFT JOIN episode_counts ec ON ec.show_id = s.id
        WHERE s.id = ?
        GROUP BY s.id
        """,
        (show_id,),
    ).fetchone()


def get_catch_up_episodes(
    db: sqlite3.Connection,
    show_id: int | None = None,
    local_date: date | None = None,
) -> list[sqlite3.Row | dict]:
    local_date = local_date or date.today()
    local_date_value = local_date.isoformat()
    episodes = db.execute(
        """
        WITH episode_counts AS (
            SELECT s.id AS show_id, s.name AS show_name, s.poster_path,
                   s.state AS tracking_state, s.added_at AS show_added_at,
                   s.status AS show_status, s.watch_again,
                   sn.season_number, sn.name AS season_name,
                   e.id AS episode_id, e.episode_number,
                   e.name AS episode_name, e.air_date, e.runtime_minutes,
                   (SELECT COUNT(*) FROM episode_watch_history wh WHERE wh.episode_id = e.id)
                   + (SELECT COUNT(*) FROM episode_skips sk WHERE sk.episode_id = e.id) AS watch_count,
                   (SELECT MAX(resolved_at) FROM (
                       SELECT wh.added_at AS resolved_at FROM episode_watch_history wh WHERE wh.episode_id = e.id
                       UNION ALL
                       SELECT sk.skipped_at AS resolved_at FROM episode_skips sk WHERE sk.episode_id = e.id
                   )) AS last_watch_added_at,
                   (SELECT MAX(wh.diary_date)
                    FROM episode_watch_history wh WHERE wh.episode_id = e.id) AS last_visible_watched_at
            FROM shows s
            JOIN seasons sn ON sn.show_id = s.id AND sn.is_progress_counted = 1
            JOIN episodes e ON e.season_id = sn.id
            WHERE s.is_tracked = 1
              AND e.air_date IS NOT NULL
              AND e.air_date <= ?
        ),
        show_progress_base AS (
            SELECT show_id,
                   COUNT(*) AS episode_count,
                   SUM(CASE WHEN watch_count > 0 THEN 1 ELSE 0 END) AS watched_count,
                   SUM(watch_count) AS total_watch_count,
                   MIN(watch_count) AS completed_watch_count,
                   MAX(last_visible_watched_at) AS last_watched_at
            FROM episode_counts
            GROUP BY show_id
        ),
        show_progress AS (
            SELECT progress.*,
                   SUM(CASE WHEN ec.watch_count > progress.completed_watch_count THEN 1 ELSE 0 END)
                       AS rewatch_watched_count
            FROM show_progress_base progress
            JOIN episode_counts ec ON ec.show_id = progress.show_id
            GROUP BY progress.show_id
        ),
        normal_unresolved AS (
            SELECT ec.*, ROW_NUMBER() OVER (
                PARTITION BY ec.show_id
                ORDER BY ec.air_date, ec.season_number, ec.episode_number
            ) AS episode_rank
            FROM episode_counts ec
            WHERE ec.watch_count = 0
        ),
        latest_rewatch AS (
            SELECT ec.*, ROW_NUMBER() OVER (
                PARTITION BY ec.show_id
                ORDER BY ec.last_watch_added_at DESC, ec.season_number DESC, ec.episode_number DESC
            ) AS rewatch_rank
            FROM episode_counts ec
            WHERE ec.watch_count > 1
        ),
        rewatch_candidates AS (
            SELECT next_episode.*, ROW_NUMBER() OVER (
                PARTITION BY latest_rewatch.show_id
                ORDER BY next_episode.season_number, next_episode.episode_number
            ) AS episode_rank
            FROM latest_rewatch
            JOIN episode_counts next_episode
              ON next_episode.show_id = latest_rewatch.show_id
             AND (next_episode.season_number > latest_rewatch.season_number
                  OR (next_episode.season_number = latest_rewatch.season_number
                      AND next_episode.episode_number > latest_rewatch.episode_number))
             AND next_episode.watch_count < latest_rewatch.watch_count
            WHERE latest_rewatch.rewatch_rank = 1
              AND NOT EXISTS (
                  SELECT 1 FROM normal_unresolved normal
                  WHERE normal.show_id = latest_rewatch.show_id
              )
        ),
        watch_again_candidates AS (
            SELECT ranked.* FROM (
                SELECT ec.*, ROW_NUMBER() OVER (
                    PARTITION BY ec.show_id
                    ORDER BY ec.watch_count, ec.season_number, ec.episode_number
                ) AS episode_rank
                FROM episode_counts ec
                WHERE ec.watch_again = 1
                  AND NOT EXISTS (
                      SELECT 1 FROM normal_unresolved normal WHERE normal.show_id = ec.show_id
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM rewatch_candidates rewatch WHERE rewatch.show_id = ec.show_id
                  )
            ) ranked
            WHERE ranked.episode_rank = 1
        ),
        unresolved AS (
            SELECT show_id, show_name, poster_path, tracking_state, show_added_at, show_status, watch_again,
                   season_number, season_name, episode_id, episode_number, episode_name,
                   air_date, runtime_minutes, 0 AS is_rewatch, 0 AS is_forced_queue
            FROM normal_unresolved
            WHERE episode_rank = 1
            UNION ALL
            SELECT show_id, show_name, poster_path, tracking_state, show_added_at, show_status, watch_again,
                   season_number, season_name, episode_id, episode_number, episode_name,
                   air_date, runtime_minutes, 1 AS is_rewatch, 0 AS is_forced_queue
            FROM rewatch_candidates
            WHERE episode_rank = 1
            UNION ALL
            SELECT show_id, show_name, poster_path, tracking_state, show_added_at, show_status, watch_again,
                   season_number, season_name, episode_id, episode_number, episode_name,
                   air_date, runtime_minutes, 1 AS is_rewatch, 1 AS is_forced_queue
            FROM watch_again_candidates
        )
        SELECT unresolved.*, show_progress.episode_count, show_progress.watched_count,
               show_progress.total_watch_count, show_progress.completed_watch_count,
               show_progress.rewatch_watched_count, show_progress.last_watched_at
        FROM unresolved
        JOIN show_progress ON show_progress.show_id = unresolved.show_id
        WHERE (? IS NULL OR unresolved.show_id = ?)
        ORDER BY show_progress.last_watched_at DESC,
                 unresolved.show_name COLLATE NOCASE
        """,
        (local_date_value, show_id, show_id),
    ).fetchall()
    if show_id is not None:
        return episodes

    watch_again_movies = db.execute(
        """
        SELECT NULL AS show_id, m.id AS movie_id, m.title AS show_name, m.poster_path,
               'ACTIVE' AS tracking_state, m.added_at AS show_added_at, m.status AS show_status,
               m.watch_again, NULL AS season_number, 'Movie' AS season_name,
               NULL AS episode_id, NULL AS episode_number, m.title AS episode_name,
               m.release_date AS air_date, m.runtime_minutes, 1 AS is_rewatch, 1 AS is_forced_queue,
               1 AS episode_count, 0 AS watched_count, 0 AS total_watch_count,
               0 AS completed_watch_count, 0 AS rewatch_watched_count,
               MAX(mwh.added_at) AS last_watched_at, 1 AS is_movie, 'movies' AS media_type
        FROM movies m
        LEFT JOIN movie_watch_history mwh ON mwh.movie_id = m.id
        WHERE m.is_tracked = 1 AND m.watch_again = 1
        GROUP BY m.id
        """
    ).fetchall()
    queue_items = [dict(episode) for episode in episodes]
    queue_items.extend(dict(movie) for movie in watch_again_movies)
    queue_items.sort(key=lambda item: item["show_name"].casefold())
    queue_items.sort(key=lambda item: item["last_watched_at"] or "", reverse=True)
    queue_items.sort(key=lambda item: item["is_forced_queue"])
    return queue_items


def get_upcoming_episodes(
    db: sqlite3.Connection, local_date: date | None = None
) -> list[dict]:
    local_date = local_date or date.today()
    local_date_value = local_date.isoformat()
    rows = db.execute(
        """
        WITH show_progress AS (
            SELECT s.id AS show_id,
                   COUNT(DISTINCT e.id) AS episode_count,
                   COUNT(DISTINCT CASE WHEN wh.id IS NOT NULL THEN e.id END) AS watched_count,
                   MAX(wh.diary_date) AS last_watched_at
            FROM shows s
            JOIN seasons sn ON sn.show_id = s.id AND sn.is_progress_counted = 1
            JOIN episodes e ON e.season_id = sn.id AND e.air_date <= ?
            LEFT JOIN episode_watch_history wh ON wh.episode_id = e.id
            WHERE s.is_tracked = 1
            GROUP BY s.id
        )
        SELECT s.id AS show_id, s.name AS show_name, s.poster_path,
               s.state AS tracking_state, s.added_at AS show_added_at,
               s.status AS show_status,
               COALESCE(sp.episode_count, 0) AS episode_count,
               COALESCE(sp.watched_count, 0) AS watched_count,
               sp.last_watched_at,
               sn.id AS season_id, sn.season_number, sn.name AS season_name,
               (SELECT COUNT(*) FROM episodes season_episode
                WHERE season_episode.season_id = sn.id) AS season_episode_count,
               e.id AS episode_id, e.episode_number,
               e.name AS episode_name, e.air_date, e.runtime_minutes
        FROM shows s
        LEFT JOIN show_progress sp ON sp.show_id = s.id
        JOIN seasons sn ON sn.show_id = s.id
        JOIN episodes e ON e.season_id = sn.id
        WHERE s.is_tracked = 1
          AND sn.is_progress_counted = 1
          AND e.air_date IS NOT NULL
          AND e.air_date >= date(?, '-7 days')
        ORDER BY e.air_date, s.name COLLATE NOCASE,
                 sn.season_number, e.episode_number
        """,
        (local_date_value, local_date_value),
    ).fetchall()
    today = local_date
    release_groups: dict[tuple[int, str, int], list[dict]] = {}
    for row in rows:
        episode = dict(row)
        release_groups.setdefault(
            (episode["show_id"], episode["air_date"], episode["season_id"]),
            [],
        ).append(episode)

    upcoming = []
    for episodes in release_groups.values():
        release = dict(episodes[0])
        air_date = date.fromisoformat(release["air_date"])
        season_ids = list(dict.fromkeys(episode["season_id"] for episode in episodes))
        is_grouped = len(episodes) > 1
        is_full_season = (
            is_grouped
            and len(episodes) == release["season_episode_count"]
        )
        if is_grouped:
            release_metadata = (
                f"Season {release['season_number']} · Episodes "
                f"{episodes[0]['episode_number']}–{episodes[-1]['episode_number']}"
            )
        else:
            release_metadata = (
                f"Season {release['season_number']} · Episode {release['episode_number']}"
            )
        release_detail = (
            "Full season"
            if is_full_season
            else f"{len(episodes)} episodes"
            if is_grouped
            else release["episode_name"]
        )
        release.update(
            media_type="tv",
            is_movie=False,
            month_key=air_date.strftime("%Y-%m"),
            month_label=(
                air_date.strftime("%B").upper()
                if air_date.year == today.year
                else air_date.strftime("%B %Y").upper()
            ),
            day_label=f"{air_date.day:02d}",
            weekday_label=air_date.strftime("%a").upper(),
            days_until=(air_date - today).days,
            is_live=air_date < today,
            is_grouped=is_grouped,
            season_ids=",".join(str(season_id) for season_id in season_ids),
            release_metadata=release_metadata,
            release_detail=release_detail,
            search_text=" ".join(
                [release["show_name"], *(episode["episode_name"] for episode in episodes)]
            ).lower(),
        )
        upcoming.append(release)
    movie_rows = db.execute(
        """
        SELECT id AS movie_id, title AS show_name, poster_path,
               'ACTIVE' AS tracking_state, added_at AS show_added_at,
               release_date AS air_date
        FROM movies
        WHERE is_tracked = 1
          AND release_date IS NOT NULL
          AND release_date >= date(?, '-7 days')
        ORDER BY release_date, title COLLATE NOCASE
        """,
        (local_date_value,),
    ).fetchall()
    for row in movie_rows:
        movie = dict(row)
        release_date = date.fromisoformat(movie["air_date"])
        movie.update(
            media_type="movies",
            is_movie=True,
            is_grouped=False,
            month_key=release_date.strftime("%Y-%m"),
            month_label=(
                release_date.strftime("%B").upper()
                if release_date.year == today.year
                else release_date.strftime("%B %Y").upper()
            ),
            day_label=f"{release_date.day:02d}",
            weekday_label=release_date.strftime("%a").upper(),
            days_until=(release_date - today).days,
            is_live=release_date < today,
            release_metadata="Movie",
            release_detail=release_date.strftime("%Y"),
            search_text=movie["show_name"].lower(),
            show_status="",
            watched_count=0,
            episode_count=0,
            last_watched_at=None,
        )
        upcoming.append(movie)
    return sorted(upcoming, key=lambda item: (item["air_date"], item["show_name"].casefold()))


def get_diary_page(
    db: sqlite3.Connection, page: int = 1, page_size: int | None = 50
) -> tuple[list[dict], bool]:
    pagination_sql = "LIMIT ? OFFSET ?" if page_size is not None else ""
    pagination_parameters = (
        (page_size + 1, (page - 1) * page_size)
        if page_size is not None
        else ()
    )
    effective_date = effective_diary_date_sql("wh")
    rows = db.execute(
        f"""
        WITH diary_watches AS (
            SELECT wh.id AS watch_record_id, wh.added_at, wh.diary_date,
                   {effective_date} AS watched_date,
                   s.id AS show_id, s.name AS show_name, s.poster_path,
                   sn.id AS season_id, sn.season_number,
                   e.id AS episode_id, e.episode_number,
                   ROW_NUMBER() OVER (
                       PARTITION BY e.id, {effective_date}
                       ORDER BY wh.added_at, wh.id
                   ) AS watch_iteration
            FROM episode_watch_history wh
            JOIN episodes e ON e.id = wh.episode_id
            JOIN seasons sn ON sn.id = e.season_id
            JOIN shows s ON s.id = sn.show_id
            WHERE wh.diary_date IS NOT NULL
        ),
        grouped_entries AS (
            SELECT 'episode' AS entry_type, watched_date, show_id,
                   MAX(show_name) AS show_name,
                   MAX(poster_path) AS poster_path,
                   season_id, MAX(season_number) AS season_number,
                   watch_iteration,
                   MIN(episode_id) AS episode_id,
                   MIN(episode_number) AS first_episode_number,
                   MAX(episode_number) AS last_episode_number,
                   COUNT(*) AS grouped_watch_count,
                   group_concat(
                       watch_record_id ORDER BY episode_number, watch_record_id
                   ) AS watch_record_ids,
                   MAX(added_at) AS latest_added_at,
                   MAX(watch_record_id) AS sort_watch_record_id
            FROM diary_watches
            GROUP BY watched_date, show_id, season_id, watch_iteration
        ),
        movie_entries AS (
            SELECT 'movie' AS entry_type,
                   {effective_diary_date_sql('mwh')} AS watched_date,
                   m.id AS show_id, m.title AS show_name, m.poster_path,
                   NULL AS season_id, NULL AS season_number, NULL AS watch_iteration,
                   NULL AS episode_id, NULL AS first_episode_number,
                   NULL AS last_episode_number, 1 AS grouped_watch_count,
                   CAST(mwh.id AS TEXT) AS watch_record_ids,
                   mwh.added_at AS latest_added_at, mwh.id AS sort_watch_record_id,
                   m.release_date
            FROM movie_watch_history mwh
            JOIN movies m ON m.id = mwh.movie_id
            WHERE mwh.diary_date IS NOT NULL
        )
        SELECT entry_type, watched_date, show_id, show_name, poster_path,
               season_id, season_number, watch_iteration, episode_id,
               first_episode_number, last_episode_number, grouped_watch_count,
               watch_record_ids, latest_added_at, sort_watch_record_id,
               NULL AS release_date
        FROM grouped_entries
        UNION ALL
        SELECT * FROM movie_entries
        ORDER BY watched_date DESC, latest_added_at DESC, sort_watch_record_id DESC
        {pagination_sql}
        """,
        pagination_parameters,
    ).fetchall()
    has_more = page_size is not None and len(rows) > page_size
    entries = []
    visible_rows = rows[:page_size] if page_size is not None else rows
    for row in visible_rows:
        entry = dict(row)
        watched_date = date.fromisoformat(entry["watched_date"])
        is_movie = entry["entry_type"] == "movie"
        is_grouped = not is_movie and entry["grouped_watch_count"] > 1
        release_metadata = (
            (entry["release_date"] or "")[:4]
            if is_movie
            else (
                f"Season {entry['season_number']} · Episodes "
                f"{entry['first_episode_number']}–{entry['last_episode_number']}"
                if is_grouped
                else f"Season {entry['season_number']} · Episode {entry['first_episode_number']}"
            )
        )
        entry.update(
            month_key=f"{9999 - watched_date.year:04d}-{13 - watched_date.month:02d}",
            month_label=watched_date.strftime("%B %Y").upper(),
            day_label=f"{watched_date.day:02d}",
            weekday_label=watched_date.strftime("%a").upper(),
            is_grouped=is_grouped,
            is_movie=is_movie,
            season_ids=str(entry["season_id"]),
            release_metadata=release_metadata,
        )
        entries.append(entry)
    return entries, has_more


def _format_duration(total_minutes: int) -> str:
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


def _format_stat_date(value: date, today: date) -> str:
    label = f"{value.strftime('%b')} {value.day}"
    return label if value.year == today.year else f"{label}, {value.year}"


def get_statistics(db: sqlite3.Connection, local_date: date | None = None) -> dict:
    today = local_date or date.today()
    effective_date = effective_diary_date_sql("wh")
    rows = [
        dict(row)
        for row in db.execute(
            f"""
            SELECT wh.id AS watch_record_id, {effective_date} AS watched_date,
                   s.id AS show_id, s.name AS show_name,
                   (
                       SELECT COUNT(*)
                       FROM episodes counted_episode
                       JOIN seasons counted_season ON counted_season.id = counted_episode.season_id
                       WHERE counted_season.show_id = s.id
                         AND counted_season.is_progress_counted = 1
                   ) AS episode_count,
                   sn.season_number, e.id AS episode_id,
                   e.episode_number, e.name AS episode_name,
                   COALESCE(e.runtime_minutes, 0) AS runtime_minutes
            FROM episode_watch_history wh
            JOIN episodes e ON e.id = wh.episode_id
            JOIN seasons sn ON sn.id = e.season_id
            JOIN shows s ON s.id = sn.show_id
            WHERE wh.diary_date IS NOT NULL
            ORDER BY watched_date, wh.added_at, wh.id
            """
        ).fetchall()
    ]
    movie_rows = [
        dict(row)
        for row in db.execute(
            f"""
            SELECT mwh.id AS watch_record_id, {effective_diary_date_sql('mwh')} AS watched_date,
                   m.id AS movie_id, m.title AS movie_title,
                   COALESCE(m.runtime_minutes, 0) AS runtime_minutes
            FROM movie_watch_history mwh
            JOIN movies m ON m.id = mwh.movie_id
            WHERE mwh.diary_date IS NOT NULL
            ORDER BY watched_date, mwh.added_at, mwh.id
            """
        ).fetchall()
    ]
    for row in rows:
        row["watched_date_value"] = date.fromisoformat(row["watched_date"])

    watch_count = len(rows)
    unique_episode_count = len({row["episode_id"] for row in rows})
    active_dates = sorted({row["watched_date_value"] for row in rows})
    total_minutes = sum(row["runtime_minutes"] for row in rows)
    active_day_count = len(active_dates)

    range_metrics = []
    for label, day_count in (("7 days", 7), ("30 days", 30), ("365 days", 365)):
        start_date = today - timedelta(days=day_count - 1)
        range_rows = [
            row for row in rows
            if start_date <= row["watched_date_value"] <= today
        ]
        range_minutes = sum(row["runtime_minutes"] for row in range_rows)
        range_metrics.append(
            {
                "label": label,
                "episode_count": len(range_rows),
                "watch_time": _format_duration(range_minutes),
                "average_per_day": round(len(range_rows) / day_count, 1),
            }
        )

    date_metrics: dict[date, dict[str, int]] = defaultdict(
        lambda: {"episode_count": 0, "minutes": 0}
    )
    show_metrics: dict[int, dict] = {}
    episode_metrics: dict[int, dict] = {}
    for row in rows:
        daily = date_metrics[row["watched_date_value"]]
        daily["episode_count"] += 1
        daily["minutes"] += row["runtime_minutes"]

        show = show_metrics.setdefault(
            row["show_id"],
            {
                "show_id": row["show_id"],
                "show_name": row["show_name"],
                "episode_count": row["episode_count"],
                "watch_count": 0,
                "minutes": 0,
                "episode_ids": set(),
            },
        )
        show["watch_count"] += 1
        show["minutes"] += row["runtime_minutes"]
        show["episode_ids"].add(row["episode_id"])

        episode = episode_metrics.setdefault(
            row["episode_id"],
            {
                "show_name": row["show_name"],
                "episode_name": row["episode_name"],
                "season_number": row["season_number"],
                "episode_number": row["episode_number"],
                "watch_count": 0,
            },
        )
        episode["watch_count"] += 1

    longest_streak = 0
    current_streak = 0
    previous_date = None
    for watched_date in active_dates:
        current_streak = (
            current_streak + 1
            if previous_date and watched_date == previous_date + timedelta(days=1)
            else 1
        )
        longest_streak = max(longest_streak, current_streak)
        previous_date = watched_date

    busiest_date = None
    if date_metrics:
        busiest_date, busiest_metrics = max(
            date_metrics.items(),
            key=lambda item: (item[1]["episode_count"], item[1]["minutes"], item[0]),
        )
    else:
        busiest_metrics = {"episode_count": 0, "minutes": 0}

    ranked_shows = []
    for show in show_metrics.values():
        unique_count = len(show.pop("episode_ids"))
        show["rewatch_count"] = show["watch_count"] - unique_count
        show["watch_time"] = _format_duration(show["minutes"])
        ranked_shows.append(show)
    ranked_shows.sort(
        key=lambda show: (show["minutes"], show["watch_count"], show["show_name"].casefold()),
        reverse=True,
    )
    top_shows = ranked_shows[:5]
    top_value = max(
        (show["minutes"] or show["watch_count"] for show in top_shows),
        default=0,
    )
    for show in top_shows:
        value = show["minutes"] or show["watch_count"]
        show["bar_percent"] = round(value / top_value * 100) if top_value else 0

    most_rewatched_show = db.execute(
        """
        SELECT s.id AS show_id, s.name AS show_name,
               CAST(ROUND(COUNT(wh.id) * 100.0 / COUNT(DISTINCT e.id)) AS INTEGER)
                   AS watch_percent
        FROM shows s
        JOIN seasons sn ON sn.show_id = s.id AND sn.is_progress_counted = 1
        JOIN episodes e ON e.season_id = sn.id
        LEFT JOIN episode_watch_history wh ON wh.episode_id = e.id
        GROUP BY s.id
        HAVING COUNT(wh.id) > COUNT(DISTINCT e.id)
        ORDER BY watch_percent DESC, COUNT(wh.id) DESC, s.name COLLATE NOCASE
        LIMIT 1
        """
    ).fetchone()
    most_rewatched_show = dict(most_rewatched_show) if most_rewatched_show else None

    most_rewatched_episode = max(
        episode_metrics.values(),
        key=lambda episode: episode["watch_count"],
        default=None,
    )
    if most_rewatched_episode and most_rewatched_episode["watch_count"] < 2:
        most_rewatched_episode = None

    movie_metrics: dict[int, dict] = {}
    for row in movie_rows:
        movie = movie_metrics.setdefault(
            row["movie_id"],
            {
                "movie_id": row["movie_id"],
                "movie_title": row["movie_title"],
                "watch_count": 0,
                "minutes": 0,
            },
        )
        movie["watch_count"] += 1
        movie["minutes"] += row["runtime_minutes"]
    most_rewatched_movie = max(
        movie_metrics.values(),
        key=lambda movie: (movie["watch_count"], movie["minutes"]),
        default=None,
    )
    if most_rewatched_movie and most_rewatched_movie["watch_count"] < 2:
        most_rewatched_movie = None

    return {
        "watch_count": watch_count,
        "unique_episode_count": unique_episode_count,
        "show_count": len(show_metrics),
        "rewatch_count": watch_count - unique_episode_count,
        "total_watch_time": _format_duration(total_minutes),
        "active_day_count": active_day_count,
        "average_episodes_per_active_day": (
            round(watch_count / active_day_count, 1) if active_day_count else 0
        ),
        "average_time_per_active_day": _format_duration(
            round(total_minutes / active_day_count) if active_day_count else 0
        ),
        "range_metrics": range_metrics,
        "longest_streak": longest_streak,
        "busiest_date": _format_stat_date(busiest_date, today) if busiest_date else "—",
        "busiest_date_episode_count": busiest_metrics["episode_count"],
        "busiest_date_watch_time": _format_duration(busiest_metrics["minutes"]),
        "most_rewatched_show": most_rewatched_show,
        "most_rewatched_episode": most_rewatched_episode,
        "movie_watch_count": len(movie_rows),
        "unique_movie_count": len(movie_metrics),
        "most_rewatched_movie": most_rewatched_movie,
        "top_shows": top_shows,
    }


def get_show_activity(db: sqlite3.Connection, show_id: int) -> list[sqlite3.Row]:
    effective_date = effective_diary_date_sql("swh")
    return db.execute(
        f"""
        WITH ordered_states AS (
            SELECT state, entered_at,
                   LAG(state) OVER (ORDER BY entered_at, id) AS previous_state,
                   ROW_NUMBER() OVER (ORDER BY entered_at, id) AS state_order
            FROM show_state_history
            WHERE show_id = ?
        ),
        initial_state AS (
            SELECT state
            FROM ordered_states
            WHERE state_order = 1
        ),
        activity AS (
            SELECT 'added' AS event_type,
                   CASE WHEN (SELECT state FROM initial_state) = 'ARCHIVED'
                        THEN 'Added to Archive'
                        ELSE 'Added to My Shows'
                   END AS title,
                   added_at AS occurred_at, NULL AS season_id,
                   NULL AS watch_record_id, NULL AS watch_kind,
                   NULL AS watch_added_at, NULL AS diary_date,
                   NULL AS season_diary_state
            FROM shows WHERE id = ? AND is_tracked = 1

            UNION ALL

            SELECT CASE state WHEN 'ARCHIVED' THEN 'archived' ELSE 'activated' END,
                   CASE state WHEN 'ARCHIVED' THEN 'Archived' ELSE 'Made active' END,
                    entered_at, NULL, NULL, NULL, NULL, NULL, NULL
            FROM ordered_states
            WHERE previous_state IS NOT NULL
              AND (state = 'ARCHIVED'
                   OR (state = 'ACTIVE' AND previous_state = 'ARCHIVED'))

            UNION ALL

            SELECT 'season_watched', sn.name || ' watched',
                   COALESCE({effective_date}, substr(swh.added_at, 1, 10)), sn.id, swh.id, 'season',
                    swh.added_at, swh.diary_date, NULL
            FROM season_watch_history swh
            JOIN seasons sn ON sn.id = swh.season_id
            WHERE sn.show_id = ?

            UNION ALL

            SELECT 'season_skipped', sn.name || ' skipped',
                   COALESCE(ssh.diary_date, substr(ssh.added_at, 1, 10)), sn.id, ssh.id, 'season-skip',
                    ssh.added_at, ssh.diary_date, NULL
            FROM season_skip_history ssh
            JOIN seasons sn ON sn.id = ssh.season_id
            WHERE sn.show_id = ?
        )
        SELECT event_type, title, occurred_at, season_id,
                watch_record_id, watch_kind, watch_added_at, diary_date,
                season_diary_state
        FROM activity
        ORDER BY occurred_at DESC, watch_added_at DESC
        """,
        (show_id, show_id, show_id, show_id),
    ).fetchall()


def get_tv_library_shows(
    db: sqlite3.Connection,
) -> tuple[list[sqlite3.Row], list[sqlite3.Row]]:
    shows = db.execute(
        """
        WITH episode_counts AS (
            SELECT e.id AS episode_id, sn.show_id,
                   (SELECT COUNT(*) FROM episode_watch_history wh WHERE wh.episode_id = e.id)
                   + (SELECT COUNT(*) FROM episode_skips sk WHERE sk.episode_id = e.id) AS watch_count,
                   MAX(wh.diary_date) AS last_watched_at
            FROM seasons sn
            JOIN episodes e ON e.season_id = sn.id
              AND sn.is_progress_counted = 1
              AND e.air_date <= date('now')
            LEFT JOIN episode_watch_history wh ON wh.episode_id = e.id
            GROUP BY e.id
        )
        SELECT s.*, COUNT(ec.episode_id) AS episode_count,
               COALESCE(SUM(CASE WHEN ec.watch_count > 0 THEN 1 ELSE 0 END), 0) AS watched_count,
               COALESCE(SUM(ec.watch_count), 0) AS total_watch_count,
               COALESCE(MIN(ec.watch_count), 0) AS completed_watch_count,
               MAX(ec.last_watched_at) AS last_watched_at
        FROM shows s
        LEFT JOIN episode_counts ec ON ec.show_id = s.id
        WHERE s.is_tracked = 1 AND s.state IN ('ACTIVE', 'ARCHIVED')
        GROUP BY s.id
        ORDER BY CASE s.state WHEN 'ACTIVE' THEN 0 ELSE 1 END, s.id ASC
        """
    ).fetchall()
    active_shows = sorted(
        (show for show in shows if show["state"] == TRACKING_ACTIVE),
        key=lambda show: (natural_title_key(show["name"]), show["id"]),
    )
    archived_shows = sorted(
        (show for show in shows if show["state"] == TRACKING_ARCHIVED),
        key=lambda show: (natural_title_key(show["name"]), show["id"]),
    )
    return active_shows, archived_shows


def get_movie_library(db: sqlite3.Connection) -> list[sqlite3.Row]:
    movies = db.execute(
        """
        SELECT m.*, COUNT(mwh.id) AS watched_count,
               CASE WHEN m.release_date > date('now', 'localtime') THEN 1 ELSE 0 END AS is_upcoming,
               MAX(mwh.diary_date) AS last_watched_at
        FROM movies m
        LEFT JOIN movie_watch_history mwh ON mwh.movie_id = m.id
        WHERE m.is_tracked = 1
        GROUP BY m.id
        ORDER BY m.title COLLATE NOCASE
        """
    ).fetchall()
    return movies


def get_reaction_media(
    db: sqlite3.Connection, reaction: str
) -> tuple[list[sqlite3.Row], list[sqlite3.Row]]:
    if reaction != "liked":
        raise ValueError(f"Unknown reaction: {reaction}")
    active_shows, archived_shows = get_tv_library_shows(db)
    shows = [show for show in (*active_shows, *archived_shows) if show["liked_at"]]
    movies = [movie for movie in get_movie_library(db) if movie["liked_at"]]
    return shows, movies


def get_movie_activity(db: sqlite3.Connection, movie_id: int) -> list[sqlite3.Row]:
    return db.execute(
        f"""
        SELECT event_type, title, occurred_at, sort_at, watch_record_id, watch_kind,
               watch_added_at, diary_date
        FROM (
            SELECT 'added' AS event_type, 'Added to Watchlist' AS title,
                   m.added_at AS occurred_at, m.added_at AS sort_at, NULL AS watch_record_id,
                    NULL AS watch_kind, NULL AS watch_added_at, NULL AS diary_date
            FROM movies m
            WHERE m.id = ? AND m.is_tracked = 1
            UNION ALL
            SELECT 'watched', 'Watched', COALESCE({effective_diary_date_sql('mwh')}, substr(mwh.added_at, 1, 10)),
                    mwh.added_at, mwh.id, 'movie', mwh.added_at, mwh.diary_date
            FROM movie_watch_history mwh
            WHERE mwh.movie_id = ?
        )
        ORDER BY sort_at DESC
        """,
        (movie_id, movie_id),
    ).fetchall()
