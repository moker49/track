from __future__ import annotations

import re
import sqlite3
from datetime import date

from domain import TRACKING_ACTIVE, TRACKING_ARCHIVED, effective_watch_date_sql


def natural_title_key(value: str) -> tuple:
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in re.split(r"(\d+)", value)
        if part
    )


def get_show_progress(db: sqlite3.Connection, show_id: int) -> sqlite3.Row:
    return db.execute(
        """
        SELECT COUNT(DISTINCT e.id) AS episode_count,
               COUNT(DISTINCT CASE WHEN wh.id IS NOT NULL THEN e.id END) AS watched_count
        FROM seasons sn
        JOIN episodes e ON e.season_id = sn.id AND e.air_date <= date('now')
        LEFT JOIN episode_watch_history wh ON wh.episode_id = e.id
        WHERE sn.show_id = ? AND sn.is_progress_counted = 1
        """,
        (show_id,),
    ).fetchone()


def get_episode_watch_count(db: sqlite3.Connection, episode_id: int) -> int:
    return db.execute(
        "SELECT COUNT(*) FROM episode_watch_history WHERE episode_id = ?",
        (episode_id,),
    ).fetchone()[0]


def watch_payload(
    db: sqlite3.Connection, show_id: int, episode_id: int | None = None
) -> dict:
    progress = get_show_progress(db, show_id)
    episode_count = progress["episode_count"]
    watched_count = progress["watched_count"]
    payload = {
        "show_id": show_id,
        "watched_count": watched_count,
        "episode_count": episode_count,
        "percent": round(watched_count / episode_count * 100) if episode_count else 0,
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
        SELECT s.*,
               COUNT(DISTINCT e.id) AS episode_count,
               COUNT(DISTINCT CASE WHEN wh.id IS NOT NULL THEN e.id END) AS watched_count
        FROM shows s
        LEFT JOIN seasons sn ON sn.show_id = s.id
        LEFT JOIN episodes e ON e.season_id = sn.id
          AND sn.is_progress_counted = 1
          AND e.air_date <= date('now')
        LEFT JOIN episode_watch_history wh ON wh.episode_id = e.id
        WHERE s.id = ?
        GROUP BY s.id
        """,
        (show_id,),
    ).fetchone()


def get_catch_up_episodes(
    db: sqlite3.Connection,
    show_id: int | None = None,
    local_date: date | None = None,
) -> list[sqlite3.Row]:
    local_date = local_date or date.today()
    local_date_value = local_date.isoformat()
    return db.execute(
        """
        WITH show_progress AS (
            SELECT s.id AS show_id,
                   COUNT(DISTINCT e.id) AS episode_count,
                   COUNT(DISTINCT CASE WHEN wh.id IS NOT NULL THEN e.id END) AS watched_count
            FROM shows s
            JOIN seasons sn ON sn.show_id = s.id AND sn.is_progress_counted = 1
            JOIN episodes e ON e.season_id = sn.id AND e.air_date <= ?
            LEFT JOIN episode_watch_history wh ON wh.episode_id = e.id
            WHERE s.is_tracked = 1 AND s.state = 'ACTIVE'
            GROUP BY s.id
        ),
        unresolved AS (
            SELECT s.id AS show_id, s.name AS show_name, s.poster_path,
                   sn.season_number, sn.name AS season_name,
                   e.id AS episode_id, e.episode_number,
                   e.name AS episode_name, e.air_date, e.runtime_minutes,
                   ROW_NUMBER() OVER (
                       PARTITION BY s.id
                       ORDER BY CASE WHEN sk.episode_id IS NULL THEN 0 ELSE 1 END,
                                sk.skipped_at, e.air_date,
                                sn.season_number, e.episode_number
                   ) AS episode_rank
            FROM shows s
            JOIN seasons sn ON sn.show_id = s.id
            JOIN episodes e ON e.season_id = sn.id
            LEFT JOIN episode_skips sk ON sk.episode_id = e.id
            WHERE s.is_tracked = 1
              AND s.state = 'ACTIVE'
              AND sn.is_progress_counted = 1
              AND e.air_date IS NOT NULL
              AND e.air_date <= ?
              AND (? IS NULL OR s.id = ?)
              AND NOT EXISTS (
                  SELECT 1 FROM episode_watch_history wh WHERE wh.episode_id = e.id
              )
        )
        SELECT unresolved.*, show_progress.episode_count, show_progress.watched_count
        FROM unresolved
        JOIN show_progress ON show_progress.show_id = unresolved.show_id
        WHERE unresolved.episode_rank = 1
        ORDER BY unresolved.air_date DESC, unresolved.show_name COLLATE NOCASE
        """,
        (local_date_value, local_date_value, show_id, show_id),
    ).fetchall()


def get_upcoming_episodes(
    db: sqlite3.Connection, local_date: date | None = None
) -> list[dict]:
    local_date = local_date or date.today()
    local_date_value = local_date.isoformat()
    rows = db.execute(
        """
        SELECT s.id AS show_id, s.name AS show_name, s.poster_path,
               sn.id AS season_id, sn.season_number, sn.name AS season_name,
               (SELECT COUNT(*) FROM episodes season_episode
                WHERE season_episode.season_id = sn.id) AS season_episode_count,
               e.id AS episode_id, e.episode_number,
               e.name AS episode_name, e.air_date, e.runtime_minutes
        FROM shows s
        JOIN seasons sn ON sn.show_id = s.id
        JOIN episodes e ON e.season_id = sn.id
        WHERE s.is_tracked = 1
          AND sn.is_progress_counted = 1
          AND e.air_date IS NOT NULL
          AND e.air_date >= date(?, '-7 days')
        ORDER BY e.air_date, s.name COLLATE NOCASE,
                 sn.season_number, e.episode_number
        """,
        (local_date_value,),
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
    return upcoming


def get_show_activity(db: sqlite3.Connection, show_id: int) -> list[sqlite3.Row]:
    effective_date = effective_watch_date_sql("swh")
    return db.execute(
        f"""
        WITH ordered_states AS (
            SELECT state, entered_at,
                   LAG(state) OVER (ORDER BY entered_at, id) AS previous_state
            FROM show_state_history
            WHERE show_id = ?
        ),
        activity AS (
            SELECT 'added' AS event_type, 'Added to My Shows' AS title,
                   added_at AS occurred_at, NULL AS season_id,
                   NULL AS watch_record_id, NULL AS watch_kind,
                   NULL AS watch_added_at, NULL AS watch_date
            FROM shows WHERE id = ? AND is_tracked = 1

            UNION ALL

            SELECT CASE state WHEN 'ARCHIVED' THEN 'archived' ELSE 'activated' END,
                   CASE state WHEN 'ARCHIVED' THEN 'Archived' ELSE 'Made active' END,
                   entered_at, NULL, NULL, NULL, NULL, NULL
            FROM ordered_states
            WHERE state = 'ARCHIVED'
               OR (state = 'ACTIVE' AND previous_state = 'ARCHIVED')

            UNION ALL

            SELECT 'season_watched', sn.name || ' watched',
                   {effective_date}, sn.id, swh.id, 'season',
                   swh.added_at, swh.watch_date
            FROM season_watch_history swh
            JOIN seasons sn ON sn.id = swh.season_id
            WHERE sn.show_id = ?
        )
        SELECT event_type, title, occurred_at, season_id,
               watch_record_id, watch_kind, watch_added_at, watch_date
        FROM activity
        ORDER BY occurred_at DESC, watch_added_at DESC
        """,
        (show_id, show_id, show_id),
    ).fetchall()


def get_tv_library_shows(
    db: sqlite3.Connection,
) -> tuple[list[sqlite3.Row], list[sqlite3.Row]]:
    shows = db.execute(
        """
        SELECT s.*,
               COUNT(DISTINCT e.id) AS episode_count,
               COUNT(DISTINCT CASE WHEN wh.id IS NOT NULL THEN e.id END) AS watched_count
        FROM shows s
        LEFT JOIN seasons sn ON sn.show_id = s.id
        LEFT JOIN episodes e ON e.season_id = sn.id
          AND sn.is_progress_counted = 1
          AND e.air_date <= date('now')
        LEFT JOIN episode_watch_history wh ON wh.episode_id = e.id
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
