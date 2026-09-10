from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

from domain import effective_diary_date_sql
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


def _latest_episode_resolution(db: sqlite3.Connection, episode_id: int) -> sqlite3.Row | None:
    return db.execute(
        """
        SELECT resolution_kind, resolution_id
        FROM (
            SELECT 'watch' AS resolution_kind, id AS resolution_id,
                   COALESCE(diary_date, substr(added_at, 1, 10)) AS resolved_at,
                   added_at AS added_at
            FROM episode_watch_history WHERE episode_id = ?
            UNION ALL
            SELECT 'skip' AS resolution_kind, id AS resolution_id,
                   COALESCE(diary_date, substr(skipped_at, 1, 10)) AS resolved_at, skipped_at AS added_at
            FROM episode_skips WHERE episode_id = ?
        )
        ORDER BY resolved_at DESC, added_at DESC, resolution_id DESC
        LIMIT 1
        """,
        (episode_id, episode_id),
    ).fetchone()


def _clear_completed_watch_again(db: sqlite3.Connection, show_id: int) -> bool:
    show = db.execute(
        "SELECT watch_again, watch_again_baseline FROM shows WHERE id = ?", (show_id,)
    ).fetchone()
    if not show or not show["watch_again"]:
        return False
    progress = get_show_progress(db, show_id)
    baseline = show["watch_again_baseline"] or 0
    if progress["episode_count"] and progress["completed_watch_count"] > baseline:
        db.execute(
            "UPDATE shows SET watch_again = 0, watch_again_baseline = NULL WHERE id = ?",
            (show_id,),
        )
        return True
    return False


def set_episode_watched(
    db: sqlite3.Connection, episode_id: int, watched: bool
) -> dict:
    episode = _episode_context(db, episode_id)
    previous_watched_count = get_show_progress(db, episode["show_id"])["watched_count"]
    if watched:
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
                ORDER BY {effective_diary_date_sql()} DESC, added_at DESC, id DESC
                LIMIT 1
            )
            """,
            (episode_id,),
        )
    watch_again_cleared = _clear_completed_watch_again(db, episode["show_id"]) if watched else False
    db.commit()
    result = watch_payload(
        db, episode["show_id"], episode_id, previous_watched_count
    )
    result["watch_again_cleared"] = watch_again_cleared
    return result


def change_episode_watch_count(
    db: sqlite3.Connection, episode_id: int, action: str
) -> dict:
    episode = _episode_context(db, episode_id)
    previous_watched_count = get_show_progress(db, episode["show_id"])["watched_count"]
    changed_at = _now()
    watch_record_id = None
    if action == "increment":
        watch_record_id = db.execute(
            "INSERT INTO episode_watch_history (episode_id, added_at) VALUES (?, ?)",
            (episode_id, changed_at),
        ).lastrowid
    else:
        latest = _latest_episode_resolution(db, episode_id)
        if latest is not None:
            watch_record_id = latest["resolution_id"]
            table = "episode_skips" if latest["resolution_kind"] == "skip" else "episode_watch_history"
            db.execute(f"DELETE FROM {table} WHERE id = ?", (watch_record_id,))
    watch_again_cleared = _clear_completed_watch_again(db, episode["show_id"]) if action == "increment" else False
    db.commit()
    result = watch_payload(
        db, episode["show_id"], episode_id, previous_watched_count
    )
    result.update(
        action=action,
        changed_at=changed_at,
        watch_record_id=watch_record_id,
        resolution_kind=("watch" if action == "increment" else (latest["resolution_kind"] if latest else None)),
        watch_again_cleared=watch_again_cleared,
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
                           ORDER BY {effective_diary_date_sql('wh')} DESC,
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
            ORDER BY {effective_diary_date_sql()} DESC, added_at DESC, id DESC
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
    watch_again_cleared = _clear_completed_watch_again(db, season["show_id"]) if action == "increment" else False
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
        watch_again_cleared=watch_again_cleared,
    )
    return result


def set_watch_history_date(
    db: sqlite3.Connection, watch_kind: str, record_id: int, diary_date: str | None
) -> dict:
    table = {
        "episode": "episode_watch_history",
        "season": "season_watch_history",
    }.get(watch_kind)
    if table is None:
        raise WatchNotFoundError("Unknown watch history type")

    history = db.execute(
        f"SELECT batch_id FROM {table} WHERE id = ?", (record_id,)
    ).fetchone()
    if history is None:
        raise WatchNotFoundError("Watch entry not found")

    cursor = db.execute(
        f"UPDATE {table} SET diary_date = ? WHERE id = ?",
        (diary_date, record_id),
    )
    if watch_kind == "season" and history["batch_id"]:
        db.execute(
            """UPDATE episode_watch_history
               SET diary_date = ?
               WHERE batch_id = ?""",
            (diary_date, history["batch_id"]),
        )
    row = db.execute(
        f"""
        SELECT added_at, diary_date,
               COALESCE({effective_diary_date_sql()}, substr(added_at, 1, 10)) AS display_date
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
        "diary_date": row["diary_date"],
        "display_date": row["display_date"],
    }


def create_episode_log(db: sqlite3.Connection, episode_id: int, action_kind: str, log_date: str | None) -> dict:
    episode = _episode_context(db, episode_id)
    created_at = _now()
    if action_kind == "watch":
        record_id = db.execute(
            "INSERT INTO episode_watch_history (episode_id, added_at, diary_date) VALUES (?, ?, ?)",
            (episode_id, created_at, log_date),
        ).lastrowid
    elif action_kind == "skip":
        record_id = db.execute(
            "INSERT INTO episode_skips (episode_id, skipped_at, diary_date) VALUES (?, ?, ?)",
            (episode_id, created_at, log_date),
        ).lastrowid
    else:
        raise WatchNotFoundError("Unknown log action")
    db.commit()
    result = watch_payload(db, episode["show_id"], episode_id)
    result.update({"episode_id": episode_id, "watch_record_id": record_id,
            "watch_kind": "episode" if action_kind == "watch" else "skip", "action_kind": action_kind,
            "added_at": created_at, "diary_date": log_date, "display_date": log_date or created_at[:10],
            "watch_count": get_episode_watch_count(db, episode_id)})
    return result


def create_season_log(db: sqlite3.Connection, season_id: int, action_kind: str, log_date: str | None) -> dict:
    season = db.execute("SELECT id, show_id, name FROM seasons WHERE id = ?", (season_id,)).fetchone()
    if season is None:
        raise WatchNotFoundError("Season not found")
    episode_ids = [row["id"] for row in db.execute(
        "SELECT id FROM episodes WHERE season_id = ? ORDER BY episode_number", (season_id,)
    )]
    if not episode_ids:
        raise WatchNotFoundError("Season has no episodes")
    batch_id, created_at = str(uuid.uuid4()), _now()
    db.execute("INSERT INTO season_log_batches (id, season_id, action_kind, created_at) VALUES (?, ?, ?, ?)",
               (batch_id, season_id, action_kind, created_at))
    if action_kind == "watch":
        record_id = db.execute(
            "INSERT INTO season_watch_history (season_id, added_at, diary_date, batch_id) VALUES (?, ?, ?, ?)",
            (season_id, created_at, log_date, batch_id),
        ).lastrowid
        db.executemany(
            "INSERT INTO episode_watch_history (episode_id, added_at, diary_date, batch_id) VALUES (?, ?, ?, ?)",
            [(episode_id, created_at, log_date, batch_id) for episode_id in episode_ids],
        )
        watch_kind = "season"
    elif action_kind == "skip":
        record_id = db.execute(
            "INSERT INTO season_skip_history (season_id, added_at, diary_date, batch_id) VALUES (?, ?, ?, ?)",
            (season_id, created_at, log_date, batch_id),
        ).lastrowid
        db.executemany(
            "INSERT INTO episode_skips (episode_id, skipped_at, diary_date, batch_id) VALUES (?, ?, ?, ?)",
            [(episode_id, created_at, log_date, batch_id) for episode_id in episode_ids],
        )
        watch_kind = "season-skip"
    else:
        raise WatchNotFoundError("Unknown log action")
    db.commit()
    episodes = [
        {"episode_id": episode_id, "watch_count": get_episode_watch_count(db, episode_id)}
        for episode_id in episode_ids
    ]
    result = watch_payload(db, season["show_id"])
    result.update({"season_id": season_id, "season_name": season["name"],
            "watch_record_id": record_id, "watch_kind": watch_kind, "action_kind": action_kind,
            "batch_id": batch_id, "added_at": created_at, "diary_date": log_date, "display_date": log_date or created_at[:10],
            "episodes": episodes})
    return result


def remove_log(db: sqlite3.Connection, watch_kind: str, record_id: int) -> dict:
    season_id = None
    episode_id = None
    movie_id = None
    if watch_kind == "episode":
        row = db.execute("SELECT episode_id FROM episode_watch_history WHERE id = ?", (record_id,)).fetchone()
        if row is None: raise WatchNotFoundError("Log entry not found")
        episode_id = row["episode_id"]
        cursor = db.execute("DELETE FROM episode_watch_history WHERE id = ?", (record_id,))
    elif watch_kind == "skip":
        row = db.execute("SELECT episode_id FROM episode_skips WHERE id = ?", (record_id,)).fetchone()
        if row is None: raise WatchNotFoundError("Log entry not found")
        episode_id = row["episode_id"]
        cursor = db.execute("DELETE FROM episode_skips WHERE id = ?", (record_id,))
    elif watch_kind == "movie":
        row = db.execute("SELECT movie_id FROM movie_watch_history WHERE id = ?", (record_id,)).fetchone()
        if row is None: raise WatchNotFoundError("Log entry not found")
        movie_id = row["movie_id"]
        cursor = db.execute("DELETE FROM movie_watch_history WHERE id = ?", (record_id,))
    elif watch_kind in {"season", "season-skip"}:
        table = "season_watch_history" if watch_kind == "season" else "season_skip_history"
        row = db.execute(f"SELECT batch_id, season_id FROM {table} WHERE id = ?", (record_id,)).fetchone()
        if row is None: raise WatchNotFoundError("Log entry not found")
        if not row["batch_id"]: raise WatchNotFoundError("Legacy season entry cannot be removed as a batch")
        season_id = row["season_id"]
        if watch_kind == "season": db.execute("DELETE FROM episode_watch_history WHERE batch_id = ?", (row["batch_id"],))
        else: db.execute("DELETE FROM episode_skips WHERE batch_id = ?", (row["batch_id"],))
        cursor = db.execute(f"DELETE FROM {table} WHERE id = ?", (record_id,))
        db.execute("DELETE FROM season_log_batches WHERE id = ?", (row["batch_id"],))
    else: raise WatchNotFoundError("Unknown log entry")
    if cursor.rowcount == 0: raise WatchNotFoundError("Log entry not found")
    db.commit()
    episodes = []
    if season_id is not None:
        episodes = [
            {"episode_id": row["id"], "watch_count": get_episode_watch_count(db, row["id"])}
            for row in db.execute("SELECT id FROM episodes WHERE season_id = ?", (season_id,))
        ]
    return {"season_id": season_id, "episode_id": episode_id,
            "watch_count": get_episode_watch_count(db, episode_id) if episode_id is not None else None,
            "movie_id": movie_id,
            "movie_watch_count": db.execute("SELECT COUNT(*) FROM movie_watch_history WHERE movie_id = ?", (movie_id,)).fetchone()[0] if movie_id is not None else None,
            "episodes": episodes}
