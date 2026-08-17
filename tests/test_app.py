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
        self.assertIn(b"Search watching", home.data)
        self.assertIn(b"Search archive", home.data)
        self.assertIn(b"Search TMDB", home.data)
        self.assertIn(b'data-view="watching"', home.data)
        self.assertIn(b'data-view="archive"', home.data)
        self.assertIn(b'data-view="discover"', home.data)
        self.assertIn(b'data-view="detail"', home.data)
        self.assertIn(b'id="detail-skeleton-template"', home.data)
        self.assertEqual(home.data.count(b"data-clear-search"), 3)
        self.assertEqual(home.data.count(b">close</span>"), 3)
        self.assertIn(b'data-progress-state="in-progress"', home.data)
        self.assertIn(b'data-progress-state="finished"', home.data)
        self.assertIn(b'data-show-id="1"', home.data)
        self.assertNotIn(b'href="/search"', home.data)
        self.assertNotIn(b'href="/shows/1"', home.data)
        self.assertIn(b'<span class="material-symbols-rounded">tv</span>', home.data)
        self.assertIn(b'<span class="material-symbols-rounded">inventory_2</span>', home.data)
        self.assertIn(b'<span class="material-symbols-rounded">explore</span>', home.data)

    def test_show_details_are_a_fragment(self):
        detail = self.client.get("/api/shows/1")
        self.assertEqual(detail.status_code, 200)
        self.assertIn(b"Season 1", detail.data)
        self.assertIn(b"Seven Thirty-Seven", detail.data)
        self.assertIn(b"arrow_back", detail.data)
        self.assertNotIn(b'<details class="season" open', detail.data)
        self.assertIn(b"data-season-watch", detail.data)
        self.assertIn(b"data-episode-watch", detail.data)
        self.assertIn(b'data-detail-title="Breaking Bad"', detail.data)
        self.assertIn(b'class="detail-app-bar-title">Show details</span>', detail.data)
        self.assertIn(b'data-activity-log', detail.data)
        self.assertIn(b"Added to My Shows", detail.data)
        self.assertNotIn(b'<details class="activity-log" open', detail.data)
        self.assertIn(b"rewatch", detail.data)
        self.assertIn(b"unwatch", detail.data)
        self.assertIn(b'aria-checked="mixed"', detail.data)
        self.assertIn(b'aria-checked="false"', detail.data)
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
        for path in ("/search", "/search?q=andor", "/shows/1", "/episodes/1"):
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

    def test_open_watch_menu_elevates_its_season(self):
        css = (Path(__file__).parents[1] / "static" / "app.css").read_text()
        self.assertIn('.season:has(.watch-menu:not([hidden]))', css)
        self.assertIn("z-index: 30", css)

    def test_season_cards_form_an_attached_stack(self):
        css = (Path(__file__).parents[1] / "static" / "app.css").read_text(
            encoding="utf-8"
        )
        self.assertIn(".season:not(:first-child)", css)
        self.assertIn("border-start-start-radius: 4px", css)
        self.assertIn(".season:not(:last-child)", css)
        self.assertIn("border-end-end-radius: 4px", css)

    def test_episode_number_is_vertically_centered(self):
        css = (Path(__file__).parents[1] / "static" / "app.css").read_text(
            encoding="utf-8"
        )
        self.assertIn(".episode-title span", css)
        self.assertIn("top: 50%", css)
        self.assertIn("transform: translateY(-50%)", css)

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
            "SELECT added_at, watch_date FROM episode_watch_history WHERE episode_id = 1 ORDER BY id"
        ).fetchall()
        db.close()
        self.assertEqual(len(rows), 1)
        self.assertIsNotNone(rows[0][0])
        self.assertIsNone(rows[0][1])

    def test_episode_watch_count_increments_and_decrements_one_event(self):
        increment = self.client.post(
            "/api/episodes/1/watch-count", json={"action": "increment"}
        )
        self.assertEqual(increment.status_code, 200)
        self.assertEqual(increment.get_json()["watch_count"], 2)
        self.assertEqual(increment.get_json()["watched_count"], 5)

        decrement = self.client.post(
            "/api/episodes/1/watch-count", json={"action": "decrement"}
        )
        self.assertEqual(decrement.status_code, 200)
        self.assertEqual(decrement.get_json()["watch_count"], 1)
        self.assertEqual(decrement.get_json()["watched_count"], 5)

        final_decrement = self.client.post(
            "/api/episodes/1/watch-count", json={"action": "decrement"}
        )
        self.assertEqual(final_decrement.get_json()["watch_count"], 0)
        self.assertEqual(final_decrement.get_json()["watched_count"], 4)

        db = sqlite3.connect(self.database)
        history = db.execute(
            "SELECT added_at, watch_date FROM episode_watch_history WHERE episode_id = 1 ORDER BY id"
        ).fetchall()
        db.close()
        self.assertEqual(history, [])

    def test_season_watch_count_is_atomic_and_progress_counts_distinct_episodes(self):
        first_watch = self.client.post(
            "/api/seasons/2/watch-count", json={"action": "increment"}
        )
        self.assertEqual(first_watch.status_code, 200)
        first_data = first_watch.get_json()
        self.assertEqual(first_data["season_watched_count"], 6)
        self.assertEqual(first_data["watched_count"], 11)
        self.assertTrue(all(item["watch_count"] == 1 for item in first_data["episodes"]))

        rewatch = self.client.post(
            "/api/seasons/2/watch-count", json={"action": "increment"}
        )
        rewatch_data = rewatch.get_json()
        self.assertEqual(rewatch_data["watched_count"], 11)
        self.assertTrue(all(item["watch_count"] == 2 for item in rewatch_data["episodes"]))

        unwatch = self.client.post(
            "/api/seasons/2/watch-count", json={"action": "decrement"}
        )
        self.assertTrue(
            all(item["watch_count"] == 1 for item in unwatch.get_json()["episodes"])
        )

        fully_unwatched = self.client.post(
            "/api/seasons/2/watch-count", json={"action": "decrement"}
        )
        fully_unwatched_data = fully_unwatched.get_json()
        self.assertEqual(fully_unwatched_data["season_watched_count"], 0)
        self.assertEqual(fully_unwatched_data["watched_count"], 5)
        self.assertTrue(
            all(
                item["watch_count"] == 0
                for item in fully_unwatched_data["episodes"]
            )
        )

    def test_season_watch_activity_is_retired_by_unwatch(self):
        watched = self.client.post(
            "/api/seasons/2/watch-count", json={"action": "increment"}
        )
        self.assertEqual(watched.status_code, 200)
        self.assertIsNotNone(watched.get_json()["season_watched_at"])
        season_record_id = watched.get_json()["season_watch_record_id"]
        dated = self.client.patch(
            f"/api/watch-history/season/{season_record_id}/date",
            json={"watch_date": "2025-05-15"},
        )
        self.assertEqual(dated.status_code, 200)

        detail = self.client.get("/api/shows/1")
        self.assertIn(b"Season 2 watched", detail.data)
        self.assertIn(b'data-season-id="2"', detail.data)
        self.assertIn(b'data-watch-date="2025-05-15"', detail.data)

        unwatched = self.client.post(
            "/api/seasons/2/watch-count", json={"action": "decrement"}
        )
        self.assertEqual(unwatched.status_code, 200)
        self.assertEqual(
            unwatched.get_json()["season_watch_record_id"], season_record_id
        )
        detail_after = self.client.get("/api/shows/1")
        self.assertNotIn(b"Season 2 watched", detail_after.data)

        db = sqlite3.connect(self.database)
        rows = db.execute(
            "SELECT added_at, watch_date FROM season_watch_history WHERE season_id = 2"
        ).fetchall()
        db.close()
        self.assertEqual(rows, [])

    def test_episode_detail_is_a_fragment_with_active_watch_log(self):
        detail = self.client.get("/api/episodes/1")
        self.assertEqual(detail.status_code, 200)
        self.assertIn(b'data-detail-episode', detail.data)
        self.assertIn(b'data-detail-title="Pilot"', detail.data)
        self.assertIn(b'class="detail-app-bar-title">Episode details</span>', detail.data)
        self.assertIn(b'data-back-show-id="1"', detail.data)
        self.assertIn(b"Watch log", detail.data)
        self.assertIn(b'data-activity-type="watched"', detail.data)
        self.assertIn(b'class="activity-log watch-log"', detail.data)
        self.assertNotIn(b'<details class="activity-log watch-log"', detail.data)
        self.assertIn(b'data-watch-log-entry', detail.data)
        self.assertNotIn(b"season-list", detail.data)
        self.assertNotIn(b"<!doctype html>", detail.data.lower())

        self.client.post(
            "/api/episodes/1/watch-count", json={"action": "increment"}
        )
        rewatched_detail = self.client.get("/api/episodes/1")
        self.assertEqual(
            rewatched_detail.data.count(b'data-activity-type="watched"'), 2
        )

        self.client.post(
            "/api/episodes/1/watch-count", json={"action": "decrement"}
        )
        unwatched_detail = self.client.get("/api/episodes/1")
        self.assertEqual(
            unwatched_detail.data.count(b'data-activity-type="watched"'), 1
        )

        missing = self.client.get("/api/episodes/999")
        self.assertEqual(missing.status_code, 404)

    def test_rewatch_count_is_rendered_in_checkbox_control(self):
        self.client.post(
            "/api/episodes/1/watch-count", json={"action": "increment"}
        )

        detail = self.client.get("/api/shows/1")

        self.assertEqual(detail.status_code, 200)
        self.assertIn(b'data-watch-count="2"', detail.data)
        self.assertIn(b'data-watch-counter', detail.data)
        self.assertIn(b'>2</span>', detail.data)

    def test_progress_tag_supports_not_started(self):
        db = sqlite3.connect(self.database)
        db.execute(
            """
            DELETE FROM episode_watch_history
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
        self.assertIn(b'data-progress-state="not-started"', home.data)

    def test_partial_archived_show_is_stopped(self):
        response = self.client.post(
            "/api/episodes/14/watched", json={"watched": False}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["watched_count"], 11)

        home = self.client.get("/")
        self.assertIn(b">Stopped</span>", home.data)
        self.assertIn(b'data-progress-state="stopped"', home.data)

    def test_progress_colors_share_status_variables(self):
        css = (Path(__file__).parents[1] / "static" / "app.css").read_text(
            encoding="utf-8"
        )
        self.assertIn("--progress-complete: var(--accent)", css)
        self.assertIn("--progress-not-started:", css)
        self.assertIn("--progress-stopped: var(--error)", css)
        self.assertIn("background: var(--progress-color", css)

    def test_watch_records_have_added_and_optional_user_dates(self):
        db = sqlite3.connect(self.database)
        episode_columns = [
            row[1] for row in db.execute("PRAGMA table_info(episode_watch_history)")
        ]
        season_columns = [
            row[1] for row in db.execute("PRAGMA table_info(season_watch_history)")
        ]
        db.close()
        self.assertEqual(
            episode_columns, ["id", "episode_id", "added_at", "watch_date"]
        )
        self.assertEqual(
            season_columns, ["id", "season_id", "added_at", "watch_date"]
        )

    def test_watch_date_can_be_set_cleared_sorted_and_controls_unwatch_order(self):
        self.client.post(
            "/api/episodes/1/watch-count", json={"action": "increment"}
        )
        db = sqlite3.connect(self.database)
        record_ids = [
            row[0]
            for row in db.execute(
                "SELECT id FROM episode_watch_history WHERE episode_id = 1 ORDER BY id"
            )
        ]
        db.close()
        self.assertEqual(len(record_ids), 2)

        chosen = self.client.patch(
            f"/api/watch-history/episode/{record_ids[0]}/date",
            json={"watch_date": "2030-05-15"},
        )
        self.assertEqual(chosen.status_code, 200)
        self.assertEqual(chosen.get_json()["display_date"], "2030-05-15")

        detail = self.client.get("/api/episodes/1")
        first_position = detail.data.index(
            f'data-watch-record-id="{record_ids[0]}"'.encode()
        )
        second_position = detail.data.index(
            f'data-watch-record-id="{record_ids[1]}"'.encode()
        )
        self.assertLess(first_position, second_position)

        decrement = self.client.post(
            "/api/episodes/1/watch-count", json={"action": "decrement"}
        )
        self.assertEqual(decrement.get_json()["watch_count"], 1)
        db = sqlite3.connect(self.database)
        remaining_ids = [
            row[0]
            for row in db.execute(
                "SELECT id FROM episode_watch_history WHERE episode_id = 1"
            )
        ]
        db.close()
        self.assertEqual(remaining_ids, [record_ids[1]])

        cleared = self.client.patch(
            f"/api/watch-history/episode/{record_ids[1]}/date",
            json={"watch_date": None},
        )
        self.assertEqual(cleared.status_code, 200)
        self.assertIsNone(cleared.get_json()["watch_date"])

    def test_date_picker_and_compact_date_formatter_are_in_the_shell(self):
        home = self.client.get("/")
        self.assertIn(b'data-date-picker', home.data)
        self.assertIn(b"Select watch date", home.data)
        javascript = (Path(__file__).parents[1] / "static" / "app.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("function formatDisplayDate", javascript)
        self.assertIn('month: "short"', javascript)
        self.assertNotIn("ordinalSuffix", javascript)
        self.assertNotIn("timeStyle", javascript)

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

        detail = self.client.get("/api/shows/1")
        self.assertIn(b">Archived</strong>", detail.data)
        self.assertIn(b">Un-archived</strong>", detail.data)

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
        episode_action = self.client.post(
            "/api/episodes/1/watch-count", json={"action": "reset"}
        )
        self.assertEqual(episode_action.status_code, 400)
        season_action = self.client.post(
            "/api/seasons/1/watch-count", json={"action": "reset"}
        )
        self.assertEqual(season_action.status_code, 400)
        invalid_date = self.client.patch(
            "/api/watch-history/episode/1/date", json={"watch_date": "May 15"}
        )
        self.assertEqual(invalid_date.status_code, 400)
        invalid_kind = self.client.patch(
            "/api/watch-history/show/1/date", json={"watch_date": None}
        )
        self.assertEqual(invalid_kind.status_code, 404)


if __name__ == "__main__":
    unittest.main()
