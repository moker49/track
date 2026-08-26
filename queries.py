from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from datetime import date, timedelta

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


def get_diary_entries(db: sqlite3.Connection) -> list[dict]:
    effective_date = effective_watch_date_sql("wh")
    rows = db.execute(
        f"""
        WITH diary_watches AS (
            SELECT wh.id AS watch_record_id, wh.added_at, wh.watch_date,
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
        )
        SELECT * FROM diary_watches
        ORDER BY watched_date DESC, added_at DESC, watch_record_id DESC
        """
    ).fetchall()
    release_groups: dict[tuple[str, int, int, int], list[dict]] = {}
    for row in rows:
        watch = dict(row)
        release_groups.setdefault(
            (
                watch["watched_date"],
                watch["show_id"],
                watch["season_id"],
                watch["watch_iteration"],
            ),
            [],
        ).append(watch)

    entries = []
    for watches in release_groups.values():
        watches.sort(key=lambda watch: (watch["episode_number"], watch["watch_record_id"]))
        entry = dict(watches[0])
        watched_date = date.fromisoformat(entry["watched_date"])
        is_grouped = len(watches) > 1
        release_metadata = (
            f"Season {entry['season_number']} · Episodes "
            f"{watches[0]['episode_number']}–{watches[-1]['episode_number']}"
            if is_grouped
            else f"Season {entry['season_number']} · Episode {entry['episode_number']}"
        )
        entry.update(
            month_key=f"{9999 - watched_date.year:04d}-{13 - watched_date.month:02d}",
            month_label=watched_date.strftime("%B %Y").upper(),
            day_label=f"{watched_date.day:02d}",
            weekday_label=watched_date.strftime("%a").upper(),
            is_grouped=is_grouped,
            season_ids=str(entry["season_id"]),
            watch_record_ids=",".join(str(watch["watch_record_id"]) for watch in watches),
            release_metadata=release_metadata,
            latest_added_at=max(watch["added_at"] for watch in watches),
        )
        entries.append(entry)
    entries.sort(
        key=lambda entry: (
            entry["watched_date"],
            entry["latest_added_at"],
            entry["watch_record_id"],
        ),
        reverse=True,
    )
    return entries


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
    effective_date = effective_watch_date_sql("wh")
    rows = [
        dict(row)
        for row in db.execute(
            f"""
            SELECT wh.id AS watch_record_id, {effective_date} AS watched_date,
                   s.id AS show_id, s.name AS show_name,
                   sn.season_number, e.id AS episode_id,
                   e.episode_number, e.name AS episode_name,
                   COALESCE(e.runtime_minutes, 0) AS runtime_minutes
            FROM episode_watch_history wh
            JOIN episodes e ON e.id = wh.episode_id
            JOIN seasons sn ON sn.id = e.season_id
            JOIN shows s ON s.id = sn.show_id
            ORDER BY watched_date, wh.added_at, wh.id
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

    most_rewatched_show = max(
        ranked_shows,
        key=lambda show: (show["rewatch_count"], show["watch_count"]),
        default=None,
    )
    if most_rewatched_show and most_rewatched_show["rewatch_count"] == 0:
        most_rewatched_show = None

    most_rewatched_episode = max(
        episode_metrics.values(),
        key=lambda episode: episode["watch_count"],
        default=None,
    )
    if most_rewatched_episode and most_rewatched_episode["watch_count"] < 2:
        most_rewatched_episode = None

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
        "top_shows": top_shows,
    }


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
