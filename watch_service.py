from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from domain import effective_watch_date_sql
from queries import get_episode_watch_count, get_show_progress, watch_payload


class WatchNotFoundError(LookupError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _episode_context(db: sqlite3.Connection, episode_id: int) -> sqlite3.Row:
    episode = db.execute(
        """
        SELECT e.id, sn.show_id
        FROM episodes e
        JOIN seasons sn ON sn.id = e.season_id
        WHERE e.id = ?
        """,
        (episode_id,),
    ).fetchone()
    if episode is None:
        raise WatchNotFoundError("Episode not found")
    return episode


def set_episode_watched(
    db: sqlite3.Connection, episode_id: int, watched: bool
) -> dict:
    episode = _episode_context(db, episode_id)
    previous_watched_count = get_show_progress(db, episode["show_id"])["watched_count"]
    if watched:
        db.execute("DELETE FROM episode_skips WHERE episode_id = ?", (episode_id,))
        exists = db.execute(
            "SELECT 1 FROM episode_watch_history WHERE episode_id = ? LIMIT 1",
            (episode_id,),
        ).fetchone()
        if exists is None:
            db.execute(
                "INSERT INTO episode_watch_history (episode_id, added_at) VALUES (?, ?)",
                (episode_id, _now()),
            )
    else:
        db.execute(
            f"""
            DELETE FROM episode_watch_history
            WHERE id = (
                SELECT id FROM episode_watch_history
                WHERE episode_id = ?
                ORDER BY {effective_watch_date_sql()} DESC, added_at DESC, id DESC
                LIMIT 1
            )
            """,
            (episode_id,),
        )
    db.commit()
    return watch_payload(
        db, episode["show_id"], episode_id, previous_watched_count
    )


def change_episode_watch_count(
    db: sqlite3.Connection, episode_id: int, action: str
) -> dict:
    episode = _episode_context(db, episode_id)
    previous_watched_count = get_show_progress(db, episode["show_id"])["watched_count"]
    changed_at = _now()
    watch_record_id = None
    if action == "increment":
        db.execute("DELETE FROM episode_skips WHERE episode_id = ?", (episode_id,))
        watch_record_id = db.execute(
            "INSERT INTO episode_watch_history (episode_id, added_at) VALUES (?, ?)",
            (episode_id, changed_at),
        ).lastrowid
    else:
        latest = db.execute(
            f"""
            SELECT id FROM episode_watch_history
            WHERE episode_id = ?
            ORDER BY {effective_watch_date_sql()} DESC, added_at DESC, id DESC
            LIMIT 1
            """,
            (episode_id,),
        ).fetchone()
        if latest is not None:
            watch_record_id = latest["id"]
            db.execute("DELETE FROM episode_watch_history WHERE id = ?", (latest["id"],))
    db.commit()
    result = watch_payload(
        db, episode["show_id"], episode_id, previous_watched_count
    )
    result.update(
        action=action,
        changed_at=changed_at,
        watch_record_id=watch_record_id,
    )
    return result


def change_season_watch_count(
    db: sqlite3.Connection, season_id: int, action: str
) -> dict:
    season = db.execute(
        "SELECT id, show_id, name FROM seasons WHERE id = ?", (season_id,)
    ).fetchone()
    if season is None:
        raise WatchNotFoundError("Season not found")
    previous_watched_count = get_show_progress(db, season["show_id"])["watched_count"]

    episode_ids = [
        row["id"]
        for row in db.execute(
            "SELECT id FROM episodes WHERE season_id = ? ORDER BY episode_number",
            (season_id,),
        ).fetchall()
    ]
    changed_at = _now()
    season_watch_record_id = None
    if action == "increment":
        if episode_ids:
            placeholders = ",".join("?" for _episode_id in episode_ids)
            db.execute(
                f"DELETE FROM episode_skips WHERE episode_id IN ({placeholders})",
                episode_ids,
            )
        db.executemany(
            "INSERT INTO episode_watch_history (episode_id, added_at) VALUES (?, ?)",
            [(episode_id, changed_at) for episode_id in episode_ids],
        )
        if episode_ids:
            season_watch_record_id = db.execute(
                "INSERT INTO season_watch_history (season_id, added_at) VALUES (?, ?)",
                (season_id, changed_at),
            ).lastrowid
    else:
        latest_watches = db.execute(
            f"""
            SELECT id FROM (
                SELECT wh.id,
                       ROW_NUMBER() OVER (
                           PARTITION BY wh.episode_id
                           ORDER BY {effective_watch_date_sql('wh')} DESC,
                                    wh.added_at DESC, wh.id DESC
                       ) AS row_number
                FROM episode_watch_history wh
                JOIN episodes e ON e.id = wh.episode_id
                WHERE e.season_id = ?
            )
            WHERE row_number = 1
            """,
            (season_id,),
        ).fetchall()
        db.executemany(
            "DELETE FROM episode_watch_history WHERE id = ?",
            [(row["id"],) for row in latest_watches],
        )
        latest_season_watch = db.execute(
            f"""
            SELECT id FROM season_watch_history
            WHERE season_id = ?
            ORDER BY {effective_watch_date_sql()} DESC, added_at DESC, id DESC
            LIMIT 1
            """,
            (season_id,),
        ).fetchone()
        if latest_season_watch is not None:
            season_watch_record_id = latest_season_watch["id"]
            db.execute(
                "DELETE FROM season_watch_history WHERE id = ?",
                (season_watch_record_id,),
            )
    db.commit()

    episode_counts = [
        {"episode_id": episode_id, "watch_count": get_episode_watch_count(db, episode_id)}
        for episode_id in episode_ids
    ]
    result = watch_payload(
        db, season["show_id"], previous_watched_count=previous_watched_count
    )
    result.update(
        season_id=season_id,
        season_name=season["name"],
        episodes=episode_counts,
        season_episode_count=len(episode_counts),
        season_watched_count=sum(item["watch_count"] > 0 for item in episode_counts),
        season_min_watch_count=(
            min(item["watch_count"] for item in episode_counts)
            if episode_counts and all(item["watch_count"] > 0 for item in episode_counts)
            else 0
        ),
        season_watched_at=(changed_at if action == "increment" and episode_ids else None),
        season_watch_record_id=season_watch_record_id,
    )
    return result


def set_watch_history_date(
    db: sqlite3.Connection, watch_kind: str, record_id: int, watch_date: str | None
) -> dict:
    table = {
        "episode": "episode_watch_history",
        "season": "season_watch_history",
    }.get(watch_kind)
    if table is None:
        raise WatchNotFoundError("Unknown watch history type")

    cursor = db.execute(
        f"UPDATE {table} SET watch_date = ? WHERE id = ?", (watch_date, record_id)
    )
    if cursor.rowcount == 0:
        raise WatchNotFoundError("Watch entry not found")
    row = db.execute(
        f"""
        SELECT added_at, watch_date,
               {effective_watch_date_sql()} AS display_date
        FROM {table}
        WHERE id = ?
        """,
        (record_id,),
    ).fetchone()
    db.commit()
    return {
        "watch_kind": watch_kind,
        "record_id": record_id,
        "added_at": row["added_at"],
        "watch_date": row["watch_date"],
        "display_date": row["display_date"],
    }
