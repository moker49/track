import sqlite3
import tempfile
import unittest
import json
import os
from pathlib import Path
from unittest import mock

from app import create_app


class TrackAppTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "test.db"
        self.app = create_app(
            {"TESTING": True, "DATABASE": str(self.database), "SEED_DEMO_DATA": True}
        )
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
        self.assertEqual(home.data.count(b">close</span>"), 4)
        self.assertIn(b'data-progress-state="in-progress"', home.data)
        self.assertIn(b'data-progress-state="finished"', home.data)
        self.assertIn(b'data-show-id="1"', home.data)
        self.assertNotIn(b'href="/search"', home.data)
        self.assertNotIn(b'href="/shows/1"', home.data)
        self.assertIn(b'<span class="material-symbols-rounded">tv</span>', home.data)
        self.assertIn(b'<span class="material-symbols-rounded">inventory_2</span>', home.data)
        self.assertIn(b'<span class="material-symbols-rounded">explore</span>', home.data)

    def test_library_filter_and_sort_dialog_is_in_the_shell(self):
        home = self.client.get("/")
        self.assertEqual(home.data.count(b"data-open-library-filter"), 2)
        self.assertIn(b'data-library-filter-dialog', home.data)
        self.assertEqual(home.data.count(b"data-filter-tag="), 4)
        self.assertIn(b'data-sort-field="name" aria-pressed="true"', home.data)
        self.assertIn(b'data-sort-field="dateAdded"', home.data)
        self.assertIn(b'data-sort-field="releaseDate"', home.data)
        self.assertIn(b'data-sort-direction="asc" aria-pressed="true"', home.data)
        self.assertIn(b'data-date-added=', home.data)
        self.assertIn(b'data-release-date=', home.data)
        self.assertEqual(home.data.count(b'class="md-button-group'), 3)
        self.assertIn(b'class="filter-fullscreen-app-bar"', home.data)
        self.assertIn(b">Done</button>", home.data)
        self.assertIn(b"<span>New</span>", home.data)
        self.assertIn(b"<span>Watching</span>", home.data)
        self.assertNotIn(b"Haven&#39;t started", home.data)
        self.assertNotIn(b"In progress", home.data)

        javascript = (Path(__file__).parents[1] / "static" / "app.js").read_text(
            encoding="utf-8"
        )
        self.assertIn('sortField: "name", sortDirection: "asc"', javascript)
        self.assertIn("preferences.tags.size === 0", javascript)
        self.assertIn("const customized = preferences.tags.size > 0;", javascript)
        self.assertNotIn("preferences.sortField !==", javascript)
        self.assertNotIn("preferences.sortDirection !==", javascript)

        css = (Path(__file__).parents[1] / "static" / "app.css").read_text(
            encoding="utf-8"
        )
        self.assertIn("height: 100dvh", css)
        self.assertIn("grid-template-columns: repeat(4, minmax(0, 1fr))", css)
        self.assertIn('.md-button-group button[aria-pressed="true"] {\n  border-radius: 24px;', css)
        self.assertIn("color: var(--progress-not-started);", css)
        self.assertIn(
            "background: color-mix(in srgb, var(--progress-not-started) 18%, transparent);",
            css,
        )

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
        self.assertIn(b'<span class="state-label progress-tag" data-progress-tag>Watching</span>', detail.data)
        self.assertNotIn(b"data-show-state-label", detail.data)
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
        self.assertIn(b'<span class="state-label progress-tag" data-progress-tag>Finished</span>', archived_detail.data)
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

    def test_progress_tag_supports_new(self):
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
        self.assertIn(b">New</span>", home.data)
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
            "/api/shows/1/state", json={"state": "PAUSED"}
        )
        self.assertEqual(invalid.status_code, 400)

    def test_removing_show_demotes_it_and_preserves_metadata_and_history(self):
        db = sqlite3.connect(self.database)
        before = db.execute(
            """
            SELECT (SELECT COUNT(*) FROM seasons WHERE show_id = 2),
                   (SELECT COUNT(*) FROM episodes e JOIN seasons s ON s.id = e.season_id WHERE s.show_id = 2),
                   (SELECT COUNT(*) FROM episode_watch_history wh
                    JOIN episodes e ON e.id = wh.episode_id
                    JOIN seasons s ON s.id = e.season_id WHERE s.show_id = 2)
            """
        ).fetchone()
        db.close()

        remove = self.client.delete("/api/shows/2")
        self.assertEqual(remove.status_code, 204)

        db = sqlite3.connect(self.database)
        tracked = db.execute("SELECT is_tracked FROM shows WHERE id = 2").fetchone()[0]
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
        history_count = db.execute(
            """
            SELECT COUNT(*) FROM episode_watch_history wh
            JOIN episodes e ON e.id = wh.episode_id
            JOIN seasons s ON s.id = e.season_id
            WHERE s.show_id = 2
            """
        ).fetchone()[0]
        db.close()
        self.assertEqual(tracked, 0)
        self.assertEqual((season_count, episode_count, history_count), before)
        self.assertNotIn(b"Game of Thrones", self.client.get("/").data)
        detail = self.client.get("/api/shows/2")
        self.assertIn(b'data-track-show-state="ACTIVE"', detail.data)

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

    def test_fresh_database_has_no_demo_data_or_watchlist_state(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "empty.db"
            empty_app = create_app(
                {"TESTING": True, "DATABASE": str(database), "SEED_DEMO_DATA": False}
            )
            with empty_app.app_context():
                connection = sqlite3.connect(database)
                show_count = connection.execute("SELECT COUNT(*) FROM shows").fetchone()[0]
                show_sql = connection.execute(
                    "SELECT sql FROM sqlite_schema WHERE name = 'shows'"
                ).fetchone()[0]
                columns = [
                    row[1] for row in connection.execute("PRAGMA table_info(shows)")
                ]
                connection.close()
            self.assertEqual(show_count, 0)
            self.assertNotIn("WATCHLIST", show_sql)
            self.assertNotIn("watchlist_at", columns)

    def test_dotenv_token_is_loaded_without_overriding_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dotenv_path = root / ".env"
            dotenv_path.write_text(
                "TMDB_READ_ACCESS_TOKEN=token-from-file\n", encoding="utf-8"
            )
            with mock.patch.dict(os.environ, {}, clear=True):
                dotenv_app = create_app(
                    {
                        "TESTING": True,
                        "DATABASE": str(root / "dotenv.db"),
                        "DOTENV_PATH": dotenv_path,
                        "SEED_DEMO_DATA": False,
                    }
                )
                self.assertEqual(
                    dotenv_app.config["TMDB_READ_ACCESS_TOKEN"], "token-from-file"
                )

            with mock.patch.dict(
                os.environ, {"TMDB_READ_ACCESS_TOKEN": "token-from-environment"}, clear=True
            ):
                environment_app = create_app(
                    {
                        "TESTING": True,
                        "DATABASE": str(root / "environment.db"),
                        "DOTENV_PATH": dotenv_path,
                        "SEED_DEMO_DATA": False,
                    }
                )
                self.assertEqual(
                    environment_app.config["TMDB_READ_ACCESS_TOKEN"],
                    "token-from-environment",
                )

    def test_popular_results_are_cached_for_one_day_and_search_is_remote(self):
        class FakeClient:
            def __init__(self):
                self.popular_calls = 0
                self.search_calls = []

            def popular_tv(self):
                self.popular_calls += 1
                return {"results": [{"id": 20, "name": "Popular Show"}]}

            def search_tv(self, query):
                self.search_calls.append(query)
                return {"results": [{"id": 21, "name": f"Result {query}"}]}

        fake = FakeClient()
        self.app.config.update(
            TMDB_READ_ACCESS_TOKEN="test-token",
            TMDB_CLIENT_FACTORY=lambda _token: fake,
        )
        first = self.client.get("/api/discover/popular")
        second = self.client.get("/api/discover/popular")
        search = self.client.get("/api/discover/search?q=Severance")

        self.assertEqual(first.status_code, 200)
        self.assertFalse(first.get_json()["cached"])
        self.assertTrue(second.get_json()["cached"])
        self.assertEqual(fake.popular_calls, 1)
        self.assertEqual(search.status_code, 200)
        self.assertEqual(fake.search_calls, ["Severance"])

    def test_import_is_atomic_deduplicated_and_specials_do_not_count(self):
        show_payload = {
            "id": 900,
            "name": "Imported Show",
            "original_name": "Imported Show",
            "overview": "Imported locally.",
            "first_air_date": "2020-01-01",
            "genres": [{"id": 18, "name": "Drama"}],
            "networks": [{"id": 1, "name": "A Network"}],
        }
        seasons = [
            {
                "id": 901,
                "season_number": 0,
                "name": "Specials",
                "episodes": [
                    {"id": 902, "episode_number": 1, "name": "Extra", "air_date": "2020-01-01"}
                ],
            },
            {
                "id": 903,
                "season_number": 1,
                "name": "Season 1",
                "episodes": [
                    {"id": 904, "episode_number": 1, "name": "Pilot", "air_date": "2020-01-02"}
                ],
            },
        ]

        class FakeClient:
            def show_bundle(self, tmdb_id):
                self.last_id = tmdb_id
                return show_payload, seasons

        fake = FakeClient()
        self.app.config.update(
            TMDB_READ_ACCESS_TOKEN="test-token",
            TMDB_CLIENT_FACTORY=lambda _token: fake,
        )
        imported = self.client.post(
            "/api/discover/shows/900/import", json={"state": "ACTIVE"}
        )
        duplicate = self.client.post(
            "/api/discover/shows/900/import", json={"state": "ARCHIVED"}
        )

        self.assertEqual(imported.status_code, 200)
        self.assertTrue(imported.get_json()["created"])
        self.assertTrue(imported.get_json()["newly_tracked"])
        self.assertIn("show-card", imported.get_json()["card_html"])
        self.assertFalse(duplicate.get_json()["created"])
        self.assertEqual(duplicate.get_json()["state"], "ACTIVE")

        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        imported_show = connection.execute(
            "SELECT * FROM shows WHERE tmdb_id = 900"
        ).fetchone()
        season_flags = connection.execute(
            "SELECT season_number, is_progress_counted FROM seasons WHERE show_id = ? ORDER BY season_number",
            (imported_show["id"],),
        ).fetchall()
        special_episode_id = connection.execute(
            "SELECT id FROM episodes WHERE tmdb_id = 902"
        ).fetchone()[0]
        regular_episode_id = connection.execute(
            "SELECT id FROM episodes WHERE tmdb_id = 904"
        ).fetchone()[0]
        connection.close()

        self.assertEqual(json.loads(imported_show["tmdb_payload"])["networks"][0]["name"], "A Network")
        self.assertEqual([tuple(row) for row in season_flags], [(0, 0), (1, 1)])
        watched_special = self.client.post(
            f"/api/episodes/{special_episode_id}/watched", json={"watched": True}
        )
        self.assertEqual(watched_special.get_json()["episode_count"], 1)
        self.assertEqual(watched_special.get_json()["watched_count"], 0)

        self.client.post(
            f"/api/episodes/{regular_episode_id}/watched", json={"watched": True}
        )
        seasons[1]["episodes"][0]["name"] = "Updated Pilot"
        refreshed = self.client.post(
            f"/api/shows/{imported_show['id']}/refresh"
        )
        self.assertEqual(refreshed.status_code, 200)
        connection = sqlite3.connect(self.database)
        refreshed_episode = connection.execute(
            "SELECT id, name FROM episodes WHERE tmdb_id = 904"
        ).fetchone()
        history_count = connection.execute(
            "SELECT COUNT(*) FROM episode_watch_history WHERE episode_id = ?",
            (regular_episode_id,),
        ).fetchone()[0]
        connection.close()
        self.assertEqual(refreshed_episode, (regular_episode_id, "Updated Pilot"))
        self.assertEqual(history_count, 1)

    def test_discover_preview_stays_untracked_until_added(self):
        show_payload = {
            "id": 920,
            "name": "Preview Show",
            "overview": "A show opened from Discover.",
            "first_air_date": "2022-04-10",
            "genres": [{"id": 18, "name": "Drama"}],
        }
        seasons = [
            {
                "id": 921,
                "season_number": 1,
                "name": "Season 1",
                "episodes": [
                    {
                        "id": 922,
                        "episode_number": 1,
                        "name": "First Look",
                        "air_date": "2022-04-10",
                    }
                ],
            }
        ]

        class FakeClient:
            def show_bundle(self, _tmdb_id):
                return show_payload, seasons

        self.app.config.update(
            TMDB_READ_ACCESS_TOKEN="test-token",
            TMDB_CLIENT_FACTORY=lambda _token: FakeClient(),
        )

        preview = self.client.post(
            "/api/discover/shows/920/import", json={"state": None}
        )
        preview_data = preview.get_json()
        self.assertEqual(preview.status_code, 200)
        self.assertTrue(preview_data["created"])
        self.assertFalse(preview_data["newly_tracked"])
        self.assertFalse(preview_data["is_tracked"])
        self.assertIsNone(preview_data["card_html"])

        home = self.client.get("/")
        self.assertNotIn(b"Preview Show", home.data)
        detail = self.client.get(f"/api/shows/{preview_data['show_id']}")
        self.assertIn(b'data-track-show-state="ACTIVE"', detail.data)
        self.assertIn(b'data-track-show-state="ARCHIVED"', detail.data)
        self.assertNotIn(b"data-progress-summary", detail.data)
        self.assertNotIn(b"data-show-menu-button", detail.data)

        tracked = self.client.post(
            f"/api/shows/{preview_data['show_id']}/state",
            json={"state": "ARCHIVED"},
        )
        tracked_data = tracked.get_json()
        self.assertEqual(tracked.status_code, 200)
        self.assertTrue(tracked_data["newly_tracked"])
        self.assertIn("show-card", tracked_data["card_html"])

        tracked_detail = self.client.get(f"/api/shows/{preview_data['show_id']}")
        self.assertIn(b"data-progress-summary", tracked_detail.data)
        self.assertNotIn(b"data-track-show-state", tracked_detail.data)
        archived_home = self.client.get("/")
        self.assertIn(b"Preview Show", archived_home.data)

    def test_discover_cards_have_edge_poster_and_tracked_highlight_styles(self):
        css = (Path(__file__).parents[1] / "static" / "app.css").read_text(
            encoding="utf-8"
        )
        javascript = (Path(__file__).parents[1] / "static" / "app.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("grid-template-columns: 88px 1fr", css)
        self.assertIn("overflow: hidden", css)
        self.assertIn(".popular-card.is-added", css)
        self.assertIn(
            "background: color-mix(in srgb, var(--accent) 12%, var(--surface-card))",
            css,
        )
        self.assertIn(".popular-card.is-added::after", css)
        self.assertIn("inset: 0 0 0 auto", css)
        self.assertNotIn("box-shadow: inset 0 0 0 2px var(--accent)", css)
        self.assertIn('card.querySelector(".popular-card-actions")?.remove()', javascript)
        self.assertIn('openShow(data.show_id, "discover", false)', javascript)
        self.assertIn("const cachedShowId = card.dataset.showId", javascript)
        self.assertIn('await openShow(cachedShowId, "discover")', javascript)
        self.assertIn("function markCatalogUntracked", javascript)

    def test_failed_import_rolls_back_every_record(self):
        class BrokenClient:
            def show_bundle(self, _tmdb_id):
                return (
                    {"id": 910, "name": "Broken"},
                    [{"id": 911, "season_number": 1, "episodes": [{"name": "No id"}]}],
                )

        self.app.config.update(
            TMDB_READ_ACCESS_TOKEN="test-token",
            TMDB_CLIENT_FACTORY=lambda _token: BrokenClient(),
        )
        response = self.client.post(
            "/api/discover/shows/910/import", json={"state": "ACTIVE"}
        )
        self.assertEqual(response.status_code, 502)
        connection = sqlite3.connect(self.database)
        counts = connection.execute(
            "SELECT (SELECT COUNT(*) FROM shows WHERE tmdb_id = 910), "
            "(SELECT COUNT(*) FROM seasons WHERE tmdb_id = 911)"
        ).fetchone()
        connection.close()
        self.assertEqual(counts, (0, 0))


if __name__ == "__main__":
    unittest.main()
