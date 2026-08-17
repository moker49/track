import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import create_app


class TrackAppTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "test.db"
        self.app = create_app({"TESTING": True, "DATABASE": str(self.database)})
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_primary_pages_render(self):
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn(b"Breaking Bad", home.data)
        self.assertIn(b"5 of 13", home.data)
        self.assertIn(b"Search your shows", home.data)
        self.assertNotIn(b"app-bar-title", home.data)
        self.assertNotIn(b'class="avatar"', home.data)
        self.assertIn(b'<span class="nav-icon" aria-hidden="true">\n          <span class="search-glyph"></span>', home.data)

        detail = self.client.get("/shows/1")
        self.assertEqual(detail.status_code, 200)
        self.assertIn(b"Season 1", detail.data)
        self.assertIn(b"Seven Thirty-Seven", detail.data)
        self.assertIn(b"arrow_back", detail.data)

        search = self.client.get("/search")
        self.assertEqual(search.status_code, 200)
        self.assertIn(b"Popular now", search.data)
        self.assertIn(b"Discover", search.data)
        self.assertIn(b"Search TMDB", search.data)

    def test_my_shows_search_filters_local_library(self):
        match = self.client.get("/?q=breaking")
        self.assertIn(b"Breaking Bad", match.data)

        no_match = self.client.get("/?q=severance")
        self.assertNotIn(b'class="show-card"', no_match.data)
        self.assertIn(b"No shows match", no_match.data)

    def test_discover_query_stays_ready_for_tmdb(self):
        response = self.client.get("/search?q=andor")
        self.assertIn(b"Search ready for TMDB", response.data)
        self.assertIn(b"andor", response.data)

    def test_watched_toggle_updates_progress_and_preserves_history(self):
        unwatch = self.client.post("/api/episodes/1/watched", json={"watched": False})
        self.assertEqual(unwatch.status_code, 200)
        self.assertEqual(unwatch.get_json()["watched_count"], 4)

        rewatch = self.client.post("/api/episodes/1/watched", json={"watched": True})
        self.assertEqual(rewatch.status_code, 200)
        self.assertEqual(rewatch.get_json()["watched_count"], 5)

        db = sqlite3.connect(self.database)
        rows = db.execute(
            "SELECT watched_at, unwatched_at FROM episode_watch_history WHERE episode_id = 1 ORDER BY id"
        ).fetchall()
        db.close()
        self.assertEqual(len(rows), 2)
        self.assertIsNotNone(rows[0][1])
        self.assertIsNone(rows[1][1])

    def test_api_validates_input(self):
        response = self.client.post("/api/episodes/1/watched", json={"watched": "yes"})
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
