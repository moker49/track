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

    def test_single_page_shell_contains_primary_views(self):
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn(b"Breaking Bad", home.data)
        self.assertIn(b"Game of Thrones", home.data)
        self.assertIn(b"Archived", home.data)
        self.assertIn(b"Finished", home.data)
        self.assertIn(b"more_vert", home.data)
        self.assertIn(b"Un-archive", home.data)
        self.assertIn(b"Remove", home.data)
        self.assertIn(b"Popular now", home.data)
        self.assertIn(b"Search your shows", home.data)
        self.assertIn(b"Search TMDB", home.data)
        self.assertIn(b'data-view="shows"', home.data)
        self.assertIn(b'data-view="discover"', home.data)
        self.assertIn(b'data-view="detail"', home.data)
        self.assertIn(b'id="detail-skeleton-template"', home.data)
        self.assertEqual(home.data.count(b"data-clear-search"), 2)
        self.assertEqual(home.data.count(b">close</span>"), 2)
        self.assertIn(b'data-show-id="1"', home.data)
        self.assertNotIn(b'href="/search"', home.data)
        self.assertNotIn(b'href="/shows/1"', home.data)
        self.assertIn(b'<span class="material-symbols-rounded">tv</span>', home.data)
        self.assertIn(b'<span class="material-symbols-rounded">explore</span>', home.data)

    def test_show_details_are_a_fragment(self):
        detail = self.client.get("/api/shows/1")
        self.assertEqual(detail.status_code, 200)
        self.assertIn(b"Season 1", detail.data)
        self.assertIn(b"Seven Thirty-Seven", detail.data)
        self.assertIn(b"arrow_back", detail.data)
        self.assertNotIn(b'<details class="season" open', detail.data)
        self.assertNotIn(b"<!doctype html>", detail.data.lower())
        self.assertNotIn(b"bottom-nav", detail.data)

        archived_detail = self.client.get("/api/shows/2")
        self.assertEqual(archived_detail.status_code, 200)
        self.assertIn(b"Game of Thrones", archived_detail.data)
        self.assertIn(b"Un-archive", archived_detail.data)
        self.assertIn(b"more_vert", archived_detail.data)

        missing = self.client.get("/api/shows/999")
        self.assertEqual(missing.status_code, 404)

    def test_legacy_page_urls_redirect_to_shell(self):
        for path in ("/search", "/search?q=andor", "/shows/1"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.headers["Location"], "/")

    def test_material_icon_font_is_local(self):
        home = self.client.get("/")
        self.assertNotIn(b"Material+Symbols", home.data)

        icon_font = self.client.get("/static/fonts/material-symbols-rounded.ttf")
        self.assertEqual(icon_font.status_code, 200)
        self.assertGreater(len(icon_font.data), 1_000_000)
        icon_font.close()

        filled_font = self.client.get(
            "/static/fonts/material-symbols-rounded-filled.ttf"
        )
        self.assertEqual(filled_font.status_code, 200)
        self.assertGreater(len(filled_font.data), 1_000_000)
        filled_font.close()

    def test_watched_toggle_updates_progress_and_preserves_history(self):
        unwatch = self.client.post("/api/episodes/1/watched", json={"watched": False})
        self.assertEqual(unwatch.status_code, 200)
        self.assertEqual(unwatch.get_json()["show_id"], 1)
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

    def test_progress_tag_supports_not_started(self):
        db = sqlite3.connect(self.database)
        db.execute(
            """
            UPDATE episode_watch_history
            SET unwatched_at = '2026-08-17T12:00:00+00:00'
            WHERE episode_id IN (
                SELECT e.id FROM episodes e
                JOIN seasons s ON s.id = e.season_id
                WHERE s.show_id = 1
            )
            """
        )
        db.commit()
        db.close()

        home = self.client.get("/")
        self.assertIn(b"Haven&#39;t started", home.data)

    def test_show_can_be_archived_and_unarchived_with_history(self):
        archive = self.client.post(
            "/api/shows/1/state", json={"state": "ARCHIVED"}
        )
        self.assertEqual(archive.status_code, 200)
        self.assertEqual(archive.get_json()["move_label"], "Un-archive")

        unarchive = self.client.post(
            "/api/shows/1/state", json={"state": "ACTIVE"}
        )
        self.assertEqual(unarchive.status_code, 200)
        self.assertEqual(unarchive.get_json()["move_label"], "Archive")

        db = sqlite3.connect(self.database)
        state = db.execute("SELECT state FROM shows WHERE id = 1").fetchone()[0]
        transitions = db.execute(
            "SELECT state FROM show_state_history WHERE show_id = 1 ORDER BY id DESC LIMIT 2"
        ).fetchall()
        db.close()
        self.assertEqual(state, "ACTIVE")
        self.assertEqual([row[0] for row in transitions], ["ACTIVE", "ARCHIVED"])

        invalid = self.client.post(
            "/api/shows/1/state", json={"state": "WATCHLIST"}
        )
        self.assertEqual(invalid.status_code, 400)

    def test_removing_show_cascades_to_episodes_and_history(self):
        remove = self.client.delete("/api/shows/2")
        self.assertEqual(remove.status_code, 204)

        db = sqlite3.connect(self.database)
        show_count = db.execute("SELECT COUNT(*) FROM shows WHERE id = 2").fetchone()[0]
        season_count = db.execute(
            "SELECT COUNT(*) FROM seasons WHERE show_id = 2"
        ).fetchone()[0]
        episode_count = db.execute(
            """
            SELECT COUNT(*) FROM episodes e
            JOIN seasons s ON s.id = e.season_id
            WHERE s.show_id = 2
            """
        ).fetchone()[0]
        db.close()
        self.assertEqual((show_count, season_count, episode_count), (0, 0, 0))

    def test_api_validates_input(self):
        response = self.client.post("/api/episodes/1/watched", json={"watched": "yes"})
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
