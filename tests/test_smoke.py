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

    def test_episode_rewatch_override_and_unwatch_remove_latest_effective_date(self):
        first = self.client.post("/api/episodes/6/watch-count", json={"action": "increment"})
        second = self.client.post("/api/episodes/6/watch-count", json={"action": "increment"})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.get_json()["watch_count"], 2)
        first_id = first.get_json()["watch_record_id"]
        second_id = second.get_json()["watch_record_id"]
        self.assertEqual(
            self.client.patch(
                f"/api/watch-history/episode/{first_id}/date",
                json={"watch_date": "2099-12-31"},
            ).status_code,
            200,
        )
        decremented = self.client.post("/api/episodes/6/watch-count", json={"action": "decrement"})
        self.assertEqual(decremented.get_json()["watch_record_id"], first_id)
        remaining = self.rows(
            "SELECT id FROM episode_watch_history WHERE episode_id = 6"
        )
        self.assertEqual([row["id"] for row in remaining], [second_id])

    def test_season_watch_and_unwatch_are_atomic_at_the_feature_boundary(self):
        watched = self.client.post("/api/seasons/2/watch-count", json={"action": "increment"})
        self.assertEqual(watched.status_code, 200)
        payload = watched.get_json()
        self.assertEqual(payload["season_episode_count"], 6)
        self.assertEqual(payload["season_watched_count"], 6)
        self.assertGreaterEqual(payload["season_min_watch_count"], 1)
        unwatched = self.client.post("/api/seasons/2/watch-count", json={"action": "decrement"})
        self.assertEqual(unwatched.status_code, 200)
        self.assertEqual(unwatched.get_json()["season_watched_count"], 0)
        self.assertEqual(
            self.rows("SELECT COUNT(*) AS count FROM season_watch_history WHERE season_id = 2")[0]["count"],
            0,
        )

    def test_queue_skip_rotates_and_watching_clears_the_skip(self):
        before = self.client.get("/api/schedule/shows/1/catch-up")
        self.assertEqual(before.status_code, 200)
        self.assertIn(b'data-episode-id="6"', before.data)
        skipped = self.client.post("/api/episodes/6/skip")
        self.assertEqual(skipped.status_code, 200)
        after = self.client.get("/api/schedule/shows/1/catch-up")
        self.assertIn(b'data-episode-id="7"', after.data)
        watched = self.client.post("/api/episodes/6/watched", json={"watched": True})
        self.assertEqual(watched.status_code, 200)
        self.assertEqual(
            self.rows("SELECT COUNT(*) AS count FROM episode_skips WHERE episode_id = 6")[0]["count"],
            0,
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

    def test_invalid_mutations_fail_without_changing_persisted_state(self):
        count = self.rows("SELECT COUNT(*) AS count FROM episode_watch_history")[0]["count"]
        cases = (
            self.client.post("/api/episodes/1/watched", json={"watched": "yes"}),
            self.client.post("/api/episodes/1/watch-count", json={"action": "erase"}),
            self.client.post("/api/seasons/1/watch-count", json={"action": "erase"}),
            self.client.post("/api/shows/1/state", json={"state": "WATCHING"}),
            self.client.patch("/api/watch-history/episode/1/date", json={"watch_date": "not-a-date"}),
        )
        self.assertTrue(all(response.status_code == 400 for response in cases))
        self.assertEqual(
            self.rows("SELECT COUNT(*) AS count FROM episode_watch_history")[0]["count"],
            count,
        )


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
            self.assertIn("show_notes", tables)
            self.assertIn("episode_notes", tables)
            self.assertIn("episode_external_ids", tables)
            self.assertNotIn("schema_migrations", tables)
            self.assertTrue(any(name.startswith("idx_") for name in indexes))


if __name__ == "__main__":
    unittest.main()
