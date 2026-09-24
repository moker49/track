import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from app import create_app
from database import connect_database, initialize_database
from tests.test_app import seed_test_library


class WorkflowSmokeTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "smoke.db"
        self.app = create_app({"TESTING": True, "DATABASE": str(self.database)})
        seed_test_library(self.database)
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def rows(self, sql, parameters=()):
        db = sqlite3.connect(self.database)
        try:
            db.row_factory = sqlite3.Row
            return db.execute(sql, parameters).fetchall()
        finally:
            db.close()

    def test_shell_and_every_local_fragment_render(self):
        for path in (
            "/",
            "/api/tv",
            "/api/schedule",
            "/api/shows/1",
            "/api/shows/1/seasons",
            "/api/seasons/1/episodes",
            "/api/episodes/1",
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertTrue(response.data, path)
        for path in ("/api/shows/9999", "/api/seasons/9999/episodes", "/api/episodes/9999"):
            self.assertEqual(self.client.get(path).status_code, 404, path)

    def test_tracking_lifecycle_preserves_metadata_and_watch_history(self):
        initial_watches = self.rows(
            "SELECT COUNT(*) AS count FROM episode_watch_history WHERE episode_id = 1"
        )[0]["count"]
        archived = self.client.post("/api/shows/1/state", json={"state": "ARCHIVED"})
        self.assertEqual(archived.status_code, 200)
        self.assertEqual(archived.get_json()["move_label"], "Resume")
        self.assertEqual(self.client.delete("/api/shows/1").status_code, 204)
        removed = self.rows("SELECT is_tracked, state FROM shows WHERE id = 1")[0]
        self.assertEqual((removed["is_tracked"], removed["state"]), (0, "ARCHIVED"))
        resumed = self.client.post("/api/shows/1/state", json={"state": "ACTIVE"})
        self.assertEqual(resumed.status_code, 200)
        self.assertTrue(resumed.get_json()["newly_tracked"])
        self.assertEqual(
            self.rows("SELECT COUNT(*) AS count FROM episode_watch_history WHERE episode_id = 1")[0]["count"],
            initial_watches,
        )
        history = self.rows("SELECT state FROM show_state_history WHERE show_id = 1 ORDER BY id")
        self.assertEqual([row["state"] for row in history][-2:], ["ARCHIVED", "ACTIVE"])

    def test_episode_logs_are_created_edited_and_deleted_by_record_id(self):
        watch = self.client.post(
            "/api/episodes/6/log",
            json={"action_kind": "watch", "log_date": None},
        )
        self.assertEqual(watch.status_code, 200)
        watch_payload = watch.get_json()
        watch_id = watch_payload["watch_record_id"]
        self.assertEqual(watch_payload["added_at"], "2026-05-02T20:15:00+00:00")

        skip = self.client.post(
            "/api/episodes/6/log",
            json={"action_kind": "skip", "log_date": "2026-09-10"},
        )
        self.assertEqual(skip.status_code, 200)
        skip_id = skip.get_json()["watch_record_id"]

        edited = self.client.patch(
            f"/api/logs/episode/{watch_id}",
            json={"diary_date": "2026-09-09"},
        )
        self.assertEqual(edited.status_code, 200)
        self.assertEqual(edited.get_json()["diary_date"], "2026-09-09")

        deleted = self.client.delete(f"/api/logs/episode/{watch_id}")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(
            self.rows("SELECT COUNT(*) AS count FROM episode_watch_history WHERE id = ?", (watch_id,))[0]["count"],
            0,
        )
        self.assertEqual(
            self.rows("SELECT COUNT(*) AS count FROM episode_skips WHERE id = ?", (skip_id,))[0]["count"],
            1,
        )

    def test_initialization_preserves_existing_unknown_log_timestamps(self):
        db = connect_database(self.database)
        db.execute(
            "INSERT INTO episode_watch_history (episode_id, added_at) VALUES (6, '2030-01-01T00:00:00+00:00')"
        )
        db.commit()
        initialize_database(db, Path(__file__).parents[1] / "schema.sql")
        timestamp = db.execute(
            "SELECT added_at FROM episode_watch_history WHERE episode_id = 6"
        ).fetchone()["added_at"]
        db.close()
        self.assertEqual(timestamp, "2030-01-01T00:00:00+00:00")

    def test_season_logs_are_removed_as_batches(self):
        created = self.client.post(
            "/api/seasons/2/log",
            json={"action_kind": "watch", "log_date": "2026-09-10"},
        )
        self.assertEqual(created.status_code, 200)
        payload = created.get_json()
        self.assertEqual(len(payload["episodes"]), 6)
        batch_id = payload["batch_id"]
        self.assertTrue(batch_id)
        batch = self.rows(
            "SELECT season_id, action_kind FROM season_log_batches WHERE id = ?",
            (batch_id,),
        )[0]
        self.assertEqual((batch["season_id"], batch["action_kind"]), (2, "watch"))
        self.assertEqual(
            self.rows(
                "SELECT COUNT(*) AS count FROM season_watch_history WHERE batch_id = ?",
                (batch_id,),
            )[0]["count"],
            1,
        )
        self.assertEqual(
            self.rows(
                "SELECT COUNT(*) AS count FROM episode_watch_history WHERE batch_id = ?",
                (batch_id,),
            )[0]["count"],
            len(payload["episodes"]),
        )
        self.assertEqual(
            self.client.delete(f"/api/logs/season/{payload['watch_record_id']}").status_code,
            200,
        )
        self.assertEqual(
            self.rows("SELECT COUNT(*) AS count FROM season_watch_history WHERE id = ?", (payload["watch_record_id"],))[0]["count"],
            0,
        )
        self.assertEqual(
            self.rows(
                "SELECT COUNT(*) AS count FROM episode_watch_history WHERE batch_id = ?",
                (batch_id,),
            )[0]["count"],
            0,
        )
        self.assertEqual(
            self.rows(
                "SELECT COUNT(*) AS count FROM season_log_batches WHERE id = ?",
                (batch_id,),
            )[0]["count"],
            0,
        )

    def test_log_routes_validate_actions_dates_and_kinds(self):
        invalid_action = self.client.post(
            "/api/episodes/1/log", json={"action_kind": "erase", "log_date": None}
        )
        invalid_date = self.client.patch(
            "/api/logs/episode/1", json={"diary_date": "not-a-date"}
        )
        invalid_kind = self.client.patch(
            "/api/logs/show/1", json={"diary_date": None}
        )
        self.assertEqual(
            (invalid_action.status_code, invalid_date.status_code, invalid_kind.status_code),
            (400, 400, 404),
        )




    def test_upcoming_includes_archived_but_excludes_untracked_and_specials(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        db = sqlite3.connect(self.database)
        try:
            db.execute("UPDATE episodes SET air_date = ? WHERE id IN (14, 20)", (tomorrow,))
            db.execute(
                "INSERT INTO seasons (id, show_id, tmdb_id, season_number, name, is_progress_counted) VALUES (99, 1, 99999, 0, 'Specials', 0)"
            )
            db.execute(
                "INSERT INTO episodes (id, season_id, tmdb_id, episode_number, name, air_date) VALUES (99, 99, 99999, 1, 'Future Special', ?)",
                (tomorrow,),
            )
            db.commit()
        finally:
            db.close()
        schedule = self.client.get("/api/schedule")
        self.assertIn(b"Archived Test Show", schedule.data)
        self.assertNotIn(b"Future Special", schedule.data)
        self.assertEqual(self.client.delete("/api/shows/2").status_code, 204)
        schedule = self.client.get("/api/schedule")
        self.assertNotIn(b"Archived Test Show", schedule.data)



class DatabaseBootstrapSmokeTest(unittest.TestCase):
    def test_bootstrap_is_repeatable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "bootstrap.db"
            schema = Path(__file__).parents[1] / "schema.sql"
            for _ in range(3):
                db = connect_database(database)
                initialize_database(db, schema)
                db.close()
            db = sqlite3.connect(database)
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")}
            indexes = {row[0] for row in db.execute("SELECT name FROM sqlite_schema WHERE type = 'index'")}
            db.close()
            self.assertIn("shows", tables)
            self.assertIn("episode_watch_history", tables)
            self.assertNotIn("schema_migrations", tables)
            self.assertTrue(any(name.startswith("idx_") for name in indexes))

    def test_cast_schema_uses_normalized_people_and_media_joins(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "cast.db"
            db = connect_database(database)
            initialize_database(db, Path(__file__).parents[1] / "schema.sql")
            db.execute(
                "INSERT INTO shows (tmdb_id, name, state, added_at) VALUES (1, 'Show', 'ACTIVE', '2026-01-01')"
            )
            db.execute(
                "INSERT INTO movies (tmdb_id, title, added_at) VALUES (2, 'Movie', '2026-01-01')"
            )
            db.execute(
                "INSERT INTO actors (tmdb_person_id, name) VALUES (3, 'Actor')"
            )
            db.execute(
                "INSERT INTO show_cast (show_id, actor_id, character_name, cast_order) VALUES (1, 1, 'Role', 0)"
            )
            db.execute(
                "INSERT INTO movie_cast (movie_id, actor_id, character_name, cast_order) VALUES (1, 1, 'Role', 1)"
            )
            db.execute("DELETE FROM actors WHERE id = 1")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM show_cast").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM movie_cast").fetchone()[0], 0)
            db.close()

if __name__ == "__main__":
    unittest.main()
