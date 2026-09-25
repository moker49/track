from __future__ import annotations

import os
import json
import sqlite3
import threading
from contextlib import closing
from queue import Full, Queue
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.request import urlopen

from flask import Flask, abort, g, jsonify, redirect, render_template, request, send_file, url_for
from dotenv import load_dotenv

from database import (
    connect_database,
    initialize_database,
    normalize_movie_added_timestamps,
    unknown_log_timestamp,
)
from domain import (
    TRACKING_ACTIVE,
    TRACKING_ARCHIVED,
    TRACKING_STATES,
    effective_diary_date_sql,
    move_presentation,
    progress_presentation,
)
from image_cache import ImageCacheError, cached_image
from cast_service import replace_media_cast
from tmdb import TMDBClient, TMDBError
from tmdb_import import import_or_refresh_show, refresh_movie_metadata
from queries import (
    get_catch_up_episodes,
    get_diary_page,
    get_diary_monthly_summary,
    get_library_show,
    get_movie_library,
    get_movie_activity,
    get_show_progress,
    watch_payload,
    get_show_activity,
    get_statistics,
    get_tv_library_shows,
    get_upcoming_episodes,
)
from refresh_service import (
    clear_refresh_failure,
    record_refresh_failure,
    refresh_retry_after,
    refresh_stale_tracked_movies as refresh_stale_movie_records,
    refresh_stale_tracked_shows as refresh_stale_records,
)
from watch_service import (
    WatchNotFoundError,
    create_episode_log,
    create_season_log,
    remove_log,
    set_log_diary_date,
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
        MOVIE_METADATA_TTL=timedelta(days=1),
        SHOW_METADATA_FAILURE_BACKOFFS=(
            timedelta(hours=1),
            timedelta(hours=6),
            timedelta(hours=24),
        ),
        TMDB_CLIENT_FACTORY=TMDBClient,
        IMAGE_CACHE_DIR=None,
        IMAGE_TRANSPORT=urlopen,
        CAST_HYDRATION_WORKERS=2,
        CAST_HYDRATION_QUEUE_SIZE=64,
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

    cast_hydration_lock = threading.Lock()
    cast_hydration_keys: set[tuple[str, int]] = set()
    cast_hydration_queue: Queue[tuple[str, int, int] | None] = Queue(
        maxsize=app.config["CAST_HYDRATION_QUEUE_SIZE"]
    )
    cast_hydration_workers: list[threading.Thread] = []
    cast_hydration_closed = False

    def set_cast_sync_status(
        db: sqlite3.Connection,
        media_type: str,
        media_id: int,
        status: str,
        error: str | None = None,
    ) -> None:
        table = "show_cast_sync" if media_type == "show" else "movie_cast_sync"
        column = "show_id" if media_type == "show" else "movie_id"
        db.execute(
            f"""
            INSERT INTO {table} ({column}, status, updated_at, error)
            VALUES (?, ?, ?, ?)
            ON CONFLICT({column}) DO UPDATE SET
                status = excluded.status,
                updated_at = excluded.updated_at,
                error = excluded.error
            """,
            (media_id, status, utc_now(), error),
        )
        db.commit()

    def hydrate_cast(media_type: str, media_id: int, tmdb_id: int) -> None:
        key = (media_type, media_id)
        try:
            db = connect_database(app.config["DATABASE"])
            try:
                client = get_tmdb_client()
                try:
                    credits = (
                        client.show_credits(tmdb_id)
                        if media_type == "show"
                        else client.movie_credits(tmdb_id)
                    )
                except TMDBError as error:
                    if error.status_code != 404:
                        raise
                    # TMDB can have a valid title without a credits resource yet.
                    # Keep any previously saved cast until credits become available.
                    app.logger.info(
                        "TMDB credits unavailable for %s %s (TMDB %s)",
                        media_type, media_id, tmdb_id,
                    )
                    set_cast_sync_status(db, media_type, media_id, "ready")
                    return
                replace_media_cast(
                    db, media_type=media_type, media_id=media_id, credits=credits
                )
                cast_table = "show_cast" if media_type == "show" else "movie_cast"
                media_column = "show_id" if media_type == "show" else "movie_id"
                profile_rows = db.execute(
                    f"""
                    SELECT DISTINCT a.profile_path
                    FROM {cast_table} c
                    JOIN actors a ON a.id = c.actor_id
                    WHERE c.{media_column} = ? AND a.profile_path IS NOT NULL
                    """,
                    (media_id,),
                ).fetchall()
                for profile in profile_rows:
                    try:
                        cached_image(
                            db,
                            Path(app.config["IMAGE_CACHE_DIR"]),
                            "profile",
                            "w185",
                            profile["profile_path"],
                            transport=app.config["IMAGE_TRANSPORT"],
                        )
                    except ImageCacheError:
                        # A missing portrait must not discard otherwise valid cast data.
                        app.logger.info("Could not cache cast portrait for %s", media_type)
                set_cast_sync_status(db, media_type, media_id, "ready")
            except Exception as error:
                # Cast is supplemental metadata and must never affect detail loading.
                app.logger.exception("Cast hydration failed for %s %s", media_type, media_id)
                set_cast_sync_status(db, media_type, media_id, "failed", str(error))
            finally:
                db.close()
        finally:
            with cast_hydration_lock:
                cast_hydration_keys.discard(key)

    def cast_hydration_worker() -> None:
        while True:
            job = cast_hydration_queue.get()
            try:
                if job is None:
                    return
                try:
                    hydrate_cast(*job)
                except Exception:
                    app.logger.exception("Cast hydration worker failed for %s %s", job[0], job[1])
            finally:
                cast_hydration_queue.task_done()

    def schedule_cast_hydration(media_type: str, media_id: int, tmdb_id: int) -> None:
        """Queue cast work without creating a thread for each media item."""
        key = (media_type, media_id)
        with cast_hydration_lock:
            if cast_hydration_closed or key in cast_hydration_keys:
                return
            cast_hydration_keys.add(key)
            try:
                with closing(connect_database(app.config["DATABASE"])) as status_db:
                    set_cast_sync_status(status_db, media_type, media_id, "pending")
                cast_hydration_queue.put_nowait((media_type, media_id, tmdb_id))
            except Full:
                try:
                    with closing(connect_database(app.config["DATABASE"])) as status_db:
                        set_cast_sync_status(status_db, media_type, media_id, "failed", "Cast queue is full")
                finally:
                    cast_hydration_keys.discard(key)
                app.logger.warning("Cast hydration queue is full for %s %s", media_type, media_id)
                return
            except Exception:
                cast_hydration_keys.discard(key)
                raise
            if not cast_hydration_workers:
                for index in range(app.config["CAST_HYDRATION_WORKERS"]):
                    worker = threading.Thread(
                        target=cast_hydration_worker,
                        name=f"track-cast-worker-{index + 1}",
                        daemon=True,
                    )
                    worker.start()
                    cast_hydration_workers.append(worker)

    def shutdown_cast_hydration() -> None:
        nonlocal cast_hydration_closed
        with cast_hydration_lock:
            if cast_hydration_closed:
                return
            cast_hydration_closed = True
        cast_hydration_queue.join()
        for _worker in cast_hydration_workers:
            cast_hydration_queue.put(None)
        for worker in cast_hydration_workers:
            worker.join()

    app.extensions["shutdown_cast_hydration"] = shutdown_cast_hydration

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

    def movie_metadata_is_fresh(refreshed_at: str | None) -> bool:
        if not refreshed_at:
            return False
        try:
            refreshed = datetime.fromisoformat(refreshed_at.replace("Z", "+00:00"))
        except ValueError:
            return False
        if refreshed.tzinfo is None:
            refreshed = refreshed.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - refreshed < app.config["MOVIE_METADATA_TTL"]

    def movie_is_background_refreshable(release_date: str | None) -> bool:
        if not release_date:
            return True
        try:
            released = date.fromisoformat(release_date)
        except ValueError:
            return True
        today = datetime.now(timezone.utc).date()
        cutoff_month = today.month - 3
        cutoff_year = today.year
        if cutoff_month <= 0:
            cutoff_month += 12
            cutoff_year -= 1
        cutoff_day = min(today.day, monthrange(cutoff_year, cutoff_month)[1])
        return released >= date(cutoff_year, cutoff_month, cutoff_day)

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
                    AND m.tmdb_id IN ({placeholders})""",
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
        return render_template(
            "index.html",
            catch_up_episodes=get_catch_up_episodes(db, local_date=local_date),
        )

    @app.get("/api/tv")
    def tv_fragment():
        active_shows, archived_shows = get_tv_library_shows(get_db(), request_local_date())
        return render_template(
            "tv.html",
            active_shows=active_shows,
            archived_shows=archived_shows,
        )

    @app.get("/api/movies")
    def movies_fragment():
        return render_template("movies.html", movies=get_movie_library(get_db(), request_local_date()))

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
        if request.args.get("layout") == "monthly":
            if request.args.get("all") != "1":
                abort(400)
            return render_template(
                "_diary_monthly_content.html",
                diary_entries=get_diary_monthly_summary(get_db()),
            )
        if request.args.get("all") == "1":
            diary_entries, _ = get_diary_page(get_db(), page_size=None)
            return render_template(
                "_diary_content.html",
                diary_entries=diary_entries,
                diary_page=1,
                diary_has_more=False,
            )
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
        queued = bool(payload.get("queued"))
        target_state = payload.get("state", TRACKING_ACTIVE)
        if target_state not in TRACKING_STATES:
            return jsonify(error="state must be ACTIVE or ARCHIVED"), 400
        diary_date = payload.get("diary_date")
        if diary_date is not None:
            if not isinstance(diary_date, str):
                return jsonify(error="diary_date must be an ISO date or null"), 400
            try:
                if date.fromisoformat(diary_date).isoformat() != diary_date:
                    raise ValueError
            except ValueError:
                return jsonify(error="diary_date must be an ISO date or null"), 400
        try: movie = get_tmdb_client().movie(tmdb_id)
        except TMDBError as error: return jsonify(error=str(error)), 503
        if movie.get("id") != tmdb_id: return jsonify(error="TMDB returned the wrong movie"), 502
        now = precise_utc_now()
        added_at = f"{diary_date}T00:00:00+00:00" if watched and diary_date else now
        db = get_db()
        existing_movie = db.execute(
            "SELECT is_tracked FROM movies WHERE tmdb_id = ?", (tmdb_id,)
        ).fetchone()
        db.execute("""INSERT INTO movies (tmdb_id,title,original_title,overview,poster_path,backdrop_path,release_date,runtime_minutes,status,genres,original_language,is_tracked,state,added_at,updated_at,tmdb_refreshed_at,tmdb_payload)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(tmdb_id) DO UPDATE SET is_tracked=1,state=excluded.state,added_at=CASE WHEN movies.is_tracked=0 THEN excluded.added_at ELSE movies.added_at END,updated_at=excluded.updated_at""",
          (tmdb_id, movie.get("title") or "Untitled movie", movie.get("original_title"), movie.get("overview"), movie.get("poster_path"), movie.get("backdrop_path"), movie.get("release_date"), movie.get("runtime"), movie.get("status"), ", ".join(g.get("name", "") for g in movie.get("genres", [])), movie.get("original_language"), 1, target_state, added_at, now, now, json.dumps(movie)))
        db.commit()
        movie_id = db.execute("SELECT id FROM movies WHERE tmdb_id = ?", (tmdb_id,)).fetchone()["id"]
        clear_refresh_failure(db, "movie", movie_id)
        if queued:
            db.execute("UPDATE movies SET watch_again = 1 WHERE id = ?", (movie_id,))
        if watched:
            movie_added_at = db.execute("SELECT added_at FROM movies WHERE id = ?", (movie_id,)).fetchone()["added_at"]
            watch_added_at = unknown_log_timestamp(movie_added_at)
            if existing_movie is None or not existing_movie["is_tracked"] or not db.execute(
                "SELECT 1 FROM movie_watch_history WHERE movie_id = ?", (movie_id,)
            ).fetchone():
                db.execute(
                    "INSERT INTO movie_watch_history (movie_id, added_at, diary_date) VALUES (?, ?, ?)",
                    (movie_id, watch_added_at, diary_date),
                )
        normalize_movie_added_timestamps(db, movie_id)
        db.commit()
        schedule_cast_hydration("movie", movie_id, tmdb_id)
        return jsonify(ok=True, movie_id=movie_id, state=target_state)

    @app.post("/api/movies/<int:movie_id>/refresh")
    def refresh_movie(movie_id: int):
        db = get_db()
        local_movie = db.execute(
            "SELECT tmdb_id FROM movies WHERE id = ?", (movie_id,)
        ).fetchone()
        if local_movie is None:
            return jsonify(error="Movie not found"), 404
        attempted_at = utc_now()
        try:
            movie = get_tmdb_client().movie(local_movie["tmdb_id"])
        except TMDBError as error:
            record_refresh_failure(
                db,
                "movie",
                movie_id,
                str(error),
                attempted_at=attempted_at,
                retry_delays=app.config["SHOW_METADATA_FAILURE_BACKOFFS"],
            )
            return jsonify(error=str(error)), 503
        if movie.get("id") != local_movie["tmdb_id"]:
            error = "TMDB returned the wrong movie"
            record_refresh_failure(
                db,
                "movie",
                movie_id,
                error,
                attempted_at=attempted_at,
                retry_delays=app.config["SHOW_METADATA_FAILURE_BACKOFFS"],
            )
            return jsonify(error=error), 502

        now = refresh_movie_metadata(db, movie_id, movie, precise_utc_now())
        clear_refresh_failure(db, "movie", movie_id)
        schedule_cast_hydration("movie", movie_id, local_movie["tmdb_id"])
        return jsonify(movie_id=movie_id, refreshed=True, refreshed_at=now)

    @app.get("/api/movies/tmdb/<int:tmdb_id>/preview")
    def movie_preview_fragment(tmdb_id: int):
        client = get_tmdb_client()
        try:
            payload = client.movie(tmdb_id)
        except TMDBError as error:
            return jsonify(error=str(error)), 503
        if payload.get("id") != tmdb_id:
            return jsonify(error="TMDB returned the wrong movie"), 502
        saved_movie = get_db().execute(
            "SELECT id, is_tracked, state FROM movies WHERE tmdb_id = ?", (tmdb_id,)
        ).fetchone()
        movie = {
            "id": saved_movie["id"] if saved_movie else None,
            "tmdb_id": tmdb_id,
            "title": payload.get("title") or "Untitled movie",
            "overview": payload.get("overview"),
            "poster_path": payload.get("poster_path"),
            "release_date": payload.get("release_date"),
            "is_upcoming": bool(
                payload.get("release_date")
                and payload["release_date"] > request_local_date().isoformat()
            ),
            "runtime_minutes": payload.get("runtime"),
            "genres": ", ".join(genre.get("name", "") for genre in payload.get("genres", [])),
            "is_tracked": bool(saved_movie["is_tracked"]) if saved_movie else False,
            "state": saved_movie["state"] if saved_movie else None,
            "watch_count": 0,
        }
        try:
            credits = client.movie_credits(tmdb_id)
            cast = [
                {
                    "name": credit["name"],
                    "profile_path": credit.get("profile_path"),
                    "character_name": credit.get("character"),
                }
                for credit in credits.get("cast", [])
                if isinstance(credit.get("name"), str) and credit["name"].strip()
            ][:20]
        except TMDBError:
            cast = []
        return render_template("movie_detail.html", movie=movie, activity=[], cast=cast)

    @app.get("/api/movies/<int:movie_id>")
    def movie_detail_fragment(movie_id: int):
        db = get_db()
        today = request_local_date().isoformat()
        movie = db.execute(
            """
            SELECT m.*, COUNT(mwh.id) AS watch_count,
                   CASE WHEN m.release_date > ? THEN 1 ELSE 0 END AS is_upcoming
            FROM movies m
            LEFT JOIN movie_watch_history mwh ON mwh.movie_id = m.id
            WHERE m.id = ?
            GROUP BY m.id
            """,
            (today, movie_id),
        ).fetchone()
        if movie is None:
            abort(404)
        return render_template(
            "movie_detail.html",
            movie=movie,
            activity=get_movie_activity(db, movie_id),
            cast=get_media_cast(db, "movie", movie_id),
        )

    def get_media_cast(db: sqlite3.Connection, media_type: str, media_id: int):
        cast_table = "show_cast" if media_type == "show" else "movie_cast"
        media_column = "show_id" if media_type == "show" else "movie_id"
        return db.execute(
            f"""
            SELECT a.name, a.profile_path, c.character_name
            FROM {cast_table} c
            JOIN actors a ON a.id = c.actor_id
            WHERE c.{media_column} = ?
            ORDER BY c.cast_order, a.name COLLATE NOCASE
            LIMIT 20
            """,
            (media_id,),
        ).fetchall()

    def update_media_reaction(table: str, media_id: int, reaction: str):
        if reaction != "queue":
            abort(404)
        selected = bool((request.get_json(silent=True) or {}).get("selected"))
        db = get_db()
        if table == "shows":
            baseline = get_show_progress(db, media_id, request_local_date())["completed_watch_count"] if selected else None
            cursor = db.execute(
                "UPDATE shows SET watch_again = ?, watch_again_baseline = ?, updated_at = ? WHERE id = ? AND is_tracked = 1",
                (int(selected), baseline, utc_now(), media_id),
            )
        else:
            cursor = db.execute(
                f"UPDATE {table} SET watch_again = ?, updated_at = ? WHERE id = ? AND is_tracked = 1",
                (int(selected), utc_now(), media_id),
            )
        if cursor.rowcount == 0:
            return jsonify(error="Media not found"), 404
        db.commit()
        return jsonify(media_id=media_id, reaction=reaction, selected=selected)

    @app.post("/api/shows/<int:show_id>/reactions/<reaction>")
    def set_show_reaction(show_id: int, reaction: str):
        return update_media_reaction("shows", show_id, reaction)

    @app.post("/api/movies/<int:movie_id>/reactions/<reaction>")
    def set_movie_reaction(movie_id: int, reaction: str):
        return update_media_reaction("movies", movie_id, reaction)

    @app.post("/api/movies/<int:movie_id>/state")
    def set_movie_state(movie_id: int):
        target_state = (request.get_json(silent=True) or {}).get("state")
        if target_state not in TRACKING_STATES:
            return jsonify(error="state must be ACTIVE or ARCHIVED"), 400
        db = get_db()
        cursor = db.execute(
            "UPDATE movies SET state = ?, updated_at = ? WHERE id = ? AND is_tracked = 1",
            (target_state, utc_now(), movie_id),
        )
        if cursor.rowcount == 0:
            return jsonify(error="Movie not found"), 404
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

    @app.post("/api/movies/<int:movie_id>/log")
    def log_movie(movie_id: int):
        payload = request.get_json(silent=True) or {}
        log_date = payload.get("log_date")
        if payload.get("action_kind") != "watch" or (log_date is not None and not isinstance(log_date, str)):
            return jsonify(error="log_date must be an ISO date or null"), 400
        if log_date is not None:
            try:
                date.fromisoformat(log_date)
            except ValueError:
                return jsonify(error="log_date must be an ISO date"), 400
        db = get_db()
        movie = db.execute(
            "SELECT id, added_at FROM movies WHERE id = ? AND is_tracked = 1", (movie_id,)
        ).fetchone()
        if movie is None:
            return jsonify(error="Movie not found"), 404
        added_at = precise_utc_now() if log_date is not None else unknown_log_timestamp(movie["added_at"])
        record_id = db.execute(
            """INSERT INTO movie_watch_history
               (movie_id, added_at, diary_date)
               VALUES (?, ?, ?)""",
            (movie_id, added_at, log_date),
        ).lastrowid
        watch_again_cleared = db.execute(
            "UPDATE movies SET watch_again = 0 WHERE id = ? AND watch_again = 1",
            (movie_id,),
        ).rowcount > 0
        normalize_movie_added_timestamps(db, movie_id)
        db.commit()
        watch_count = db.execute("SELECT COUNT(*) FROM movie_watch_history WHERE movie_id = ?", (movie_id,)).fetchone()[0]
        return jsonify(movie_id=movie_id, watch_count=watch_count, watch_record_id=record_id,
                       watch_kind="movie", action_kind="watch", added_at=added_at,
                       diary_date=log_date, display_date=log_date or added_at[:10],
                       watch_again_cleared=watch_again_cleared)

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
        imported_show = get_library_show(get_db(), show_id, request_local_date())
        schedule_cast_hydration("show", show_id, tmdb_id)
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
        retry_after = refresh_retry_after(db, "show", show_id)
        now = utc_now()
        if not force and (
            show_metadata_is_fresh(local_show["tmdb_refreshed_at"])
            or (retry_after is not None and retry_after > now)
        ):
            return jsonify(
                show_id=show_id,
                refreshed=False,
                refreshed_at=local_show["tmdb_refreshed_at"],
                retry_after=retry_after,
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
            record_refresh_failure(
                db,
                "show",
                show_id,
                str(error),
                attempted_at=now,
                retry_delays=app.config["SHOW_METADATA_FAILURE_BACKOFFS"],
            )
            return jsonify(error=str(error)), 503
        except ValueError as error:
            record_refresh_failure(
                db,
                "show",
                show_id,
                str(error),
                attempted_at=now,
                retry_delays=app.config["SHOW_METADATA_FAILURE_BACKOFFS"],
            )
            return jsonify(error=str(error)), 502
        clear_refresh_failure(db, "show", refreshed_id)
        refreshed_show = get_library_show(db, refreshed_id, request_local_date())
        schedule_cast_hydration("show", refreshed_id, local_show["tmdb_id"])
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
        result = refresh_stale_records(
            get_db(),
            client_factory=get_tmdb_client,
            metadata_is_fresh=show_metadata_is_fresh,
            attempted_at=utc_now(),
            retry_delays=app.config["SHOW_METADATA_FAILURE_BACKOFFS"],
            include_card_html=include_card_html,
            render_card=(
                lambda show: render_template("_show_card_fragment.html", show=show)
            ),
        )
        for refreshed_show in result["refreshed"]:
            local_show = get_db().execute(
                "SELECT tmdb_id FROM shows WHERE id = ?", (refreshed_show["show_id"],)
            ).fetchone()
            if local_show is not None:
                schedule_cast_hydration(
                    "show", refreshed_show["show_id"], local_show["tmdb_id"]
                )
        return result


    app.extensions["refresh_stale_tracked_shows"] = (
        refresh_stale_tracked_show_records
    )

    def refresh_stale_tracked_movie_records() -> dict:
        result = refresh_stale_movie_records(
            get_db(),
            client_factory=get_tmdb_client,
            metadata_is_fresh=movie_metadata_is_fresh,
            movie_is_refreshable=movie_is_background_refreshable,
            attempted_at=utc_now(),
            retry_delays=app.config["SHOW_METADATA_FAILURE_BACKOFFS"],
        )
        for refreshed_movie in result["refreshed"]:
            local_movie = get_db().execute(
                "SELECT tmdb_id FROM movies WHERE id = ?", (refreshed_movie["movie_id"],)
            ).fetchone()
            if local_movie is not None:
                schedule_cast_hydration(
                    "movie", refreshed_movie["movie_id"], local_movie["tmdb_id"]
                )
        return result

    app.extensions["refresh_stale_tracked_movies"] = (
        refresh_stale_tracked_movie_records
    )

    @app.post("/api/shows/refresh-stale")
    def refresh_stale_tracked_shows():
        return jsonify(refresh_stale_tracked_show_records(include_card_html=True))

    @app.get("/api/shows/<int:show_id>")
    def show_detail_fragment(show_id: int):
        db = get_db()
        show = db.execute(
            """
            WITH episode_counts AS (
                SELECT e.id AS episode_id, sn.show_id,
                       (SELECT COUNT(*) FROM episode_watch_history wh WHERE wh.episode_id = e.id)
                       + (SELECT COUNT(*) FROM episode_skips sk WHERE sk.episode_id = e.id) AS watch_count
                FROM seasons sn
                JOIN episodes e ON e.season_id = sn.id
                  AND sn.is_progress_counted = 1
                  AND e.air_date <= ?
            )
            SELECT s.*, (SELECT COUNT(*) FROM seasons WHERE show_id = s.id AND is_progress_counted = 1) AS season_count,
                   COUNT(ec.episode_id) AS episode_count,
                   COALESCE(SUM(CASE WHEN ec.watch_count > 0 THEN 1 ELSE 0 END), 0) AS watched_count,
                   COALESCE(SUM(ec.watch_count), 0) AS total_watch_count,
                   COALESCE(MIN(ec.watch_count), 0) AS completed_watch_count
            FROM shows s
            LEFT JOIN episode_counts ec ON ec.show_id = s.id
            WHERE s.id = ?
            GROUP BY s.id
            """,
            (request_local_date().isoformat(), show_id),
        ).fetchone()
        if show is None:
            abort(404)

        next_episode = get_catch_up_episodes(db, show_id=show_id, local_date=request_local_date()) if show["is_tracked"] else []
        return render_template(
            "show_detail.html",
            show=show,
            next_watch_episode_id=next_episode[0]["episode_id"] if next_episode else None,
            activity=get_show_activity(db, show_id),
            cast=get_media_cast(db, "show", show_id),
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
                       (SELECT COUNT(*) FROM episode_watch_history wh WHERE wh.episode_id = e.id)
                       + (SELECT COUNT(*) FROM episode_skips sk WHERE sk.episode_id = e.id) AS watch_count
                FROM episodes e
                WHERE e.season_id IN (
                    SELECT id FROM seasons WHERE show_id = ?
                )
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
                   (SELECT COUNT(*) FROM episode_watch_history wh WHERE wh.episode_id = e.id)
                   + (SELECT COUNT(*) FROM episode_skips sk WHERE sk.episode_id = e.id) AS watch_count,
                   (SELECT MAX(resolved_at) FROM (
                     SELECT wh.added_at AS resolved_at FROM episode_watch_history wh WHERE wh.episode_id = e.id
                     UNION ALL
                     SELECT sk.skipped_at AS resolved_at FROM episode_skips sk WHERE sk.episode_id = e.id
                   )) AS last_watched_at,
                   (SELECT resolution_kind FROM (
                     SELECT 'watch' AS resolution_kind, COALESCE(wh.diary_date, substr(wh.added_at, 1, 10)) AS resolved_at, wh.id FROM episode_watch_history wh WHERE wh.episode_id = e.id
                     UNION ALL
                     SELECT 'skip' AS resolution_kind, COALESCE(sk.diary_date, substr(sk.skipped_at, 1, 10)) AS resolved_at, sk.id FROM episode_skips sk WHERE sk.episode_id = e.id
                   ) ORDER BY resolved_at DESC, id DESC LIMIT 1) AS latest_resolution_kind
            FROM episodes e
            WHERE e.season_id = ?
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
                   s.is_tracked AS show_is_tracked,
                   s.watch_again AS show_watch_again,
                   s.status AS show_status,
                   s.genres AS show_genres,
                   (SELECT COUNT(*) FROM episode_watch_history wh WHERE wh.episode_id = e.id)
                   + (SELECT COUNT(*) FROM episode_skips sk WHERE sk.episode_id = e.id) AS watch_count,
                   (SELECT resolution_kind FROM (
                     SELECT 'watch' AS resolution_kind, COALESCE(wh.diary_date, substr(wh.added_at, 1, 10)) AS resolved_at, wh.id FROM episode_watch_history wh WHERE wh.episode_id = e.id
                     UNION ALL
                     SELECT 'skip' AS resolution_kind, COALESCE(sk.diary_date, substr(sk.skipped_at, 1, 10)) AS resolved_at, sk.id FROM episode_skips sk WHERE sk.episode_id = e.id
                   ) ORDER BY resolved_at DESC, id DESC LIMIT 1) AS latest_resolution_kind
            FROM episodes e
            JOIN seasons sn ON sn.id = e.season_id
            JOIN shows s ON s.id = sn.show_id
            WHERE e.id = ?
            """,
            (episode_id,),
        ).fetchone()
        if episode is None:
            abort(404)

        episode = dict(episode)
        show_progress = get_show_progress(db, episode["show_id"], request_local_date())
        episode["show_finished"] = (
            show_progress["episode_count"] > 0
            and show_progress["watched_count"] >= show_progress["episode_count"]
        )
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
            SELECT 'watched' AS event_type, 'Watched' AS title,
                   id AS watch_record_id, added_at, diary_date,
                   COALESCE({effective_diary_date_sql()}, substr(added_at, 1, 10)) AS display_date, 'episode' AS watch_kind
            FROM episode_watch_history WHERE episode_id = ?
            UNION ALL
            SELECT 'skipped' AS event_type, 'Skipped' AS title,
                   id AS watch_record_id, skipped_at AS added_at, diary_date,
                   COALESCE(diary_date, substr(skipped_at, 1, 10)) AS display_date, 'skip' AS watch_kind
            FROM episode_skips WHERE episode_id = ?
            ORDER BY display_date DESC, added_at DESC, watch_record_id DESC
            """,
            (episode_id, episode_id),
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
        queued = payload.get("queued", False)
        if type(queued) is not bool or (queued and target_state != TRACKING_ACTIVE):
            return jsonify(error="queued requires ACTIVE and must be a boolean"), 400

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

        if queued:
            baseline = get_show_progress(db, show_id, request_local_date())["completed_watch_count"]
            db.execute(
                "UPDATE shows SET watch_again = 1, watch_again_baseline = ?, updated_at = ? WHERE id = ?",
                (baseline, utc_now(), show_id),
            )
            db.commit()

        library_show = get_library_show(db, show_id, request_local_date())
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
            activity_title=("Archived" if target_state == TRACKING_ARCHIVED else "Resumed"),
            activity_type=("archived" if target_state == TRACKING_ARCHIVED else "activated"),
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

    @app.post("/api/episodes/<int:episode_id>/log")
    def log_episode(episode_id: int):
        payload = request.get_json(silent=True) or {}
        action_kind, log_date = payload.get("action_kind"), payload.get("log_date")
        if action_kind not in {"watch", "skip"} or (log_date is not None and not isinstance(log_date, str)):
            return jsonify(error="action_kind and log_date are required"), 400
        if log_date is not None:
            try: date.fromisoformat(log_date)
            except ValueError: return jsonify(error="log_date must be an ISO date"), 400
        try: return jsonify(create_episode_log(get_db(), episode_id, action_kind, log_date, request_local_date()))
        except WatchNotFoundError as error: return jsonify(error=str(error)), 404


    @app.post("/api/seasons/<int:season_id>/log")
    def log_season(season_id: int):
        payload = request.get_json(silent=True) or {}
        action_kind, log_date = payload.get("action_kind"), payload.get("log_date")
        if action_kind not in {"watch", "skip"} or (log_date is not None and not isinstance(log_date, str)):
            return jsonify(error="action_kind and log_date are required"), 400
        if log_date is not None:
            try: date.fromisoformat(log_date)
            except ValueError: return jsonify(error="log_date must be an ISO date"), 400
        try: return jsonify(create_season_log(get_db(), season_id, action_kind, log_date, request_local_date()))
        except WatchNotFoundError as error: return jsonify(error=str(error)), 404

    @app.delete("/api/logs/<string:watch_kind>/<int:record_id>")
    def delete_log(watch_kind: str, record_id: int):
        try:
            result = remove_log(get_db(), watch_kind, record_id)
            return jsonify(watch_kind=watch_kind, watch_record_id=record_id, **result)
        except WatchNotFoundError as error:
            return jsonify(error=str(error)), 404


    @app.patch("/api/logs/<string:watch_kind>/<int:record_id>")
    def set_log_diary_date_route(watch_kind: str, record_id: int):
        if watch_kind not in {"episode", "season", "movie", "skip", "season-skip"}:
            return jsonify(error="Unknown watch history type"), 404
        payload = request.get_json(silent=True) or {}
        diary_date = payload.get("diary_date")
        if diary_date is not None:
            if not isinstance(diary_date, str):
                return jsonify(error="diary_date must be an ISO date or null"), 400
            try:
                date.fromisoformat(diary_date)
            except ValueError:
                return jsonify(error="diary_date must be an ISO date or null"), 400
        if watch_kind == "skip":
            db = get_db()
            row = db.execute("SELECT skipped_at FROM episode_skips WHERE id = ?", (record_id,)).fetchone()
            if row is None:
                return jsonify(error="Skip entry not found"), 404
            db.execute("UPDATE episode_skips SET diary_date = ? WHERE id = ?", (diary_date, record_id))
            db.commit()
            return jsonify(watch_kind="skip", watch_record_id=record_id, added_at=row["skipped_at"], diary_date=diary_date, display_date=diary_date or row["skipped_at"][:10])
        if watch_kind == "season-skip":
            db = get_db()
            row = db.execute("SELECT added_at, batch_id FROM season_skip_history WHERE id = ?", (record_id,)).fetchone()
            if row is None:
                return jsonify(error="Skip entry not found"), 404
            db.execute("UPDATE season_skip_history SET diary_date = ? WHERE id = ?", (diary_date, record_id))
            if row["batch_id"]:
                db.execute(
                    "UPDATE episode_skips SET diary_date = ? WHERE batch_id = ?",
                    (diary_date, row["batch_id"]),
                )
            db.commit()
            return jsonify(watch_kind="season-skip", watch_record_id=record_id, added_at=row["added_at"], diary_date=diary_date, display_date=diary_date or row["added_at"][:10])
        if watch_kind == "movie":
            db = get_db()
            row = db.execute(
                "SELECT id, movie_id, added_at FROM movie_watch_history WHERE id = ?", (record_id,)
            ).fetchone()
            if row is None:
                return jsonify(error="Movie watch history not found"), 404
            db.execute("UPDATE movie_watch_history SET diary_date = ? WHERE id = ?", (diary_date, record_id))
            normalize_movie_added_timestamps(db, row["movie_id"])
            db.commit()
            return jsonify(
                watch_kind="movie", watch_record_id=record_id, added_at=row["added_at"],
                diary_date=diary_date, display_date=diary_date or row["added_at"][:10],
            )
        try:
            return jsonify(
                set_log_diary_date(
                    get_db(), watch_kind, record_id, diary_date
                )
            )
        except WatchNotFoundError as error:
            return jsonify(error=str(error)), 404

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
            for media_type, extension_name in (
                ("show", "refresh_stale_tracked_shows"),
                ("movie", "refresh_stale_tracked_movies"),
            ):
                try:
                    with app.app_context():
                        result = app.extensions[extension_name]()
                    if result["refreshed"] or result["failures"]:
                        app.logger.info(
                            "Tracked-%s refresh completed: %s refreshed, %s failed, %s fresh",
                            media_type,
                            len(result["refreshed"]),
                            len(result["failures"]),
                            result["skipped"],
                        )
                except Exception:
                    app.logger.exception("Tracked-%s background refresh failed", media_type)
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
