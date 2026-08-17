from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, abort, g, jsonify, render_template, request


BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "instance" / "track.db"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(DATABASE=str(DATABASE))
    if test_config:
        app.config.update(test_config)

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

    @app.get("/")
    def my_shows():
        query = request.args.get("q", "").strip()
        shows = get_db().execute(
            """
            SELECT s.*,
                   COUNT(DISTINCT e.id) AS episode_count,
                   COUNT(DISTINCT CASE WHEN wh.id IS NOT NULL THEN e.id END) AS watched_count
            FROM shows s
            LEFT JOIN seasons sn ON sn.show_id = s.id
            LEFT JOIN episodes e ON e.season_id = sn.id AND e.air_date <= date('now')
            LEFT JOIN episode_watch_history wh ON wh.episode_id = e.id AND wh.unwatched_at IS NULL
            WHERE s.state = 'ACTIVE'
              AND (? = '' OR s.name LIKE '%' || ? || '%' COLLATE NOCASE)
            GROUP BY s.id
            ORDER BY s.name COLLATE NOCASE
            """,
            (query, query),
        ).fetchall()
        return render_template(
            "my_shows.html", shows=shows, query=query, active_nav="shows"
        )

    @app.get("/shows/<int:show_id>")
    def show_detail(show_id: int):
        db = get_db()
        show = db.execute(
            """
            SELECT s.*,
                   COUNT(DISTINCT e.id) AS episode_count,
                   COUNT(DISTINCT CASE WHEN wh.id IS NOT NULL THEN e.id END) AS watched_count
            FROM shows s
            LEFT JOIN seasons sn ON sn.show_id = s.id
            LEFT JOIN episodes e ON e.season_id = sn.id AND e.air_date <= date('now')
            LEFT JOIN episode_watch_history wh ON wh.episode_id = e.id AND wh.unwatched_at IS NULL
            WHERE s.id = ?
            GROUP BY s.id
            """,
            (show_id,),
        ).fetchone()
        if show is None:
            abort(404)

        seasons = db.execute(
            "SELECT * FROM seasons WHERE show_id = ? ORDER BY season_number",
            (show_id,),
        ).fetchall()
        episodes_by_season = {}
        for season in seasons:
            episodes_by_season[season["id"]] = db.execute(
                """
                SELECT e.*,
                       COUNT(wh.id) AS watch_count,
                       MAX(wh.watched_at) AS last_watched_at
                FROM episodes e
                LEFT JOIN episode_watch_history wh ON wh.episode_id = e.id AND wh.unwatched_at IS NULL
                WHERE e.season_id = ?
                GROUP BY e.id
                ORDER BY e.episode_number
                """,
                (season["id"],),
            ).fetchall()
        return render_template(
            "show_detail.html",
            show=show,
            seasons=seasons,
            episodes_by_season=episodes_by_season,
            active_nav="shows",
        )

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
                "SELECT 1 FROM episode_watch_history WHERE episode_id = ? AND unwatched_at IS NULL LIMIT 1",
                (episode_id,),
            ).fetchone()
            if watched is None:
                db.execute(
                    "INSERT INTO episode_watch_history (episode_id, watched_at) VALUES (?, ?)",
                    (episode_id, utc_now()),
                )
        else:
            # Retire active watch events instead of deleting them so every
            # historical watched_at timestamp remains available.
            db.execute(
                """
                UPDATE episode_watch_history
                SET unwatched_at = ?
                WHERE episode_id = ? AND unwatched_at IS NULL
                """,
                (utc_now(), episode_id),
            )
        db.commit()

        progress = db.execute(
            """
            SELECT COUNT(DISTINCT e.id) AS episode_count,
                   COUNT(DISTINCT CASE WHEN wh.id IS NOT NULL THEN e.id END) AS watched_count
            FROM seasons sn
            JOIN episodes e ON e.season_id = sn.id AND e.air_date <= date('now')
            LEFT JOIN episode_watch_history wh ON wh.episode_id = e.id AND wh.unwatched_at IS NULL
            WHERE sn.show_id = ?
            """,
            (episode["show_id"],),
        ).fetchone()
        episode_count = progress["episode_count"]
        watched_count = progress["watched_count"]
        percent = round(watched_count / episode_count * 100) if episode_count else 0
        return jsonify(
            watched=payload["watched"],
            watch_count=(1 if payload["watched"] else 0),
            watched_count=watched_count,
            episode_count=episode_count,
            percent=percent,
        )

    @app.get("/search")
    def search():
        query = request.args.get("q", "").strip()
        popular = get_db().execute(
            "SELECT * FROM popular_show_stubs ORDER BY popularity_rank"
        ).fetchall()
        return render_template(
            "search.html", popular=popular, query=query, active_nav="search"
        )

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("404.html", active_nav=None), 404

    with app.app_context():
        db = get_db()
        schema = (BASE_DIR / "schema.sql").read_text(encoding="utf-8")
        db.executescript(schema)
        watch_columns = {
            row["name"] for row in db.execute("PRAGMA table_info(episode_watch_history)")
        }
        if "unwatched_at" not in watch_columns:
            db.execute("ALTER TABLE episode_watch_history ADD COLUMN unwatched_at TEXT")
        seed_database(db)

    return app


def seed_database(db: sqlite3.Connection) -> None:
    if db.execute("SELECT 1 FROM shows LIMIT 1").fetchone():
        return

    added_at = "2026-05-02T19:15:00+00:00"
    cursor = db.execute(
        """
        INSERT INTO shows (
            tmdb_id, name, original_name, overview, tagline, poster_path,
            backdrop_path, first_air_date, status, genres, original_language,
            state, added_at, watchlist_at, active_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?, ?)
        """,
        (
            1396,
            "Breaking Bad",
            "Breaking Bad",
            "A chemistry teacher facing a terminal diagnosis turns to making methamphetamine, transforming his family and everyone around him.",
            "All hail the king.",
            None,
            None,
            "2008-01-20",
            "Ended",
            "Drama, Crime",
            "en",
            added_at,
            added_at,
            "2026-05-04T00:10:00+00:00",
        ),
    )
    show_id = cursor.lastrowid
    db.executemany(
        "INSERT INTO show_state_history (show_id, state, entered_at) VALUES (?, ?, ?)",
        [
            (show_id, "WATCHLIST", added_at),
            (show_id, "ACTIVE", "2026-05-04T00:10:00+00:00"),
        ],
    )

    seasons = [
        (1, "Season 1", "Walter White takes his first steps into a dangerous new life.", "2008-01-20"),
        (2, "Season 2", "The consequences grow as Walter and Jesse expand their operation.", "2009-03-08"),
    ]
    episode_rows = {
        1: [
            (1, "Pilot", "Walter White receives life-changing news and makes a startling choice.", "2008-01-20", 58),
            (2, "Cat's in the Bag...", "Walter and Jesse confront the practical fallout of their first cook.", "2008-01-27", 48),
            (3, "...And the Bag's in the River", "Walter wrestles with an impossible decision.", "2008-02-10", 48),
            (4, "Cancer Man", "Walter reveals his diagnosis to the family.", "2008-02-17", 48),
            (5, "Gray Matter", "An old business connection offers Walter a way out.", "2008-02-24", 48),
            (6, "Crazy Handful of Nothin'", "Walter adopts a new identity as pressure mounts.", "2008-03-02", 48),
            (7, "A No-Rough-Stuff-Type Deal", "Walter and Jesse attempt an ambitious new cook.", "2008-03-09", 48),
        ],
        2: [
            (1, "Seven Thirty-Seven", "Walter calculates what it will take to secure his family's future.", "2009-03-08", 47),
            (2, "Grilled", "A tense desert confrontation leaves few options.", "2009-03-15", 48),
            (3, "Bit by a Dead Bee", "Walter and Jesse invent stories to explain their disappearance.", "2009-03-22", 47),
            (4, "Down", "The strain on both partners' personal lives intensifies.", "2009-03-29", 47),
            (5, "Breakage", "Jesse rebuilds the operation while Hank struggles.", "2009-04-05", 47),
            (6, "Peekaboo", "Jesse encounters the human cost of the drug trade.", "2009-04-12", 47),
        ],
    }
    episode_ids = []
    for number, name, overview, air_date in seasons:
        season_cursor = db.execute(
            """
            INSERT INTO seasons (show_id, tmdb_id, season_number, name, overview, air_date)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (show_id, 3572 + number, number, name, overview, air_date),
        )
        season_id = season_cursor.lastrowid
        for ep_num, title, ep_overview, ep_date, runtime in episode_rows[number]:
            ep_cursor = db.execute(
                """
                INSERT INTO episodes (
                    season_id, tmdb_id, episode_number, name, overview, air_date, runtime_minutes
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (season_id, 62000 + number * 100 + ep_num, ep_num, title, ep_overview, ep_date, runtime),
            )
            episode_ids.append(ep_cursor.lastrowid)

    for index, episode_id in enumerate(episode_ids[:5], start=1):
        db.execute(
            "INSERT INTO episode_watch_history (episode_id, watched_at) VALUES (?, ?)",
            (episode_id, f"2026-05-{index + 4:02d}T01:20:00+00:00"),
        )

    db.executemany(
        """
        INSERT INTO popular_show_stubs (tmdb_id, name, subtitle, popularity_rank)
        VALUES (?, ?, ?, ?)
        """,
        [
            (94997, "House of the Dragon", "Drama · Fantasy", 1),
            (100088, "The Last of Us", "Drama · Sci-Fi", 2),
            (95396, "Severance", "Drama · Mystery", 3),
            (60625, "Rick and Morty", "Animation · Comedy", 4),
        ],
    )
    db.commit()


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=False)
