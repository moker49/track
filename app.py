from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.request import urlopen

from flask import Flask, abort, g, jsonify, redirect, render_template, request, send_file, url_for
from dotenv import load_dotenv

from migrations import migrate_database
from image_cache import ImageCacheError, cached_image
from tmdb import TMDBClient, TMDBError
from tmdb_import import import_or_refresh_show


BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "instance" / "track.db"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def migrate_watch_history_tables(db: sqlite3.Connection) -> None:
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

        columns = {
            row["name"] for row in db.execute(f"PRAGMA table_info({table})")
        }
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
        active_filter = (
            "WHERE unwatched_at IS NULL" if "unwatched_at" in columns else ""
        )
        db.execute(
            f"""
            INSERT INTO {table} (id, {parent_column}, added_at, watch_date)
            SELECT id, {parent_column}, {added_source}, {date_source}
            FROM {legacy_table}
            {active_filter}
            """
        )
        db.execute(f"DROP TABLE {legacy_table}")


def create_app(test_config: dict | None = None) -> Flask:
    dotenv_path = (test_config or {}).get("DOTENV_PATH", BASE_DIR / ".env")
    load_dotenv(dotenv_path=dotenv_path, override=False)
    app = Flask(__name__)
    app.config.from_mapping(
        DATABASE=str(DATABASE),
        TMDB_READ_ACCESS_TOKEN=os.environ.get("TMDB_READ_ACCESS_TOKEN", ""),
        TMDB_CACHE_TTL=timedelta(days=1),
        SHOW_METADATA_TTL=timedelta(days=1),
        TMDB_CLIENT_FACTORY=TMDBClient,
        IMAGE_CACHE_DIR=None,
        IMAGE_TRANSPORT=urlopen,
    )
    if test_config:
        app.config.update(test_config)

    if app.config["IMAGE_CACHE_DIR"] is None:
        app.config["IMAGE_CACHE_DIR"] = str(
            Path(app.config["DATABASE"]).parent / "images"
        )

    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)

    def get_db() -> sqlite3.Connection:
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DATABASE"])
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys = ON")
        return g.db

    @app.teardown_appcontext
    def close_db(_error=None) -> None:
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.context_processor
    def inject_year() -> dict:
        return {"current_year": datetime.now().year}

    def get_show_progress(db: sqlite3.Connection, show_id: int) -> sqlite3.Row:
        return db.execute(
            """
            SELECT COUNT(DISTINCT e.id) AS episode_count,
                   COUNT(DISTINCT CASE WHEN wh.id IS NOT NULL THEN e.id END) AS watched_count
            FROM seasons sn
            JOIN episodes e ON e.season_id = sn.id AND e.air_date <= date('now')
            LEFT JOIN episode_watch_history wh
              ON wh.episode_id = e.id
            WHERE sn.show_id = ? AND sn.is_progress_counted = 1
            """,
            (show_id,),
        ).fetchone()

    def get_episode_watch_count(db: sqlite3.Connection, episode_id: int) -> int:
        return db.execute(
            """
            SELECT COUNT(*)
            FROM episode_watch_history
            WHERE episode_id = ?
            """,
            (episode_id,),
        ).fetchone()[0]

    def get_tmdb_client() -> TMDBClient:
        return app.config["TMDB_CLIENT_FACTORY"](
            app.config["TMDB_READ_ACCESS_TOKEN"]
        )

    def show_metadata_is_fresh(refreshed_at: str | None) -> bool:
        if not refreshed_at:
            return False
        try:
            refreshed = datetime.fromisoformat(refreshed_at.replace("Z", "+00:00"))
        except ValueError:
            return False
        if refreshed.tzinfo is None:
            refreshed = refreshed.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - refreshed < app.config["SHOW_METADATA_TTL"]

    def catalog_results(payload: dict) -> list[dict]:
        results = []
        for item in payload.get("results", []):
            tmdb_id = item.get("id")
            if not isinstance(tmdb_id, int):
                continue
            results.append(
                {
                    "tmdb_id": tmdb_id,
                    "name": item.get("name") or item.get("original_name") or "Untitled show",
                    "overview": item.get("overview") or "No overview available.",
                    "poster_path": item.get("poster_path"),
                    "first_air_date": item.get("first_air_date"),
                    "vote_average": item.get("vote_average"),
                }
            )
        if not results:
            return results
        placeholders = ",".join("?" for _item in results)
        local_by_tmdb_id = {
            row["tmdb_id"]: row
            for row in get_db().execute(
                f"""
                SELECT id, tmdb_id, state, is_tracked
                FROM shows
                WHERE tmdb_id IN ({placeholders})
                """,
                [item["tmdb_id"] for item in results],
            )
        }
        for item in results:
            local = local_by_tmdb_id.get(item["tmdb_id"])
            item["show_id"] = local["id"] if local else None
            item["is_tracked"] = bool(local["is_tracked"]) if local else False
            item["state"] = local["state"] if local and local["is_tracked"] else None
        return results

    def get_library_show(db: sqlite3.Connection, show_id: int) -> sqlite3.Row | None:
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
            "percent": (
                round(watched_count / episode_count * 100) if episode_count else 0
            ),
        }
        if episode_id is not None:
            episode_watch_count = get_episode_watch_count(db, episode_id)
            payload.update(
                episode_id=episode_id,
                watched=episode_watch_count > 0,
                watch_count=episode_watch_count,
            )
        return payload

    def get_show_activity(db: sqlite3.Connection, show_id: int) -> list[sqlite3.Row]:
        return db.execute(
            """
            WITH ordered_states AS (
                SELECT state,
                       entered_at,
                       LAG(state) OVER (ORDER BY entered_at, id) AS previous_state
                FROM show_state_history
                WHERE show_id = ?
            ),
            activity AS (
                SELECT 'added' AS event_type,
                       'Added to My Shows' AS title,
                       added_at AS occurred_at,
                       NULL AS season_id,
                       NULL AS watch_record_id,
                       NULL AS watch_kind,
                       NULL AS watch_added_at,
                       NULL AS watch_date
                FROM shows
                WHERE id = ? AND is_tracked = 1

                UNION ALL

                SELECT CASE state
                           WHEN 'ARCHIVED' THEN 'archived'
                           ELSE 'started_watching'
                       END AS event_type,
                       CASE state
                           WHEN 'ARCHIVED' THEN 'Archived'
                           ELSE 'Started watching'
                       END AS title,
                       entered_at AS occurred_at,
                       NULL AS season_id,
                       NULL AS watch_record_id,
                       NULL AS watch_kind,
                       NULL AS watch_added_at,
                       NULL AS watch_date
                FROM ordered_states
                WHERE state = 'ARCHIVED'
                   OR (state = 'WATCHING' AND previous_state = 'ARCHIVED')

                UNION ALL

                SELECT 'season_watched' AS event_type,
                       sn.name || ' watched' AS title,
                       COALESCE(swh.watch_date, substr(swh.added_at, 1, 10)) AS occurred_at,
                       sn.id AS season_id,
                       swh.id AS watch_record_id,
                       'season' AS watch_kind,
                       swh.added_at AS watch_added_at,
                       swh.watch_date AS watch_date
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

    @app.get("/")
    def index():
        db = get_db()
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
            WHERE s.is_tracked = 1
              AND s.state IN ('WATCHING', 'ARCHIVED')
            GROUP BY s.id
            ORDER BY CASE s.state WHEN 'WATCHING' THEN 0 ELSE 1 END,
                     s.name COLLATE NOCASE ASC
            """
        ).fetchall()
        watching_shows = [show for show in shows if show["state"] == "WATCHING"]
        archived_shows = [show for show in shows if show["state"] == "ARCHIVED"]
        return render_template(
            "index.html",
            watching_shows=watching_shows,
            archived_shows=archived_shows,
        )

    @app.get("/media/<image_type>/<size>/<path:tmdb_path>")
    def cached_tmdb_image(image_type: str, size: str, tmdb_path: str):
        try:
            image_path, content_type = cached_image(
                get_db(),
                Path(app.config["IMAGE_CACHE_DIR"]),
                image_type,
                size,
                tmdb_path,
                transport=app.config["IMAGE_TRANSPORT"],
            )
        except ImageCacheError:
            abort(404)
        return send_file(
            image_path,
            mimetype=content_type,
            conditional=True,
            max_age=31_536_000,
        )

    @app.get("/api/discover/popular")
    def discover_popular():
        db = get_db()
        cached = db.execute(
            "SELECT payload, refreshed_at FROM tmdb_cache WHERE cache_key = 'popular'"
        ).fetchone()
        now = datetime.now(timezone.utc)
        fresh = False
        if cached is not None:
            refreshed_at = datetime.fromisoformat(cached["refreshed_at"])
            fresh = now - refreshed_at < app.config["TMDB_CACHE_TTL"]
            if fresh:
                return jsonify(
                    results=catalog_results(json.loads(cached["payload"])),
                    refreshed_at=cached["refreshed_at"],
                    cached=True,
                )

        try:
            payload = get_tmdb_client().popular_tv()
        except TMDBError as error:
            if cached is not None:
                return jsonify(
                    results=catalog_results(json.loads(cached["payload"])),
                    refreshed_at=cached["refreshed_at"],
                    cached=True,
                    stale=True,
                )
            return jsonify(error=str(error), configured=bool(app.config["TMDB_READ_ACCESS_TOKEN"])), 503

        refreshed_at = utc_now()
        db.execute(
            """
            INSERT INTO tmdb_cache (cache_key, payload, refreshed_at)
            VALUES ('popular', ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                payload = excluded.payload,
                refreshed_at = excluded.refreshed_at
            """,
            (json.dumps(payload, separators=(",", ":")), refreshed_at),
        )
        db.commit()
        return jsonify(
            results=catalog_results(payload), refreshed_at=refreshed_at, cached=False
        )

    @app.get("/api/discover/search")
    def discover_search():
        query = request.args.get("q", "").strip()
        if len(query) < 2:
            return jsonify(error="Enter at least two characters"), 400
        try:
            payload = get_tmdb_client().search_tv(query)
        except TMDBError as error:
            return jsonify(error=str(error), configured=bool(app.config["TMDB_READ_ACCESS_TOKEN"])), 503
        return jsonify(results=catalog_results(payload))

    @app.post("/api/discover/shows/<int:tmdb_id>/import")
    def import_discovered_show(tmdb_id: int):
        payload = request.get_json(silent=True) or {}
        target_state = payload.get("state")
        if target_state not in {None, "WATCHING", "ARCHIVED"}:
            return jsonify(error="state must be WATCHING, ARCHIVED, or null"), 400
        try:
            show, seasons = get_tmdb_client().show_bundle(tmdb_id)
            if show.get("id") != tmdb_id:
                raise TMDBError("TMDB returned the wrong show")
            show_id, created, newly_tracked = import_or_refresh_show(
                get_db(), show, seasons, target_state
            )
        except TMDBError as error:
            return jsonify(error=str(error)), 503
        except ValueError as error:
            return jsonify(error=str(error)), 502
        imported_show = get_library_show(get_db(), show_id)
        return jsonify(
            show_id=show_id,
            created=created,
            newly_tracked=newly_tracked,
            is_tracked=bool(imported_show["is_tracked"]),
            state=imported_show["state"] if imported_show["is_tracked"] else None,
            card_html=(
                render_template("_show_card_fragment.html", show=imported_show)
                if imported_show["is_tracked"]
                else None
            ),
        )

    @app.post("/api/shows/<int:show_id>/refresh")
    def refresh_show(show_id: int):
        db = get_db()
        payload = request.get_json(silent=True) or {}
        force = payload.get("force", True)
        if type(force) is not bool:
            return jsonify(error="force must be a boolean"), 400
        local_show = db.execute(
            "SELECT tmdb_id, state, is_tracked, tmdb_refreshed_at FROM shows WHERE id = ?",
            (show_id,),
        ).fetchone()
        if local_show is None:
            return jsonify(error="Show not found"), 404
        if not force and show_metadata_is_fresh(local_show["tmdb_refreshed_at"]):
            return jsonify(
                show_id=show_id,
                refreshed=False,
                refreshed_at=local_show["tmdb_refreshed_at"],
            )
        try:
            show, seasons = get_tmdb_client().show_bundle(local_show["tmdb_id"])
            refreshed_id, _created, _newly_tracked = import_or_refresh_show(
                db,
                show,
                seasons,
                local_show["state"] if local_show["is_tracked"] else None,
            )
        except TMDBError as error:
            return jsonify(error=str(error)), 503
        except ValueError as error:
            return jsonify(error=str(error)), 502
        refreshed_show = get_library_show(db, refreshed_id)
        return jsonify(
            show_id=refreshed_id,
            refreshed=True,
            refreshed_at=refreshed_show["tmdb_refreshed_at"],
            card_html=(
                render_template("_show_card_fragment.html", show=refreshed_show)
                if refreshed_show["is_tracked"]
                else None
            ),
        )

    @app.get("/api/shows/<int:show_id>")
    def show_detail_fragment(show_id: int):
        db = get_db()
        show = db.execute(
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
        if show is None:
            abort(404)

        return render_template(
            "show_detail.html",
            show=show,
            activity=get_show_activity(db, show_id),
            metadata_refresh_due=not show_metadata_is_fresh(show["tmdb_refreshed_at"]),
        )

    @app.get("/api/shows/<int:show_id>/seasons")
    def show_seasons_fragment(show_id: int):
        db = get_db()
        if db.execute("SELECT 1 FROM shows WHERE id = ?", (show_id,)).fetchone() is None:
            abort(404)
        seasons = db.execute(
            "SELECT * FROM seasons WHERE show_id = ? ORDER BY season_number",
            (show_id,),
        ).fetchall()
        episodes_by_season = {}
        for season in seasons:
            episodes_by_season[season["id"]] = db.execute(
                """
                SELECT e.id, e.season_id, e.episode_number, e.name, e.overview,
                       e.air_date, e.runtime_minutes, e.still_path,
                       COUNT(wh.id) AS watch_count,
                       MAX(wh.added_at) AS last_watched_at
                FROM episodes e
                LEFT JOIN episode_watch_history wh ON wh.episode_id = e.id
                WHERE e.season_id = ?
                GROUP BY e.id
                ORDER BY e.episode_number
                """,
                (season["id"],),
            ).fetchall()
        return render_template(
            "_show_seasons.html",
            seasons=seasons,
            episodes_by_season=episodes_by_season,
        )

    @app.get("/api/episodes/<int:episode_id>")
    def episode_detail_fragment(episode_id: int):
        db = get_db()
        episode = db.execute(
            """
            SELECT e.*,
                   sn.season_number,
                   sn.name AS season_name,
                   s.id AS show_id,
                   s.name AS show_name,
                   s.status AS show_status,
                   s.genres AS show_genres,
                   COUNT(wh.id) AS watch_count
            FROM episodes e
            JOIN seasons sn ON sn.id = e.season_id
            JOIN shows s ON s.id = sn.show_id
            LEFT JOIN episode_watch_history wh
              ON wh.episode_id = e.id
            WHERE e.id = ?
            GROUP BY e.id
            """,
            (episode_id,),
        ).fetchone()
        if episode is None:
            abort(404)

        watch_log = db.execute(
            """
            SELECT id AS watch_record_id,
                   added_at,
                   watch_date,
                   COALESCE(watch_date, substr(added_at, 1, 10)) AS display_date
            FROM episode_watch_history
            WHERE episode_id = ?
            ORDER BY display_date DESC, added_at DESC, id DESC
            """,
            (episode_id,),
        ).fetchall()
        return render_template(
            "episode_detail.html", episode=episode, watch_log=watch_log
        )

    @app.get("/shows/<int:_show_id>")
    @app.get("/episodes/<int:_episode_id>")
    @app.get("/search")
    def legacy_page_redirect(
        _show_id: int | None = None, _episode_id: int | None = None
    ):
        return redirect(url_for("index"))

    @app.post("/api/shows/<int:show_id>/state")
    def set_show_state(show_id: int):
        payload = request.get_json(silent=True) or {}
        target_state = payload.get("state")
        if target_state not in {"WATCHING", "ARCHIVED"}:
            return jsonify(error="state must be WATCHING or ARCHIVED"), 400

        db = get_db()
        show = db.execute(
            "SELECT id, state, is_tracked FROM shows WHERE id = ?", (show_id,)
        ).fetchone()
        if show is None:
            return jsonify(error="Show not found"), 404

        changed_at = None
        newly_tracked = show["is_tracked"] == 0
        if newly_tracked or show["state"] != target_state:
            changed_at = utc_now()
            timestamp_column = (
                "archived_at" if target_state == "ARCHIVED" else "watching_at"
            )
            db.execute(
                f"""
                UPDATE shows
                SET state = ?, is_tracked = 1, added_at = CASE
                        WHEN is_tracked = 0 THEN ? ELSE added_at END,
                    {timestamp_column} = ?, updated_at = ?
                WHERE id = ?
                """,
                (target_state, changed_at, changed_at, changed_at, show_id),
            )
            db.execute(
                """
                INSERT INTO show_state_history (show_id, state, entered_at)
                VALUES (?, ?, ?)
                """,
                (show_id, target_state, changed_at),
            )
            db.commit()

        library_show = get_library_show(db, show_id)
        return jsonify(
            show_id=show_id,
            state=target_state,
            newly_tracked=newly_tracked,
            card_html=(
                render_template("_show_card_fragment.html", show=library_show)
                if newly_tracked
                else None
            ),
            move_label=("Start watching" if target_state == "ARCHIVED" else "Archive"),
            move_icon=("play_arrow" if target_state == "ARCHIVED" else "archive"),
            activity_title=("Archived" if target_state == "ARCHIVED" else "Started watching"),
            activity_type=("archived" if target_state == "ARCHIVED" else "started_watching"),
            changed_at=changed_at,
        )

    @app.delete("/api/shows/<int:show_id>")
    def remove_show(show_id: int):
        db = get_db()
        cursor = db.execute(
            """
            UPDATE shows
            SET is_tracked = 0, updated_at = ?
            WHERE id = ? AND is_tracked = 1
            """,
            (utc_now(), show_id),
        )
        if cursor.rowcount == 0:
            return jsonify(error="Show not found"), 404
        db.commit()
        return "", 204

    @app.post("/api/episodes/<int:episode_id>/watched")
    def set_episode_watched(episode_id: int):
        payload = request.get_json(silent=True) or {}
        if type(payload.get("watched")) is not bool:
            return jsonify(error="watched must be a boolean"), 400

        db = get_db()
        episode = db.execute(
            """
            SELECT e.id, sn.show_id
            FROM episodes e JOIN seasons sn ON sn.id = e.season_id
            WHERE e.id = ?
            """,
            (episode_id,),
        ).fetchone()
        if episode is None:
            return jsonify(error="Episode not found"), 404

        if payload["watched"]:
            watched = db.execute(
                "SELECT 1 FROM episode_watch_history WHERE episode_id = ? LIMIT 1",
                (episode_id,),
            ).fetchone()
            if watched is None:
                db.execute(
                    "INSERT INTO episode_watch_history (episode_id, added_at) VALUES (?, ?)",
                    (episode_id, utc_now()),
                )
        else:
            db.execute(
                """
                DELETE FROM episode_watch_history
                WHERE id = (
                    SELECT id
                    FROM episode_watch_history
                    WHERE episode_id = ?
                    ORDER BY COALESCE(watch_date, substr(added_at, 1, 10)) DESC,
                             added_at DESC,
                             id DESC
                    LIMIT 1
                )
                """,
                (episode_id,),
            )
        db.commit()

        return jsonify(watch_payload(db, episode["show_id"], episode_id))

    @app.post("/api/episodes/<int:episode_id>/watch-count")
    def change_episode_watch_count(episode_id: int):
        payload = request.get_json(silent=True) or {}
        action = payload.get("action")
        if action not in {"increment", "decrement"}:
            return jsonify(error="action must be increment or decrement"), 400

        db = get_db()
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
            return jsonify(error="Episode not found"), 404

        changed_at = utc_now()
        if action == "increment":
            db.execute(
                """
                INSERT INTO episode_watch_history (episode_id, added_at)
                VALUES (?, ?)
                """,
                (episode_id, changed_at),
            )
        else:
            latest_watch = db.execute(
                """
                SELECT id
                FROM episode_watch_history
                WHERE episode_id = ?
                ORDER BY COALESCE(watch_date, substr(added_at, 1, 10)) DESC,
                         added_at DESC,
                         id DESC
                LIMIT 1
                """,
                (episode_id,),
            ).fetchone()
            if latest_watch is not None:
                db.execute("DELETE FROM episode_watch_history WHERE id = ?", (latest_watch["id"],))
        db.commit()
        return jsonify(watch_payload(db, episode["show_id"], episode_id))

    @app.post("/api/seasons/<int:season_id>/watch-count")
    def change_season_watch_count(season_id: int):
        payload = request.get_json(silent=True) or {}
        action = payload.get("action")
        if action not in {"increment", "decrement"}:
            return jsonify(error="action must be increment or decrement"), 400

        db = get_db()
        season = db.execute(
            "SELECT id, show_id, name FROM seasons WHERE id = ?", (season_id,)
        ).fetchone()
        if season is None:
            return jsonify(error="Season not found"), 404

        episode_ids = [
            row["id"]
            for row in db.execute(
                "SELECT id FROM episodes WHERE season_id = ? ORDER BY episode_number",
                (season_id,),
            ).fetchall()
        ]
        changed_at = utc_now()
        if action == "increment":
            db.executemany(
                """
                INSERT INTO episode_watch_history (episode_id, added_at)
                VALUES (?, ?)
                """,
                [(episode_id, changed_at) for episode_id in episode_ids],
            )
            season_watch_record_id = None
            if episode_ids:
                season_watch_record_id = db.execute(
                    """
                    INSERT INTO season_watch_history (season_id, added_at)
                    VALUES (?, ?)
                    """,
                    (season_id, changed_at),
                ).lastrowid
        else:
            latest_watches = db.execute(
                """
                SELECT id
                FROM (
                    SELECT wh.id,
                           ROW_NUMBER() OVER (
                               PARTITION BY wh.episode_id
                               ORDER BY COALESCE(wh.watch_date, substr(wh.added_at, 1, 10)) DESC,
                                        wh.added_at DESC,
                                        wh.id DESC
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
                """
                SELECT id
                FROM season_watch_history
                WHERE season_id = ?
                ORDER BY COALESCE(watch_date, substr(added_at, 1, 10)) DESC,
                         added_at DESC,
                         id DESC
                LIMIT 1
                """,
                (season_id,),
            ).fetchone()
            season_watch_record_id = (
                latest_season_watch["id"] if latest_season_watch is not None else None
            )
            if latest_season_watch is not None:
                db.execute(
                    "DELETE FROM season_watch_history WHERE id = ?",
                    (latest_season_watch["id"],),
                )
        db.commit()

        episode_counts = [
            {
                "episode_id": episode_id,
                "watch_count": get_episode_watch_count(db, episode_id),
            }
            for episode_id in episode_ids
        ]
        response = watch_payload(db, season["show_id"])
        response.update(
            season_id=season_id,
            season_name=season["name"],
            episodes=episode_counts,
            season_episode_count=len(episode_counts),
            season_watched_count=sum(
                1 for episode in episode_counts if episode["watch_count"] > 0
            ),
            season_watched_at=(changed_at if action == "increment" and episode_ids else None),
            season_watch_record_id=season_watch_record_id,
        )
        return jsonify(response)

    @app.patch("/api/watch-history/<string:watch_kind>/<int:record_id>/date")
    def set_watch_history_date(watch_kind: str, record_id: int):
        table = {
            "episode": "episode_watch_history",
            "season": "season_watch_history",
        }.get(watch_kind)
        if table is None:
            return jsonify(error="Unknown watch history type"), 404

        payload = request.get_json(silent=True) or {}
        watch_date = payload.get("watch_date")
        if watch_date is not None:
            if not isinstance(watch_date, str):
                return jsonify(error="watch_date must be an ISO date or null"), 400
            try:
                date.fromisoformat(watch_date)
            except ValueError:
                return jsonify(error="watch_date must be an ISO date or null"), 400

        db = get_db()
        cursor = db.execute(
            f"UPDATE {table} SET watch_date = ? WHERE id = ?",
            (watch_date, record_id),
        )
        if cursor.rowcount == 0:
            return jsonify(error="Watch entry not found"), 404
        row = db.execute(
            f"""
            SELECT added_at,
                   watch_date,
                   COALESCE(watch_date, substr(added_at, 1, 10)) AS display_date
            FROM {table}
            WHERE id = ?
            """,
            (record_id,),
        ).fetchone()
        db.commit()
        return jsonify(
            watch_kind=watch_kind,
            record_id=record_id,
            added_at=row["added_at"],
            watch_date=row["watch_date"],
            display_date=row["display_date"],
        )

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("404.html", active_nav=None), 404

    with app.app_context():
        db = get_db()
        migrate_watch_history_tables(db)
        schema = (BASE_DIR / "schema.sql").read_text(encoding="utf-8")
        db.executescript(schema)
        migrate_database(db)
        db.executescript(schema)
        db.execute("PRAGMA optimize")

    return app



app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=False)
