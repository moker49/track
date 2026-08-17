from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, abort, g, jsonify, redirect, render_template, request, url_for


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
    def index():
        db = get_db()
        shows = db.execute(
            """
            SELECT s.*,
                   COUNT(DISTINCT e.id) AS episode_count,
                   COUNT(DISTINCT CASE WHEN wh.id IS NOT NULL THEN e.id END) AS watched_count
            FROM shows s
            LEFT JOIN seasons sn ON sn.show_id = s.id
            LEFT JOIN episodes e ON e.season_id = sn.id AND e.air_date <= date('now')
            LEFT JOIN episode_watch_history wh ON wh.episode_id = e.id AND wh.unwatched_at IS NULL
            WHERE s.state IN ('ACTIVE', 'ARCHIVED')
            GROUP BY s.id
            ORDER BY CASE s.state WHEN 'ACTIVE' THEN 0 ELSE 1 END,
                     s.name COLLATE NOCASE
            """
        ).fetchall()
        popular = db.execute(
            "SELECT * FROM popular_show_stubs ORDER BY popularity_rank"
        ).fetchall()
        active_shows = [show for show in shows if show["state"] == "ACTIVE"]
        archived_shows = [show for show in shows if show["state"] == "ARCHIVED"]
        return render_template(
            "index.html",
            active_shows=active_shows,
            archived_shows=archived_shows,
            popular=popular,
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
        )

    @app.get("/shows/<int:_show_id>")
    @app.get("/search")
    def legacy_page_redirect(_show_id: int | None = None):
        return redirect(url_for("index"))

    @app.post("/api/shows/<int:show_id>/state")
    def set_show_state(show_id: int):
        payload = request.get_json(silent=True) or {}
        target_state = payload.get("state")
        if target_state not in {"ACTIVE", "ARCHIVED"}:
            return jsonify(error="state must be ACTIVE or ARCHIVED"), 400

        db = get_db()
        show = db.execute(
            "SELECT id, state FROM shows WHERE id = ?", (show_id,)
        ).fetchone()
        if show is None:
            return jsonify(error="Show not found"), 404

        if show["state"] != target_state:
            changed_at = utc_now()
            timestamp_column = (
                "archived_at" if target_state == "ARCHIVED" else "active_at"
            )
            db.execute(
                f"""
                UPDATE shows
                SET state = ?, {timestamp_column} = ?, updated_at = ?
                WHERE id = ?
                """,
                (target_state, changed_at, changed_at, show_id),
            )
            db.execute(
                """
                INSERT INTO show_state_history (show_id, state, entered_at)
                VALUES (?, ?, ?)
                """,
                (show_id, target_state, changed_at),
            )
            db.commit()

        return jsonify(
            show_id=show_id,
            state=target_state,
            move_label=("Un-archive" if target_state == "ARCHIVED" else "Archive"),
            move_icon=("unarchive" if target_state == "ARCHIVED" else "archive"),
        )

    @app.delete("/api/shows/<int:show_id>")
    def remove_show(show_id: int):
        db = get_db()
        cursor = db.execute("DELETE FROM shows WHERE id = ?", (show_id,))
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
            show_id=episode["show_id"],
            watched=payload["watched"],
            watch_count=(1 if payload["watched"] else 0),
            watched_count=watched_count,
            episode_count=episode_count,
            percent=percent,
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
    if db.execute("SELECT 1 FROM shows WHERE tmdb_id = 1396").fetchone():
        seed_game_of_thrones(db)
        db.commit()
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
        INSERT OR IGNORE INTO popular_show_stubs (tmdb_id, name, subtitle, popularity_rank)
        VALUES (?, ?, ?, ?)
        """,
        [
            (94997, "House of the Dragon", "Drama · Fantasy", 1),
            (100088, "The Last of Us", "Drama · Sci-Fi", 2),
            (95396, "Severance", "Drama · Mystery", 3),
            (60625, "Rick and Morty", "Animation · Comedy", 4),
        ],
    )
    seed_game_of_thrones(db)
    db.commit()


def seed_game_of_thrones(db: sqlite3.Connection) -> None:
    if db.execute("SELECT 1 FROM shows WHERE tmdb_id = 1399").fetchone():
        return

    added_at = "2026-06-10T18:30:00+00:00"
    active_at = "2026-06-12T00:15:00+00:00"
    archived_at = "2026-07-01T02:40:00+00:00"
    cursor = db.execute(
        """
        INSERT INTO shows (
            tmdb_id, name, original_name, overview, tagline, poster_path,
            backdrop_path, first_air_date, status, genres, original_language,
            state, added_at, watchlist_at, active_at, archived_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ARCHIVED', ?, ?, ?, ?)
        """,
        (
            1399,
            "Game of Thrones",
            "Game of Thrones",
            "Nine noble families fight for control over the lands of Westeros while an ancient enemy returns after being dormant for millennia.",
            "Winter is coming.",
            None,
            None,
            "2011-04-17",
            "Ended",
            "Drama, Fantasy, Action",
            "en",
            added_at,
            added_at,
            active_at,
            archived_at,
        ),
    )
    show_id = cursor.lastrowid
    db.executemany(
        "INSERT INTO show_state_history (show_id, state, entered_at) VALUES (?, ?, ?)",
        [
            (show_id, "WATCHLIST", added_at),
            (show_id, "ACTIVE", active_at),
            (show_id, "ARCHIVED", archived_at),
        ],
    )

    seasons = [
        (
            1,
            3624,
            "Season 1",
            "The great houses of Westeros are drawn into a struggle for the Iron Throne.",
            "2011-04-17",
            [
                (1, "Winter Is Coming", "2011-04-17", 62),
                (2, "The Kingsroad", "2011-04-24", 56),
                (3, "Lord Snow", "2011-05-01", 58),
                (4, "Cripples, Bastards, and Broken Things", "2011-05-08", 56),
                (5, "The Wolf and the Lion", "2011-05-15", 55),
                (6, "A Golden Crown", "2011-05-22", 53),
            ],
        ),
        (
            2,
            3625,
            "Season 2",
            "Kings across Westeros clash as threats gather beyond the Wall and across the sea.",
            "2012-04-01",
            [
                (1, "The North Remembers", "2012-04-01", 53),
                (2, "The Night Lands", "2012-04-08", 54),
                (3, "What Is Dead May Never Die", "2012-04-15", 53),
                (4, "Garden of Bones", "2012-04-22", 51),
                (5, "The Ghost of Harrenhal", "2012-04-29", 55),
                (6, "The Old Gods and the New", "2012-05-06", 54),
            ],
        ),
    ]

    watched_at_day = 13
    for season_number, tmdb_id, name, overview, air_date, episodes in seasons:
        season_cursor = db.execute(
            """
            INSERT INTO seasons (show_id, tmdb_id, season_number, name, overview, air_date)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (show_id, tmdb_id, season_number, name, overview, air_date),
        )
        for episode_number, title, episode_air_date, runtime in episodes:
            episode_cursor = db.execute(
                """
                INSERT INTO episodes (
                    season_id, tmdb_id, episode_number, name, overview,
                    air_date, runtime_minutes
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    season_cursor.lastrowid,
                    64000 + season_number * 100 + episode_number,
                    episode_number,
                    title,
                    "A chapter in the struggle for the future of Westeros.",
                    episode_air_date,
                    runtime,
                ),
            )
            db.execute(
                """
                INSERT INTO episode_watch_history (episode_id, watched_at)
                VALUES (?, ?)
                """,
                (
                    episode_cursor.lastrowid,
                    f"2026-06-{watched_at_day:02d}T01:10:00+00:00",
                ),
            )
            watched_at_day += 1


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=False)
