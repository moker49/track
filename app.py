from __future__ import annotations

import os
import json
import sqlite3
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.request import urlopen

from flask import Flask, abort, g, jsonify, redirect, render_template, request, send_file, url_for
from dotenv import load_dotenv

from database import connect_database, initialize_database
from domain import (
    TRACKING_ACTIVE,
    TRACKING_ARCHIVED,
    TRACKING_STATES,
    effective_watch_date_sql,
    move_presentation,
    progress_presentation,
)
from image_cache import ImageCacheError, cached_image
from tmdb import TMDBClient, TMDBError
from tmdb_import import import_or_refresh_show
from queries import (
    get_catch_up_episodes,
    get_diary_page,
    get_library_show,
    get_movie_library,
    get_movie_activity,
    get_show_progress,
    get_show_activity,
    get_statistics,
    get_tv_library_shows,
    get_upcoming_episodes,
)
from refresh_service import refresh_stale_tracked_shows as refresh_stale_records
from watch_service import (
    WatchNotFoundError,
    change_episode_watch_count as change_episode_watch_count_record,
    change_season_watch_count as change_season_watch_count_records,
    set_episode_watched as set_episode_watched_record,
    set_watch_history_date as set_watch_history_date_record,
)


BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "instance" / "track.db"
ASSET_VERSION = str(
    max(
        (BASE_DIR / "static" / filename).stat().st_mtime_ns
        for filename in ("app.css", "app.js")
    )
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def precise_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def create_app(test_config: dict | None = None) -> Flask:
    dotenv_path = (test_config or {}).get("DOTENV_PATH", BASE_DIR / ".env")
    load_dotenv(dotenv_path=dotenv_path, override=False)
    app = Flask(__name__)
    app.config.from_mapping(
        DATABASE=str(DATABASE),
        TMDB_READ_ACCESS_TOKEN=os.environ.get("TMDB_READ_ACCESS_TOKEN", ""),
        SHOW_METADATA_TTL=timedelta(days=1),
        TMDB_CLIENT_FACTORY=TMDBClient,
        IMAGE_CACHE_DIR=None,
        IMAGE_TRANSPORT=urlopen,
        BACKGROUND_REFRESH_INTERVAL_SECONDS=60 * 60,
    )
    if test_config:
        app.config.update(test_config)

    app.jinja_env.globals.update(
        progress_for=progress_presentation,
        move_for=move_presentation,
    )

    if app.config["IMAGE_CACHE_DIR"] is None:
        app.config["IMAGE_CACHE_DIR"] = str(
            Path(app.config["DATABASE"]).parent / "images"
        )

    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)

    def get_db() -> sqlite3.Connection:
        if "db" not in g:
            g.db = connect_database(app.config["DATABASE"])
        return g.db

    @app.teardown_appcontext
    def close_db(_error=None) -> None:
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.context_processor
    def inject_year() -> dict:
        return {
            "current_year": datetime.now().year,
            "asset_version": ASSET_VERSION,
        }

    def get_tmdb_client() -> TMDBClient:
        return app.config["TMDB_CLIENT_FACTORY"](
            app.config["TMDB_READ_ACCESS_TOKEN"]
        )

    def request_local_date() -> date:
        value = request.headers.get("X-Track-Local-Date", "")
        try:
            return date.fromisoformat(value) if value else datetime.now().astimezone().date()
        except ValueError:
            return datetime.now().astimezone().date()

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

    def movie_catalog_results(payload: dict) -> list[dict]:
        results = []
        for item in payload.get("results", []):
            if not isinstance(item.get("id"), int):
                continue
            results.append({"tmdb_id": item["id"], "name": item.get("title") or "Untitled movie",
                            "overview": item.get("overview") or "No overview available.",
                            "poster_path": item.get("poster_path"), "first_air_date": item.get("release_date")})
        if results:
            placeholders = ",".join("?" for _ in results)
            existing = {row["tmdb_id"] for row in get_db().execute(
                f"SELECT tmdb_id FROM movies WHERE is_tracked = 1 AND tmdb_id IN ({placeholders})",
                [item["tmdb_id"] for item in results],
            )}
            removed = {row["tmdb_id"] for row in get_db().execute(
                f"""SELECT m.tmdb_id FROM movies m WHERE m.is_tracked = 0
                    AND m.tmdb_id IN ({placeholders})
                    AND EXISTS (SELECT 1 FROM movie_state_history h WHERE h.movie_id = m.id)""",
                [item["tmdb_id"] for item in results],
            )}
            for item in results:
                item["is_tracked"] = item["tmdb_id"] in existing
                item["is_removed"] = item["tmdb_id"] in removed
        return results







    @app.get("/")
    def index():
        db = get_db()
        local_date = request_local_date()
        active_shows, archived_shows = get_tv_library_shows(db)
        movies = get_movie_library(db)
        diary_entries, diary_has_more = get_diary_page(db)
        return render_template(
            "index.html",
            catch_up_episodes=get_catch_up_episodes(db, local_date=local_date),
            upcoming_episodes=get_upcoming_episodes(db, local_date),
            diary_entries=diary_entries,
            diary_page=1,
            diary_has_more=diary_has_more,
            statistics=get_statistics(db, local_date),
            active_shows=active_shows,
            archived_shows=archived_shows,
            movies=movies,
        )

    @app.get("/api/tv")
    def tv_fragment():
        active_shows, archived_shows = get_tv_library_shows(get_db())
        return render_template(
            "tv.html",
            active_shows=active_shows,
            archived_shows=archived_shows,
        )

    @app.get("/api/movies")
    def movies_fragment():
        return render_template("movies.html", movies=get_movie_library(get_db()))

    @app.get("/api/schedule")
    def schedule_fragment():
        db = get_db()
        local_date = request_local_date()
        return render_template(
            "_schedule_content.html",
            catch_up_episodes=get_catch_up_episodes(db, local_date=local_date),
            upcoming_episodes=get_upcoming_episodes(db, local_date),
        )

    @app.get("/api/profile/diary")
    def diary_fragment():
        try:
            page = int(request.args.get("page", "1"))
        except ValueError:
            abort(400)
        if page < 1:
            abort(400)
        diary_entries, diary_has_more = get_diary_page(get_db(), page=page)
        if page > 1:
            return render_template(
                "_diary_page.html",
                diary_entries=diary_entries,
                diary_page=page,
                diary_has_more=diary_has_more,
            )
        return render_template(
            "_diary_content.html",
            diary_entries=diary_entries,
            diary_page=page,
            diary_has_more=diary_has_more,
        )

    @app.get("/api/profile/statistics")
    def statistics_fragment():
        return render_template(
            "_statistics_content.html",
            statistics=get_statistics(get_db(), request_local_date()),
        )

    @app.get("/api/schedule/shows/<int:show_id>/catch-up")
    def schedule_catch_up_card(show_id: int):
        episodes = get_catch_up_episodes(
            get_db(), show_id, local_date=request_local_date()
        )
        if not episodes:
            return "", 204
        return render_template(
            "_schedule_timeline_item_fragment.html",
            episode=episodes[0],
            mode="catch-up",
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

    @app.get("/api/tv/search")
    def tv_search():
        query = request.args.get("q", "").strip()
        if not query:
            return jsonify(error="Enter a search term"), 400
        try:
            payload = get_tmdb_client().search_tv(query)
        except TMDBError as error:
            return jsonify(error=str(error), configured=bool(app.config["TMDB_READ_ACCESS_TOKEN"])), 503
        results = [result for result in catalog_results(payload) if not result["is_tracked"]]
        return jsonify(results=results)

    @app.get("/api/movies/search")
    def movie_search():
        query = request.args.get("q", "").strip()
        if not query: return jsonify(error="Enter a search term"), 400
        try: payload = get_tmdb_client().search_movie(query)
        except TMDBError as error: return jsonify(error=str(error)), 503
        return jsonify(results=[item for item in movie_catalog_results(payload) if not item["is_tracked"]])

    @app.post("/api/movies/<int:tmdb_id>/import")
    def import_movie(tmdb_id: int):
        payload = request.get_json(silent=True) or {}
        watched = bool(payload.get("watched"))
        watch_date = payload.get("watch_date")
        try: movie = get_tmdb_client().movie(tmdb_id)
        except TMDBError as error: return jsonify(error=str(error)), 503
        if movie.get("id") != tmdb_id: return jsonify(error="TMDB returned the wrong movie"), 502
        now = utc_now()
        db = get_db()
        db.execute("""INSERT INTO movies (tmdb_id,title,original_title,overview,poster_path,backdrop_path,release_date,runtime_minutes,status,genres,original_language,state,added_at,active_at,archived_at,updated_at,tmdb_refreshed_at,tmdb_payload)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(tmdb_id) DO UPDATE SET is_tracked=1,state=excluded.state,updated_at=excluded.updated_at""",
          (tmdb_id, movie.get("title") or "Untitled movie", movie.get("original_title"), movie.get("overview"), movie.get("poster_path"), movie.get("backdrop_path"), movie.get("release_date"), movie.get("runtime"), movie.get("status"), ", ".join(g.get("name", "") for g in movie.get("genres", [])), movie.get("original_language"), TRACKING_ACTIVE, now, now, None, now, now, json.dumps(movie)))
        db.commit()
        movie_id = db.execute("SELECT id FROM movies WHERE tmdb_id = ?", (tmdb_id,)).fetchone()["id"]
        db.execute("INSERT INTO movie_state_history (movie_id, state, entered_at) SELECT ?, ?, ? WHERE NOT EXISTS (SELECT 1 FROM movie_state_history WHERE movie_id = ?)", (movie_id, TRACKING_ACTIVE, now, movie_id))
        if watched:
            db.execute("INSERT INTO movie_watch_history (movie_id, added_at, watch_date, show_in_diary) SELECT ?, ?, ?, ? WHERE NOT EXISTS (SELECT 1 FROM movie_watch_history WHERE movie_id = ?)", (movie_id, now, watch_date, int(bool(watch_date)), movie_id))
        db.commit()
        return jsonify(ok=True, movie_id=movie_id)

    @app.get("/api/movies/tmdb/<int:tmdb_id>/preview")
    def movie_preview_fragment(tmdb_id: int):
        try:
            payload = get_tmdb_client().movie(tmdb_id)
        except TMDBError as error:
            return jsonify(error=str(error)), 503
        if payload.get("id") != tmdb_id:
            return jsonify(error="TMDB returned the wrong movie"), 502
        saved_movie = get_db().execute(
            "SELECT id, state, is_tracked, liked FROM movies WHERE tmdb_id = ?", (tmdb_id,)
        ).fetchone()
        movie = {
            "id": saved_movie["id"] if saved_movie else None,
            "tmdb_id": tmdb_id,
            "title": payload.get("title") or "Untitled movie",
            "overview": payload.get("overview"),
            "poster_path": payload.get("poster_path"),
            "release_date": payload.get("release_date"),
            "runtime_minutes": payload.get("runtime"),
            "genres": ", ".join(genre.get("name", "") for genre in payload.get("genres", [])),
            "state": saved_movie["state"] if saved_movie else TRACKING_ACTIVE,
            "is_tracked": bool(saved_movie["is_tracked"]) if saved_movie else False,
            "liked": bool(saved_movie["liked"]) if saved_movie else False,
            "watch_count": 0,
        }
        return render_template("movie_detail.html", movie=movie, activity=[])

    @app.get("/api/movies/<int:movie_id>")
    def movie_detail_fragment(movie_id: int):
        movie = get_db().execute(
            """
            SELECT m.*, COUNT(mwh.id) AS watch_count
            FROM movies m
            LEFT JOIN movie_watch_history mwh ON mwh.movie_id = m.id
            WHERE m.id = ?
            GROUP BY m.id
            """,
            (movie_id,),
        ).fetchone()
        if movie is None:
            abort(404)
        return render_template("movie_detail.html", movie=movie, activity=get_movie_activity(get_db(), movie_id))

    @app.post("/api/movies/<int:movie_id>/liked")
    def set_movie_liked(movie_id: int):
        liked = bool((request.get_json(silent=True) or {}).get("liked"))
        cursor = get_db().execute(
            "UPDATE movies SET liked = ?, updated_at = ? WHERE id = ?",
            (int(liked), utc_now(), movie_id),
        )
        if cursor.rowcount == 0:
            return jsonify(error="Movie not found"), 404
        get_db().commit()
        return jsonify(movie_id=movie_id, liked=liked)

    @app.post("/api/movies/tmdb/<int:tmdb_id>/liked")
    def set_preview_movie_liked(tmdb_id: int):
        liked = bool((request.get_json(silent=True) or {}).get("liked"))
        db = get_db()
        existing = db.execute(
            "SELECT id FROM movies WHERE tmdb_id = ?", (tmdb_id,)
        ).fetchone()
        if existing:
            db.execute(
                "UPDATE movies SET liked = ?, updated_at = ? WHERE id = ?",
                (int(liked), utc_now(), existing["id"]),
            )
            movie_id = existing["id"]
        else:
            try:
                movie = get_tmdb_client().movie(tmdb_id)
            except TMDBError as error:
                return jsonify(error=str(error)), 503
            if movie.get("id") != tmdb_id:
                return jsonify(error="TMDB returned the wrong movie"), 502
            now = utc_now()
            cursor = db.execute(
                """INSERT INTO movies (tmdb_id,title,original_title,overview,poster_path,backdrop_path,
                  release_date,runtime_minutes,status,genres,original_language,state,is_tracked,liked,
                  added_at,updated_at,tmdb_refreshed_at,tmdb_payload)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?,?,?)""",
                (tmdb_id, movie.get("title") or "Untitled movie", movie.get("original_title"),
                 movie.get("overview"), movie.get("poster_path"), movie.get("backdrop_path"),
                 movie.get("release_date"), movie.get("runtime"), movie.get("status"),
                 ", ".join(genre.get("name", "") for genre in movie.get("genres", [])),
                 movie.get("original_language"), TRACKING_ACTIVE, int(liked), now, now, now,
                 json.dumps(movie)),
            )
            movie_id = cursor.lastrowid
        db.commit()
        return jsonify(movie_id=movie_id, liked=liked)

    @app.post("/api/movies/<int:movie_id>/state")
    def set_movie_state(movie_id: int):
        target_state = (request.get_json(silent=True) or {}).get("state")
        if target_state not in TRACKING_STATES:
            return jsonify(error="state must be ACTIVE or ARCHIVED"), 400
        db = get_db()
        movie = db.execute("SELECT id, state, is_tracked FROM movies WHERE id = ?", (movie_id,)).fetchone()
        if movie is None or not movie["is_tracked"]:
            return jsonify(error="Movie not found"), 404
        now = utc_now()
        timestamp_column = "archived_at" if target_state == TRACKING_ARCHIVED else "active_at"
        db.execute(
            f"UPDATE movies SET state = ?, {timestamp_column} = ?, updated_at = ? WHERE id = ?",
            (target_state, now, now, movie_id),
        )
        if movie["state"] != target_state:
            db.execute("INSERT INTO movie_state_history (movie_id, state, entered_at) VALUES (?, ?, ?)", (movie_id, target_state, now))
        db.commit()
        return jsonify(movie_id=movie_id, state=target_state)

    @app.delete("/api/movies/<int:movie_id>")
    def remove_movie(movie_id: int):
        cursor = get_db().execute(
            "UPDATE movies SET is_tracked = 0, updated_at = ? WHERE id = ? AND is_tracked = 1",
            (utc_now(), movie_id),
        )
        if cursor.rowcount == 0:
            return jsonify(error="Movie not found"), 404
        get_db().commit()
        return "", 204

    @app.post("/api/movies/<int:movie_id>/watch-count")
    def change_movie_watch_count(movie_id: int):
        action = (request.get_json(silent=True) or {}).get("action")
        if action not in {"increment", "decrement"}:
            return jsonify(error="action must be increment or decrement"), 400
        db = get_db()
        movie = db.execute("SELECT id FROM movies WHERE id = ? AND is_tracked = 1", (movie_id,)).fetchone()
        if movie is None:
            return jsonify(error="Movie not found"), 404
        if action == "increment":
            changed_at = precise_utc_now()
            cursor = db.execute(
                "INSERT INTO movie_watch_history (movie_id, added_at) VALUES (?, ?)",
                (movie_id, changed_at),
            )
            watch_record_id = cursor.lastrowid
        else:
            watch = db.execute("SELECT id FROM movie_watch_history WHERE movie_id = ? ORDER BY added_at DESC, id DESC LIMIT 1", (movie_id,)).fetchone()
            if watch is None:
                return jsonify(error="Movie has not been watched"), 409
            db.execute("DELETE FROM movie_watch_history WHERE id = ?", (watch["id"],))
            watch_record_id = watch["id"]
            changed_at = None
        db.commit()
        watch_count = db.execute("SELECT COUNT(*) AS count FROM movie_watch_history WHERE movie_id = ?", (movie_id,)).fetchone()["count"]
        return jsonify(movie_id=movie_id, watch_count=watch_count, action=action,
                       watch_record_id=watch_record_id, changed_at=changed_at)

    @app.post("/api/movies/<int:movie_id>/watched")
    def set_movie_watched_without_diary(movie_id: int):
        watched = (request.get_json(silent=True) or {}).get("watched")
        if not isinstance(watched, bool):
            return jsonify(error="watched must be a boolean"), 400
        db = get_db()
        cursor = db.execute(
            "UPDATE movies SET is_watched_without_diary = ?, updated_at = ? WHERE id = ? AND is_tracked = 1",
            (int(watched), utc_now(), movie_id),
        )
        if cursor.rowcount == 0:
            return jsonify(error="Movie not found"), 404
        db.commit()
        row = db.execute(
            "SELECT COUNT(*) + is_watched_without_diary AS watch_count FROM movies m LEFT JOIN movie_watch_history mwh ON mwh.movie_id = m.id WHERE m.id = ? GROUP BY m.id",
            (movie_id,),
        ).fetchone()
        return jsonify(movie_id=movie_id, watched=watched, watch_count=row["watch_count"])

    @app.post("/api/tv/shows/<int:tmdb_id>/import")
    def import_tv_show(tmdb_id: int):
        payload = request.get_json(silent=True) or {}
        target_state = payload.get("state")
        if target_state is not None and target_state not in TRACKING_STATES:
            return jsonify(error="state must be ACTIVE, ARCHIVED, or null"), 400
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

    def refresh_stale_tracked_show_records(
        include_card_html: bool = False,
    ) -> dict:
        return refresh_stale_records(
            get_db(),
            client_factory=get_tmdb_client,
            metadata_is_fresh=show_metadata_is_fresh,
            include_card_html=include_card_html,
            render_card=(
                lambda show: render_template("_show_card_fragment.html", show=show)
            ),
        )


    app.extensions["refresh_stale_tracked_shows"] = (
        refresh_stale_tracked_show_records
    )

    @app.post("/api/shows/refresh-stale")
    def refresh_stale_tracked_shows():
        return jsonify(refresh_stale_tracked_show_records(include_card_html=True))

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
              AND e.air_date <= ?
            LEFT JOIN episode_watch_history wh ON wh.episode_id = e.id
            WHERE s.id = ?
            GROUP BY s.id
            """,
            (request_local_date().isoformat(), show_id),
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
            """
            WITH episode_counts AS (
                SELECT e.id,
                       e.season_id,
                       COUNT(wh.id) AS watch_count
                FROM episodes e
                LEFT JOIN episode_watch_history wh ON wh.episode_id = e.id
                WHERE e.season_id IN (
                    SELECT id FROM seasons WHERE show_id = ?
                )
                GROUP BY e.id
            )
            SELECT sn.*,
                   COUNT(ec.id) AS episode_count,
                   COALESCE(SUM(CASE WHEN ec.watch_count > 0 THEN 1 ELSE 0 END), 0)
                       AS watched_count,
                   CASE
                       WHEN COUNT(ec.id) > 0
                        AND SUM(CASE WHEN ec.watch_count > 0 THEN 1 ELSE 0 END) = COUNT(ec.id)
                       THEN MIN(ec.watch_count)
                       ELSE 0
                   END AS minimum_watch_count
            FROM seasons sn
            LEFT JOIN episode_counts ec ON ec.season_id = sn.id
            WHERE sn.show_id = ?
            GROUP BY sn.id
            ORDER BY CASE WHEN sn.season_number = 0 THEN 1 ELSE 0 END,
                     sn.season_number
            """,
            (show_id, show_id),
        ).fetchall()
        return render_template("_show_seasons.html", seasons=seasons)

    @app.get("/api/seasons/<int:season_id>/episodes")
    def season_episodes_fragment(season_id: int):
        db = get_db()
        if db.execute("SELECT 1 FROM seasons WHERE id = ?", (season_id,)).fetchone() is None:
            abort(404)
        episodes = db.execute(
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
            (season_id,),
        ).fetchall()
        return render_template("_season_episodes.html", episodes=episodes)

    @app.get("/api/episodes/<int:episode_id>")
    def episode_detail_fragment(episode_id: int):
        db = get_db()
        episode = db.execute(
            """
            SELECT e.*,
                   sn.season_number,
                   sn.name AS season_name,
                   sn.is_progress_counted,
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

        episode = dict(episode)
        neighbor_parameters = (
            episode["show_id"],
            episode["is_progress_counted"],
            episode["season_number"],
            episode["season_number"],
            episode["episode_number"],
        )
        previous_episode = db.execute(
            """
            SELECT e.id
            FROM episodes e
            JOIN seasons sn ON sn.id = e.season_id
            WHERE sn.show_id = ?
              AND sn.is_progress_counted = ?
              AND (sn.season_number < ?
                   OR (sn.season_number = ? AND e.episode_number < ?))
            ORDER BY sn.season_number DESC, e.episode_number DESC
            LIMIT 1
            """,
            neighbor_parameters,
        ).fetchone()
        next_episode = db.execute(
            """
            SELECT e.id
            FROM episodes e
            JOIN seasons sn ON sn.id = e.season_id
            WHERE sn.show_id = ?
              AND sn.is_progress_counted = ?
              AND (sn.season_number > ?
                   OR (sn.season_number = ? AND e.episode_number > ?))
            ORDER BY sn.season_number, e.episode_number
            LIMIT 1
            """,
            neighbor_parameters,
        ).fetchone()
        episode["previous_episode_id"] = previous_episode["id"] if previous_episode else None
        episode["next_episode_id"] = next_episode["id"] if next_episode else None

        watch_log = db.execute(
            f"""
            SELECT id AS watch_record_id,
                   added_at,
                   watch_date,
                   show_in_diary,
                   {effective_watch_date_sql()} AS display_date
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
        if target_state not in TRACKING_STATES:
            return jsonify(error="state must be ACTIVE or ARCHIVED"), 400

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
                "archived_at" if target_state == TRACKING_ARCHIVED else "active_at"
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
        move = move_presentation(target_state)
        return jsonify(
            show_id=show_id,
            state=target_state,
            newly_tracked=newly_tracked,
            card_html=(
                render_template("_show_card_fragment.html", show=library_show)
                if newly_tracked
                else None
            ),
            move_label=move.label,
            move_icon=move.icon,
            activity_title=("Archived" if target_state == TRACKING_ARCHIVED else "Made active"),
            activity_type=("archived" if target_state == TRACKING_ARCHIVED else "activated"),
            changed_at=changed_at,
        )

    @app.post("/api/shows/<int:show_id>/watched")
    def set_show_watched_without_diary(show_id: int):
        watched = (request.get_json(silent=True) or {}).get("watched")
        if not isinstance(watched, bool):
            return jsonify(error="watched must be a boolean"), 400
        db = get_db()
        show = db.execute(
            "SELECT id FROM shows WHERE id = ? AND is_tracked = 1", (show_id,)
        ).fetchone()
        if show is None:
            return jsonify(error="Show not found"), 404
        db.execute(
            """
            UPDATE episodes
            SET is_watched_without_diary = ?
            WHERE id IN (
                SELECT e.id
                FROM episodes e
                JOIN seasons sn ON sn.id = e.season_id
                WHERE sn.show_id = ?
                  AND sn.is_progress_counted = 1
                  AND e.air_date IS NOT NULL
                  AND e.air_date <= ?
            )
            """,
            (int(watched), show_id, request_local_date().isoformat()),
        )
        db.commit()
        progress = get_show_progress(db, show_id)
        return jsonify(show_id=show_id, watched=watched,
                       watched_count=progress["watched_count"],
                       episode_count=progress["episode_count"])

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
        try:
            return jsonify(
                set_episode_watched_record(get_db(), episode_id, payload["watched"])
            )
        except WatchNotFoundError as error:
            return jsonify(error=str(error)), 404


    @app.post("/api/episodes/<int:episode_id>/watch-count")
    def change_episode_watch_count(episode_id: int):
        payload = request.get_json(silent=True) or {}
        action = payload.get("action")
        if action not in {"increment", "decrement"}:
            return jsonify(error="action must be increment or decrement"), 400
        try:
            return jsonify(
                change_episode_watch_count_record(get_db(), episode_id, action)
            )
        except WatchNotFoundError as error:
            return jsonify(error=str(error)), 404


    @app.post("/api/episodes/<int:episode_id>/skip")
    def skip_episode(episode_id: int):
        db = get_db()
        episode = db.execute(
            """
            SELECT e.id, sn.show_id
            FROM episodes e
            JOIN seasons sn ON sn.id = e.season_id
            JOIN shows s ON s.id = sn.show_id
            WHERE e.id = ?
              AND e.air_date IS NOT NULL
              AND e.air_date <= ?
              AND sn.is_progress_counted = 1
              AND s.is_tracked = 1
              AND s.state = 'ACTIVE'
              AND NOT EXISTS (
                  SELECT 1 FROM episode_watch_history wh
                  WHERE wh.episode_id = e.id
              )
            """,
            (episode_id, request_local_date().isoformat()),
        ).fetchone()
        if episode is None:
            return jsonify(error="Episode cannot be skipped"), 409
        db.execute(
            """
            INSERT INTO episode_skips (episode_id, skipped_at)
            VALUES (?, ?)
            ON CONFLICT(episode_id) DO UPDATE SET skipped_at = excluded.skipped_at
            """,
            (episode_id, precise_utc_now()),
        )
        db.commit()
        return jsonify(show_id=episode["show_id"], episode_id=episode_id)

    @app.delete("/api/episodes/<int:episode_id>/skip")
    def undo_skip_episode(episode_id: int):
        db = get_db()
        row = db.execute(
            """
            SELECT sn.show_id
            FROM episodes e
            JOIN seasons sn ON sn.id = e.season_id
            WHERE e.id = ?
            """,
            (episode_id,),
        ).fetchone()
        if row is None:
            return jsonify(error="Episode not found"), 404
        cursor = db.execute(
            "DELETE FROM episode_skips WHERE episode_id = ?", (episode_id,)
        )
        db.commit()
        if cursor.rowcount == 0:
            return jsonify(error="Episode is not skipped"), 404
        return jsonify(show_id=row["show_id"], episode_id=episode_id)

    @app.post("/api/seasons/<int:season_id>/watch-count")
    def change_season_watch_count(season_id: int):
        payload = request.get_json(silent=True) or {}
        action = payload.get("action")
        if action not in {"increment", "decrement"}:
            return jsonify(error="action must be increment or decrement"), 400
        try:
            return jsonify(
                change_season_watch_count_records(get_db(), season_id, action)
            )
        except WatchNotFoundError as error:
            return jsonify(error=str(error)), 404


    @app.patch("/api/watch-history/<string:watch_kind>/<int:record_id>/date")
    def set_watch_history_date(watch_kind: str, record_id: int):
        if watch_kind not in {"episode", "season", "movie"}:
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
        if watch_kind == "movie":
            db = get_db()
            row = db.execute(
                "SELECT id, added_at FROM movie_watch_history WHERE id = ?", (record_id,)
            ).fetchone()
            if row is None:
                return jsonify(error="Movie watch history not found"), 404
            db.execute("UPDATE movie_watch_history SET watch_date = ?, show_in_diary = 1 WHERE id = ?", (watch_date, record_id))
            db.commit()
            return jsonify(
                watch_kind="movie", watch_record_id=record_id, added_at=row["added_at"],
                watch_date=watch_date, display_date=watch_date or row["added_at"][:10],
            )
        try:
            return jsonify(
                set_watch_history_date_record(
                    get_db(), watch_kind, record_id, watch_date
                )
            )
        except WatchNotFoundError as error:
            return jsonify(error=str(error)), 404

    @app.patch("/api/watch-history/<string:watch_kind>/<int:record_id>/diary")
    def set_watch_history_diary_visibility(watch_kind: str, record_id: int):
        table = {"episode": "episode_watch_history", "season": "season_watch_history", "movie": "movie_watch_history"}.get(watch_kind)
        visible = (request.get_json(silent=True) or {}).get("show_in_diary")
        if table is None or not isinstance(visible, bool):
            return jsonify(error="Invalid diary setting"), 400
        cursor = get_db().execute(f"UPDATE {table} SET show_in_diary = ? WHERE id = ?", (int(visible), record_id))
        if cursor.rowcount == 0:
            return jsonify(error="Watch entry not found"), 404
        get_db().commit()
        return jsonify(watch_kind=watch_kind, watch_record_id=record_id, show_in_diary=visible)

    @app.patch("/api/seasons/<int:season_id>/diary")
    def toggle_season_diary_visibility(season_id: int):
        db = get_db()
        rows = db.execute(
            "SELECT h.show_in_diary FROM episode_watch_history h JOIN episodes e ON e.id = h.episode_id WHERE e.season_id = ?",
            (season_id,),
        ).fetchall()
        if not rows:
            return jsonify(error="Season has no watch history"), 409
        visible = any(not row["show_in_diary"] for row in rows)
        db.execute(
            "UPDATE episode_watch_history SET show_in_diary = ? WHERE episode_id IN (SELECT id FROM episodes WHERE season_id = ?)",
            (int(visible), season_id),
        )
        db.commit()
        return jsonify(season_id=season_id, show_in_diary=visible)


    @app.errorhandler(404)
    def not_found(_error):
        return render_template("404.html", active_nav=None), 404

    with app.app_context():
        db = get_db()
        initialize_database(db, BASE_DIR / "schema.sql")

    return app


def start_background_refresh(app: Flask) -> tuple[threading.Thread, threading.Event]:
    stop_event = threading.Event()
    interval = app.config["BACKGROUND_REFRESH_INTERVAL_SECONDS"]

    def refresh_worker() -> None:
        while not stop_event.is_set():
            try:
                with app.app_context():
                    result = app.extensions["refresh_stale_tracked_shows"]()
                if result["refreshed"] or result["failures"]:
                    app.logger.info(
                        "Tracked-show refresh completed: %s refreshed, %s failed, %s fresh",
                        len(result["refreshed"]),
                        len(result["failures"]),
                        result["skipped"],
                    )
            except Exception:
                app.logger.exception("Tracked-show background refresh failed")
            stop_event.wait(interval)

    thread = threading.Thread(
        target=refresh_worker,
        name="track-metadata-refresh",
        daemon=True,
    )
    thread.start()
    return thread, stop_event



app = create_app()


if __name__ == "__main__":
    _refresh_thread, _refresh_stop = start_background_refresh(app)
    try:
        app.run(host="0.0.0.0", port=5050, debug=False)
    finally:
        _refresh_stop.set()
        _refresh_thread.join(timeout=5)
