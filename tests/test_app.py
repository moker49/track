import sqlite3
import tempfile
import unittest
import json
import os
import re
import threading
from email.message import Message
from io import BytesIO
from pathlib import Path
from unittest import mock

from app import create_app, start_background_refresh


def seed_test_library(database: Path) -> None:
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executemany(
        """
        INSERT INTO shows (
            id, tmdb_id, name, original_name, overview, tagline,
            first_air_date, status, genres, original_language, state,
            added_at, active_at, archived_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'en', ?, ?, ?, ?)
        """,
        [
            (1, 900001, "Active Test Show", "Active Test Show", "Test overview.", "Test tagline.",
             "2008-01-20", "Ended", "Drama, Crime", "ACTIVE",
             "2026-05-02T19:15:00+00:00", "2026-05-04T00:10:00+00:00", None),
            (2, 900002, "Archived Test Show", "Archived Test Show", "Test overview.", "Test tagline.",
             "2011-04-17", "Ended", "Drama, Fantasy", "ARCHIVED",
             "2026-06-10T18:30:00+00:00", "2026-06-12T00:15:00+00:00", "2026-07-01T02:40:00+00:00"),
        ],
    )
    connection.executemany(
        "INSERT INTO show_state_history (show_id, state, entered_at) VALUES (?, ?, ?)",
        [
            (1, "ACTIVE", "2026-05-04T00:10:00+00:00"),
            (2, "ACTIVE", "2026-06-12T00:15:00+00:00"),
            (2, "ARCHIVED", "2026-07-01T02:40:00+00:00"),
        ],
    )
    season_rows = [
        (1, 1, 3573, 1, "Season 1", "2008-01-20", 7),
        (2, 1, 3574, 2, "Season 2", "2009-03-08", 6),
        (3, 2, 3624, 1, "Season 1", "2011-04-17", 6),
        (4, 2, 3625, 2, "Season 2", "2012-04-01", 6),
    ]
    connection.executemany(
        """
        INSERT INTO seasons (id, show_id, tmdb_id, season_number, name, air_date, episode_count)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        season_rows,
    )
    episode_id = 1
    episode_ids_by_show = {1: [], 2: []}
    for season_id, show_id, _tmdb_id, _number, _name, air_date, count in season_rows:
        for episode_number in range(1, count + 1):
            title = "Episode " + str(episode_number)
            if episode_id == 1:
                title = "Opening Episode"
            elif season_id == 2 and episode_number == 1:
                title = "Season Two Premiere"
            connection.execute(
                """
                INSERT INTO episodes (
                    id, season_id, tmdb_id, episode_number, name, overview,
                    air_date, runtime_minutes
                ) VALUES (?, ?, ?, ?, ?, 'Test episode overview.', ?, 48)
                """,
                (episode_id, season_id, 62000 + episode_id, episode_number, title, air_date),
            )
            episode_ids_by_show[show_id].append(episode_id)
            episode_id += 1
    watched_episode_ids = episode_ids_by_show[1][:5] + episode_ids_by_show[2]
    connection.executemany(
        "INSERT INTO episode_watch_history (episode_id, added_at) VALUES (?, ?)",
        [(episode_id, f"2026-05-{index + 4:02d}T01:20:00+00:00")
         for index, episode_id in enumerate(watched_episode_ids)],
    )
    connection.commit()
    connection.close()


class TrackAppTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "test.db"
        self.app = create_app({"TESTING": True, "DATABASE": str(self.database)})
        seed_test_library(self.database)
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_single_page_shell_contains_primary_views(self):
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn(b"Active Test Show", home.data)
        self.assertIn(b"Archived Test Show", home.data)
        self.assertIn(b"Archived", home.data)
        self.assertIn(b"Finished", home.data)
        self.assertIn(b"more_vert", home.data)
        self.assertIn(b"Resume", home.data)
        self.assertIn(b"Remove", home.data)
        self.assertNotIn(b">Add show</h2>", home.data)
        self.assertIn(b'data-tv-add-results', home.data)
        self.assertNotIn(b'data-tv-search-loading', home.data)
        self.assertIn(b'data-tv-search-empty', home.data)
        self.assertIn(b"No results found", home.data)
        self.assertIn(b'data-global-search-bar', home.data)
        self.assertEqual(home.data.count(b'data-global-search>'), 1)
        self.assertIn(b'aria-label="Menu"', home.data)
        self.assertIn(b'>menu</span>', home.data)
        self.assertIn(b'data-search-back', home.data)
        self.assertIn(b'>arrow_back</span>', home.data)
        self.assertIn(b'aria-label="Profile"', home.data)
        self.assertIn(b'>account_circle</span>', home.data)
        self.assertIn(b'data-clear-search aria-label="Clear search" hidden', home.data)
        self.assertNotIn(b'>search</span>', home.data)
        self.assertIn(b'placeholder="Search queue"', home.data)
        self.assertIn(b'data-view="backlog"', home.data)
        self.assertIn(b'data-view="upcoming"', home.data)
        self.assertIn(b'data-view="tv"', home.data)
        self.assertIn(b'data-image-viewer', home.data)
        self.assertIn(b'data-image-viewer-preview', home.data)
        self.assertIn(b'data-image-viewer-image', home.data)
        self.assertIn(b'data-image-viewer-media', home.data)
        javascript = (Path(__file__).parents[1] / "static" / "app.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("function sizeImageViewerLayers()", javascript)
        self.assertIn("function clearImageViewerMotion()", javascript)
        self.assertIn("function closeImageViewer()", javascript)
        self.assertNotIn(b'data-view="schedule"', home.data)
        self.assertNotIn(b'data-view="archive"', home.data)
        self.assertNotIn(b'data-view="discover"', home.data)
        self.assertIn(b'data-view="detail"', home.data)
        self.assertIn(b'id="detail-loading-template"', home.data)
        self.assertNotIn(b'id="detail-skeleton-template"', home.data)
        self.assertIn(b'class="app-boot-screen"', home.data)
        self.assertIn(b'document.documentElement.classList.add("app-booting")', home.data)
        self.assertIn(b'material-symbols-rounded-filled.ttf', home.data)
        self.assertIn(b'/static/app.css?v=', home.data)
        self.assertIn(b'/static/app.js?v=', home.data)
        self.assertEqual(home.data.count(b"data-clear-search"), 1)
        self.assertEqual(home.data.count(b">close</span>"), 2)
        self.assertIn(b'data-progress-state="started"', home.data)
        self.assertIn(b'data-progress-state="finished"', home.data)
        self.assertIn(b'data-show-id="1"', home.data)
        self.assertNotIn(b'href="/search"', home.data)
        self.assertNotIn(b'href="/shows/1"', home.data)
        self.assertIn(b'<span class="material-symbols-rounded">tv</span>', home.data)
        self.assertNotIn(b'<span class="material-symbols-rounded">explore</span>', home.data)
        self.assertIn(b'<span class="material-symbols-rounded">resume</span>', home.data)
        self.assertIn(b'<span class="material-symbols-rounded">event</span>', home.data)
        self.assertNotIn(b"Drama, Crime", home.data)
        self.assertNotIn(b"Drama, Fantasy", home.data)

        css = (Path(__file__).parents[1] / "static" / "app.css").read_text(
            encoding="utf-8"
        )
        self.assertIn("--compact-card-height: 152px", css)
        self.assertIn(".show-card {\n  position: relative;\n  width: 100%;\n  height: var(--compact-card-height);", css)
        self.assertIn(".popular-card {\n  position: relative;\n  height: var(--compact-card-height);", css)
        self.assertIn("grid-template-columns: 88px 1fr", css)
        self.assertIn('class="show-card-meta"', home.data.decode("utf-8"))
        self.assertIn('class="show-card-year">2008</span>', home.data.decode("utf-8"))
        self.assertIn("font-size: 1.16rem", css)
        self.assertIn("grid-template-columns: repeat(3, 1fr)", css)
        self.assertIn("grid-template-columns: 48px minmax(0, 1fr) 48px", css)
        self.assertIn("padding: max(12px, env(safe-area-inset-top)) 4px 12px", css)
        self.assertIn("text-align: center", css)
        self.assertIn(".app-bar-search:has(input:focus)", css)
        self.assertIn(".app-bar-search input.search-text-positioned:focus", css)
        self.assertNotIn(".app-bar-search:focus-within", css)
        self.assertIn("text-align: left", css)
        self.assertIn("transition: padding-left 180ms cubic-bezier(0.2, 0, 0, 1)", css)

        javascript = (Path(__file__).parents[1] / "static" / "app.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("function syncSearchChrome()", javascript)
        self.assertIn("searchMenuButton.hidden = hasText", javascript)
        self.assertIn("searchProfileButton.hidden = hasText", javascript)
        self.assertIn("searchClearButton.hidden = !hasText", javascript)
        self.assertIn("searchBackButton.hidden = !hasText", javascript)
        self.assertIn("globalSearchInput.focus()", javascript)
        self.assertIn("globalSearchInput.blur()", javascript)
        self.assertIn("function syncSearchTextPosition()", javascript)
        self.assertIn("searchTextMeasureContext.measureText(text).width", javascript)
        self.assertIn('style.setProperty("--search-text-centered-inset"', javascript)
        self.assertIn('classList.add("search-text-positioned")', javascript)

    def test_initial_library_order_matches_natural_default_sort(self):
        connection = sqlite3.connect(self.database)
        connection.executemany(
            """
            INSERT INTO shows (
                id, tmdb_id, name, first_air_date, genres,
                state, is_tracked, added_at, active_at
            ) VALUES (?, ?, ?, '2020-01-01', 'Drama', 'ACTIVE', 1, ?, ?)
            """,
            [
                (3, 900003, "Series 10", "2026-08-01", "2026-08-01"),
                (4, 900004, "Series 2", "2026-08-02", "2026-08-02"),
            ],
        )
        connection.commit()
        connection.close()

        home = self.client.get("/")
        self.assertLess(home.data.index(b"Series 2"), home.data.index(b"Series 10"))

        javascript = (Path(__file__).parents[1] / "static" / "app.js").read_text(
            encoding="utf-8"
        )
        css = (Path(__file__).parents[1] / "static" / "app.css").read_text(
            encoding="utf-8"
        )
        self.assertIn("async function revealAppWhenIconsAreReady()", javascript)
        self.assertIn('document.fonts.load(', javascript)
        self.assertIn('Material Symbols Rounded Filled', javascript)
        self.assertIn('classList.remove("app-booting")', javascript)
        self.assertIn("const hydratedLibraryViews = new Set();", javascript)
        self.assertIn("hydratedLibraryViews.add(view.dataset.view)", javascript)
        self.assertIn('window.history.replaceState({ trackApp: true, view: "backlog" }, "")', javascript)
        self.assertIn('window.addEventListener("popstate"', javascript)
        self.assertIn("window.history.back()", javascript)
        self.assertIn('detailType: "show"', javascript)
        self.assertIn('detailType: "episode"', javascript)
        self.assertIn('activeHistoryState.detailType === "show"', javascript)
        self.assertIn('previousWasShow,', javascript)
        self.assertIn("openSeasonIds,", javascript)
        self.assertIn("returnEpisodeId: String(episodeId)", javascript)
        self.assertIn("detailScrollY: window.scrollY", javascript)
        self.assertIn("function restoreShowDetailContext(showId, context)", javascript)
        self.assertIn('classList.add("is-returned-to")', javascript)
        self.assertIn("openShow(state.showId, detailParentView, true, null, state)", javascript)
        self.assertIn('episodeTemplate.content.querySelector("[data-episode-show-open]")?.remove()', javascript)
        self.assertIn('replaceChildren(episodeTemplate.content)', javascript)

        self.assertIn(".episode.is-returned-to", css)
        self.assertIn("@keyframes episode-return-highlight", css)

    def test_backlog_and_upcoming_are_independent_primary_views(self):
        connection = sqlite3.connect(self.database)
        connection.execute(
            """
            INSERT INTO episodes (
                id, season_id, tmdb_id, episode_number, name,
                air_date, runtime_minutes
            ) VALUES (100, 2, 99100, 7, 'Future Episode', '2099-01-02', 52)
            """
        )
        connection.commit()
        connection.close()

        home = self.client.get("/")
        self.assertIn(b'data-view="backlog"', home.data)
        self.assertIn(b'data-view="upcoming"', home.data)
        self.assertIn(
            b'class="nav-item active" type="button" data-nav-view="backlog"',
            home.data,
        )
        self.assertIn(b'data-nav-view="upcoming"', home.data)
        self.assertNotIn(b'data-schedule-tab', home.data)
        self.assertIn(b'placeholder="Search queue"', home.data)
        self.assertIn(b'data-schedule-search-text="active test show episode 6"', home.data)
        self.assertIn(b'data-schedule-content="backlog"', home.data)
        self.assertIn(b'data-schedule-content="upcoming"', home.data)
        self.assertEqual(home.data.count(b"data-schedule-panel"), 2)
        self.assertNotIn(b'data-schedule-now', home.data)
        self.assertIn(b'data-schedule-mode="catch-up"', home.data)
        self.assertIn(b'data-episode-id="6"', home.data)
        self.assertIn(b"Season 1 \xc2\xb7 Episode 6", home.data)
        self.assertIn(b"5/13", home.data)
        self.assertIn(b"38%", home.data)
        self.assertNotIn(b"more available", home.data)
        self.assertIn(b'data-schedule-mode="upcoming"', home.data)
        self.assertIn(b"Future Episode", home.data)
        self.assertIn(b'class="schedule-timeline"', home.data)
        self.assertIn(b"Season 2 \xc2\xb7 Episode 7", home.data)
        self.assertIn(b'class="schedule-timeline-episode-title">Future Episode</span>', home.data)
        self.assertRegex(
            home.data.decode("utf-8"),
            r'class="schedule-timeline-countdown">\s+\d+ days\s+</span>',
        )
        self.assertNotIn(b"days left", home.data)
        self.assertNotIn(b"48 min", home.data)
        self.assertNotIn(b'<h2 id="catch-up-title">', home.data)
        self.assertNotIn(b'<h2 id="upcoming-title">', home.data)
        self.assertNotIn(b'data-show-id="2" data-episode-id=', home.data)

        javascript = (Path(__file__).parents[1] / "static" / "app.js").read_text(
            encoding="utf-8"
        )
        self.assertIn('let currentView = "backlog"', javascript)
        self.assertNotIn("scheduleTab", javascript)
        self.assertNotIn("function setScheduleTab", javascript)
        self.assertIn("function filterSchedule(viewName = currentView)", javascript)
        self.assertIn("function syncGlobalSearch()", javascript)
        self.assertIn('tv: { placeholder: "Search TV"', javascript)
        self.assertIn('fetch(`/api/tv/search?q=${encodeURIComponent(query)}`', javascript)
        self.assertNotIn("centerScheduleOnNow", javascript)
        self.assertNotIn("preserveMarker", javascript)
        self.assertIn('data-schedule-action', javascript)
        self.assertIn('button.classList.add("catalog-action-secondary")', javascript)
        self.assertIn('if (!snackbar || !actionLabel || !onAction) return;', javascript)
        self.assertIn('function showCaughtUpScheduleState(card, data, action)', javascript)
        self.assertIn('function clearCaughtUpScheduleItems()', javascript)
        self.assertIn('function advanceScheduleCard(card, nextCard, {', javascript)
        self.assertIn('function showScheduleActionConfirmation(card)', javascript)
        self.assertIn('if (card.dataset.scheduleProcessing === "true") return;', javascript)
        self.assertNotIn("step_over", javascript)
        self.assertIn('function revealScheduleActions(card)', javascript)
        self.assertIn('playScheduleAdvanceTransition(card);', javascript)
        self.assertNotIn('card.classList.add("is-leaving")', javascript)
        self.assertIn('aria-label="Caught up">done_all', javascript)
        self.assertIn("function invalidateWatchCaches({", javascript)
        self.assertIn("invalidateWatchCaches({ showId, episodeId });", javascript)
        self.assertIn("invalidateWatchCaches({ showId, allEpisodes: true });", javascript)
        self.assertNotIn('Caught up with this show', javascript)

        css = (Path(__file__).parents[1] / "static" / "app.css").read_text(
            encoding="utf-8"
        )
        self.assertIn('.schedule-timeline-item {', css)
        self.assertIn('grid-template-columns: 48px 16px minmax(0, 1fr);', css)
        self.assertIn('.schedule-timeline-marker {', css)
        self.assertIn('justify-items: end;', css)
        self.assertIn('.schedule-timeline-poster {', css)
        self.assertIn('width: 72px;\n  height: 120px;', css)
        self.assertIn('.schedule-timeline-actions {\n  position: absolute;', css)
        self.assertIn('.schedule-timeline-item.is-advancing [data-schedule-advance-line]', css)
        self.assertIn('@keyframes schedule-advance-reveal', css)
        self.assertIn('@keyframes schedule-action-reveal', css)
        self.assertIn('@keyframes schedule-confirmation-out', css)
        self.assertIn('.schedule-action-slot .schedule-action-confirmation {', css)
        self.assertNotIn('@keyframes schedule-content-out', css)
        self.assertIn('.catalog-action.catalog-action-secondary {', css)
        self.assertIn('.schedule-skip-button {\n  width: 100%;\n  color: var(--primary);\n  background: transparent;', css)
        self.assertIn('.schedule-timeline-rail::before {', css)
        self.assertIn('.schedule-timeline-list>.schedule-timeline-item:first-child .schedule-timeline-rail::before {', css)
        self.assertIn('.schedule-timeline-list>.schedule-timeline-item:last-child .schedule-timeline-rail::before {', css)
        self.assertIn('.schedule-timeline-list>.schedule-timeline-item:only-child .schedule-timeline-rail::before {', css)
        self.assertIn('top: calc(50% - 4px);', css)
        self.assertIn('.schedule-timeline-content::after {', css)
        self.assertIn('background: linear-gradient(', css)
        self.assertIn('.schedule-timeline-item.is-caught-up {', css)
        self.assertIn('--progress-color: var(--progress-complete);', css)
        self.assertIn('.schedule-caught-up-icon {', css)
        self.assertIn('.schedule-timeline-item.is-caught-up .schedule-timeline-rail>span {', css)
        self.assertNotIn('.schedule-tabs-bar {', css)
        self.assertNotIn('.schedule-tab {', css)

        schedule_template = (Path(__file__).parents[1] / "templates" / "_schedule_content.html").read_text(
            encoding="utf-8"
        )
        self.assertIn('{% include "_backlog_content.html" %}', schedule_template)
        self.assertIn('{% include "_upcoming_content.html" %}', schedule_template)
        self.assertNotIn("_upcoming_timeline_item.html", schedule_template)

    def test_upcoming_groups_same_show_same_day_releases(self):
        connection = sqlite3.connect(self.database)
        connection.executemany(
            """
            INSERT INTO seasons (
                id, show_id, tmdb_id, season_number, name, air_date, episode_count
            ) VALUES (?, 1, ?, ?, ?, '2099-01-01', ?)
            """,
            [
                (20, 92020, 3, "Season 3", 3),
                (21, 92021, 4, "Season 4", 2),
                (22, 92022, 5, "Season 5", 1),
                (23, 92023, 6, "Season 6", 1),
            ],
        )
        connection.executemany(
            """
            INSERT INTO episodes (
                id, season_id, tmdb_id, episode_number, name, air_date
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (200, 20, 93200, 3, "Partial One", "2099-02-01"),
                (201, 20, 93201, 4, "Partial Two", "2099-02-01"),
                (202, 20, 93202, 5, "Later Episode", "2099-02-02"),
                (203, 21, 93203, 1, "Full One", "2099-03-01"),
                (204, 21, 93204, 2, "Full Two", "2099-03-01"),
                (205, 22, 93205, 6, "Season Five", "2099-04-01"),
                (206, 23, 93206, 6, "Season Six", "2099-04-01"),
            ],
        )
        connection.commit()
        connection.close()

        home = self.client.get("/")
        self.assertIn("Season 3 · Episodes 3–4".encode(), home.data)
        self.assertIn(b'>2 episodes</span>', home.data)
        self.assertIn("Season 4 · Episodes 1–2".encode(), home.data)
        self.assertIn(b'>Full season</span>', home.data)
        self.assertIn(b">S05E06-S06E06</span>", home.data)
        self.assertIn(b'data-season-ids="20"', home.data)
        self.assertIn(b'data-season-ids="22,23"', home.data)
        self.assertIn(b"data-schedule-show-open", home.data)

        javascript = (Path(__file__).parents[1] / "static" / "app.js").read_text(
            encoding="utf-8"
        )
        self.assertIn('event.target.closest("[data-schedule-show-open]")', javascript)
        self.assertIn("openSeasonIds,", javascript)

    def test_schedule_skip_advances_without_creating_watch_history(self):
        skipped = self.client.post("/api/episodes/6/skip")
        self.assertEqual(skipped.status_code, 200)

        connection = sqlite3.connect(self.database)
        skip_count = connection.execute(
            "SELECT COUNT(*) FROM episode_skips WHERE episode_id = 6"
        ).fetchone()[0]
        watch_count = connection.execute(
            "SELECT COUNT(*) FROM episode_watch_history WHERE episode_id = 6"
        ).fetchone()[0]
        connection.close()
        self.assertEqual(skip_count, 1)
        self.assertEqual(watch_count, 0)

        next_card = self.client.get("/api/schedule/shows/1/catch-up")
        self.assertIn(b'data-episode-id="7"', next_card.data)
        self.assertNotIn(b"Skipped", self.client.get("/api/episodes/6").data)

        undone = self.client.delete("/api/episodes/6/skip")
        self.assertEqual(undone.status_code, 200)
        restored_card = self.client.get("/api/schedule/shows/1/catch-up")
        self.assertIn(b'data-episode-id="6"', restored_card.data)

        self.client.post("/api/episodes/6/skip")
        watched = self.client.post(
            "/api/episodes/6/watch-count", json={"action": "increment"}
        )
        self.assertEqual(watched.status_code, 200)
        connection = sqlite3.connect(self.database)
        remaining_skip = connection.execute(
            "SELECT COUNT(*) FROM episode_skips WHERE episode_id = 6"
        ).fetchone()[0]
        connection.close()
        self.assertEqual(remaining_skip, 0)

    def test_schedule_cycles_skipped_episodes_and_only_finishes_when_fully_watched(self):
        for episode_id in range(6, 14):
            skipped = self.client.post(f"/api/episodes/{episode_id}/skip")
            self.assertEqual(skipped.status_code, 200)

        wrapped = self.client.get("/api/schedule/shows/1/catch-up")
        self.assertEqual(wrapped.status_code, 200)
        self.assertIn(b'data-episode-id="6"', wrapped.data)

        skipped_again = self.client.post("/api/episodes/6/skip")
        self.assertEqual(skipped_again.status_code, 200)
        rotated = self.client.get("/api/schedule/shows/1/catch-up")
        self.assertEqual(rotated.status_code, 200)
        self.assertIn(b'data-episode-id="7"', rotated.data)

        for episode_id in range(6, 14):
            watched = self.client.post(
                f"/api/episodes/{episode_id}/watch-count",
                json={"action": "increment"},
            )
            self.assertEqual(watched.status_code, 200)

        caught_up = self.client.get("/api/schedule/shows/1/catch-up")
        self.assertEqual(caught_up.status_code, 204)

    def test_upcoming_includes_archived_but_excludes_untracked_shows(self):
        connection = sqlite3.connect(self.database)
        connection.executemany(
            """
            INSERT INTO episodes (
                id, season_id, tmdb_id, episode_number, name,
                air_date, runtime_minutes
            ) VALUES (?, 4, ?, ?, ?, ?, 52)
            """,
            [
                (100, 99100, 7, "Archived Future Episode", "2099-01-02"),
                (101, 99101, 8, "Archived Backlog Candidate", "2020-01-02"),
            ],
        )
        connection.commit()
        connection.close()

        tracked_schedule = self.client.get("/api/schedule")
        self.assertIn(b"Archived Future Episode", tracked_schedule.data)
        self.assertNotIn(b"Archived Backlog Candidate", tracked_schedule.data)

        connection = sqlite3.connect(self.database)
        connection.execute("UPDATE shows SET is_tracked = 0 WHERE id = 2")
        connection.commit()
        connection.close()

        untracked_schedule = self.client.get("/api/schedule")
        self.assertNotIn(b"Archived Future Episode", untracked_schedule.data)

    def test_upcoming_includes_the_past_week_with_live_status(self):
        connection = sqlite3.connect(self.database)
        connection.execute(
            """
            INSERT INTO episodes (
                id, season_id, tmdb_id, episode_number, name,
                air_date, runtime_minutes
            ) VALUES (100, 2, 99100, 7, 'Recently Aired', date('now', '-3 days'), 52)
            """
        )
        connection.execute(
            """
            INSERT INTO episodes (
                id, season_id, tmdb_id, episode_number, name,
                air_date, runtime_minutes
            ) VALUES (101, 2, 99101, 8, 'Too Old for Upcoming', date('now', '-8 days'), 52)
            """
        )
        connection.execute(
            """
            INSERT INTO episodes (
                id, season_id, tmdb_id, episode_number, name,
                air_date, runtime_minutes
            ) VALUES (102, 2, 99102, 9, 'Airs Today', date('now'), 52)
            """
        )
        connection.execute(
            """
            INSERT INTO episodes (
                id, season_id, tmdb_id, episode_number, name,
                air_date, runtime_minutes
            ) VALUES (103, 2, 99103, 10, 'Airs Tomorrow', date('now', '+1 day'), 52)
            """
        )
        connection.commit()
        connection.close()

        schedule = self.client.get("/api/schedule")
        self.assertIn(b"Recently Aired", schedule.data)
        self.assertIn(b"Airs Today", schedule.data)
        self.assertIn(b"Airs Tomorrow", schedule.data)
        self.assertNotIn(b"Too Old for Upcoming", schedule.data)
        self.assertIn(b'class="schedule-timeline-countdown is-live">', schedule.data)
        self.assertRegex(
            schedule.data.decode("utf-8"),
            r'class="schedule-timeline-countdown is-live">\s+live\s+</span>',
        )
        self.assertRegex(
            schedule.data.decode("utf-8"),
            r'class="schedule-timeline-countdown">\s+today\s+</span>',
        )
        self.assertRegex(
            schedule.data.decode("utf-8"),
            r'class="schedule-timeline-countdown">\s+tomorrow\s+</span>',
        )

        css = (Path(__file__).parents[1] / "static" / "app.css").read_text(
            encoding="utf-8"
        )
        self.assertIn(".schedule-timeline-countdown.is-live", css)
        self.assertIn(".schedule-timeline-countdown.is-live::before", css)
        self.assertIn("color: var(--error)", css)
        self.assertIn("display: inline-flex", css)
        self.assertIn("align-items: center", css)
        self.assertIn("flex: 0 0 5px", css)

    def test_upcoming_uses_the_browser_local_calendar_date(self):
        connection = sqlite3.connect(self.database)
        connection.execute(
            """
            INSERT INTO episodes (
                id, season_id, tmdb_id, episode_number, name, air_date
            ) VALUES (104, 2, 99104, 11, 'Boundary Episode', '2099-06-15')
            """
        )
        connection.commit()
        connection.close()

        def boundary_card(local_date):
            response = self.client.get(
                "/api/schedule", headers={"X-Track-Local-Date": local_date}
            )
            html = response.data.decode("utf-8")
            match = re.search(
                r'<article[^>]*>.*?Boundary Episode.*?</article>', html, re.DOTALL
            )
            self.assertIsNotNone(match)
            return match.group(0)

        self.assertRegex(boundary_card("2099-06-14"), r">\s*tomorrow\s*</span>")
        self.assertRegex(boundary_card("2099-06-15"), r">\s*today\s*</span>")
        self.assertRegex(boundary_card("2099-06-16"), r">\s*live\s*</span>")

    def test_tv_controls_share_a_bottom_inline_bar(self):
        home = self.client.get("/")
        self.assertNotIn(b"data-open-library-filter", home.data)
        self.assertNotIn(b'data-library-filter-dialog', home.data)
        self.assertEqual(home.data.count(b"data-tv-control-bar"), 1)
        self.assertEqual(home.data.count(b'class="tv-inline-bar"'), 1)
        self.assertEqual(home.data.count(b'class="tv-library-button-group"'), 1)
        self.assertEqual(home.data.count(b"data-tv-dropdown-toggle="), 2)
        self.assertEqual(home.data.count(b"data-tv-progress-option="), 4)
        self.assertEqual(home.data.count(b"data-tv-sort-option="), 3)
        self.assertIn(b'data-tv-progress-option=""', home.data)
        self.assertIn(b'data-tv-sort-option="name"', home.data)
        self.assertIn(b'data-tv-sort-option="dateAdded"', home.data)
        self.assertIn(b'data-tv-sort-option="releaseDate"', home.data)
        self.assertIn(b">check_box</span>", home.data)
        self.assertIn(b">arrow_upward</span>", home.data)
        self.assertIn(b'data-date-added=', home.data)
        self.assertIn(b'data-release-date=', home.data)
        self.assertNotIn(b'class="tv-list-heading-toggle"', home.data)
        self.assertIn(b'data-tv-library-switcher', home.data)
        self.assertEqual(home.data.count(b"data-tv-library-state="), 2)
        self.assertIn(b"<span>New</span>", home.data)
        self.assertIn(b"<span>Started</span>", home.data)
        self.assertIn(b"<span>Caught-up</span>", home.data)

        javascript = (Path(__file__).parents[1] / "static" / "app.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("state: TRACKING_STATE.ACTIVE", javascript)
        self.assertIn('progress: ""', javascript)
        self.assertIn("globalSearchInput?.blur();", javascript)
        self.assertIn("function syncTvControlBar", javascript)
        self.assertIn("function toggleTvDropdown", javascript)
        self.assertIn("libraryViewPreferences.tv.progress = progressOption.dataset.tvProgressOption", javascript)
        self.assertIn('preferences.sortDirection === "asc" ? "desc" : "asc"', javascript)
        self.assertIn("preferences.state = nextState;", javascript)
        self.assertIn("librarySwitcher.hidden = searching;", javascript)
        self.assertIn('switcher?.classList.add("is-scroll-hidden")', javascript)
        self.assertIn('switcher?.classList.remove("is-scroll-hidden")', javascript)
        self.assertIn('controlBar?.classList.add("is-scroll-hidden")', javascript)
        self.assertIn('controlBar?.classList.remove("is-scroll-hidden")', javascript)
        self.assertNotIn(b">swap_vert</span>", home.data)
        self.assertIn('filterShowView(views.get("tv"))', javascript)
        self.assertNotIn("preferences.sortField !==", javascript)
        self.assertNotIn("preferences.sortDirection !==", javascript)
        self.assertIn("const showDetailCache = new Map();", javascript)
        self.assertIn("const showSeasonsCache = new Map();", javascript)
        self.assertIn("const seasonEpisodesCache = new Map();", javascript)
        self.assertIn("const revealKey = `tv:${state}`;", javascript)
        self.assertIn("revealedViewAnimations.has(revealKey)", javascript)
        self.assertIn("staggerTvFirstReveal(view)", javascript)
        self.assertIn("staggerTvSlices(cards)", javascript)
        self.assertIn('slice.classList.add("tv-slice-reveal")', javascript)
        self.assertIn("const tvSliceStaggerMs = 55;", javascript)
        self.assertIn('slice.classList.remove("tv-slice-reveal")', javascript)
        self.assertIn('clearTvFirstReveal(views.get("tv"))', javascript)
        self.assertIn("const scheduleItemStaggerMs = 65;", javascript)
        self.assertIn('item.classList.add("schedule-item-reveal")', javascript)
        self.assertIn('view.classList.add("schedule-rail-reveal")', javascript)
        self.assertIn("staggerScheduleFirstReveal(views.get(currentView));", javascript)
        self.assertIn('fetch("/api/tv"', javascript)
        self.assertIn("hydrateOtherPrimaryViews(view.dataset.view);", javascript)
        self.assertIn("Promise.allSettled(hydrationTasks);", javascript)
        self.assertIn("background && viewName === currentView", javascript)
        self.assertIn("const firstScheduleDataReady = firstScheduleReveal && scheduleViewsHydrated;", javascript)
        self.assertIn("if (firstScheduleDataReady) {\n      staggerScheduleFirstReveal", javascript)
        self.assertIn("const [overviewHtml, seasonsHtml] = await Promise.all", javascript)
        self.assertIn(
            "renderShowDetail(cachedOverview, cachedSeasons, false, returnContext)",
            javascript,
        )
        self.assertIn("fetchFragment(`/api/shows/${showId}/seasons`", javascript)
        self.assertIn("fetch(`/api/seasons/${cacheKey}/episodes`", javascript)
        self.assertIn("const seasonEpisodeHydrationTargets = new Map();", javascript)
        self.assertIn("activeSeasonEpisodePrefetches < 3", javascript)
        self.assertIn("window.requestIdleCallback(hydrateWhenIdle", javascript)
        self.assertIn("renderSeasonEpisodes(season, html, false);", javascript)
        self.assertIn("prefetchShowSeasonEpisodes(detailShow);", javascript)
        self.assertIn('document.addEventListener("toggle"', javascript)
        self.assertIn(
            "await Promise.all(seasonsToRestore.filter(Boolean).map(loadSeasonEpisodes))",
            javascript,
        )

        css = (Path(__file__).parents[1] / "static" / "app.css").read_text(
            encoding="utf-8"
        )
        self.assertIn(".tv-inline-bar {", css)
        self.assertIn("position: fixed;", css)
        self.assertIn("bottom: calc(72px + env(safe-area-inset-bottom));", css)
        self.assertIn("width: min(100%, 520px);", css)
        self.assertIn("background: var(--nav-surface);", css)
        self.assertIn(".tv-inline-bar.is-scroll-hidden {", css)
        self.assertIn("transform: translate(-50%, calc(100% + 16px));", css)
        self.assertIn(".tv-library-button-group {", css)
        self.assertIn('.tv-library-button-group button[aria-pressed="true"] {', css)
        self.assertIn("border-radius: 24px;", css)
        self.assertIn("bottom: calc(100% + 8px);", css)
        self.assertNotIn(".tv-control-bar {", css)
        self.assertIn(".tv-dropdown-menu {", css)
        self.assertIn(".tv-dropdown-selection {", css)
        self.assertIn("color: var(--progress-not-started);", css)
        self.assertNotIn(".library-filter-dialog", css)
        self.assertIn(".tv-slice-reveal {", css)
        self.assertIn("@keyframes schedule-rail-reveal", css)
        self.assertIn("@keyframes schedule-dot-reveal", css)
        self.assertIn("@keyframes media-image-reveal", css)
        self.assertIn(
            ".episode-watch-summary-wrap:has(.episode-detail-watch-menu:not([hidden]))",
            css,
        )
        self.assertIn('image.dataset.mediaImagePending = "";', javascript)
        self.assertIn('image.classList.add("media-image-reveal")', javascript)
        self.assertIn('const menuScrim = document.querySelector("[data-menu-scrim]")', javascript)
        self.assertIn("openMenu.parentElement.insertBefore(menuScrim, openMenu)", javascript)
        self.assertIn('event.target === imageViewerStage', javascript)
        self.assertIn('event.key === "Escape" && menuScrim', javascript)
        self.assertIn(".menu-scrim {", css)
        self.assertIn("backdrop-filter: blur(2px);", css)
        self.assertIn("grid-template-columns: 48px minmax(0, 1fr) 48px;", css)

    def test_tv_library_is_available_as_a_background_fragment(self):
        fragment = self.client.get("/api/tv")
        self.assertEqual(fragment.status_code, 200)
        self.assertIn(b'data-state-section="ACTIVE"', fragment.data)
        self.assertIn(b'data-state-section="ARCHIVED"', fragment.data)
        self.assertNotIn(b"<!doctype html>", fragment.data.lower())
        self.assertNotIn(b"bottom-nav", fragment.data)

    def test_show_details_are_a_fragment(self):
        detail = self.client.get("/api/shows/1")
        self.assertEqual(detail.status_code, 200)
        self.assertIn(b"arrow_back", detail.data)
        self.assertIn(b"data-season-list", detail.data)
        self.assertNotIn(b"data-season-loading", detail.data)
        self.assertIn(b'data-tmdb-refreshed-at=""', detail.data)
        self.assertIn(b'data-metadata-refresh-due="true"', detail.data)
        self.assertNotIn(b"Season 1", detail.data)
        self.assertNotIn(b"Season Two Premiere", detail.data)
        self.assertNotIn(b"data-season-watch", detail.data)
        self.assertNotIn(b"data-episode-watch", detail.data)
        self.assertIn(b'data-detail-title="Active Test Show"', detail.data)
        self.assertIn(b'class="detail-app-bar-title">Show details</span>', detail.data)
        self.assertIn(b'data-activity-log', detail.data)
        self.assertIn(b"Added to My Shows", detail.data)
        self.assertIn(b'<span class="state-label progress-tag" data-progress-tag>Watching</span>', detail.data)
        self.assertIn(b'<span data-progress-copy>5/13</span>', detail.data)
        self.assertIn(b'<strong data-progress-percent>38%</strong>', detail.data)
        self.assertNotIn(b"Your progress", detail.data)
        self.assertNotIn(b"data-show-state-label", detail.data)
        self.assertNotIn(b'<details class="activity-log" open', detail.data)
        self.assertNotIn(b"<!doctype html>", detail.data.lower())
        self.assertNotIn(b"bottom-nav", detail.data)
        self.assertLess(len(detail.data), 50_000)

        seasons = self.client.get("/api/shows/1/seasons")
        self.assertEqual(seasons.status_code, 200)
        self.assertIn(b"Season 1", seasons.data)
        self.assertNotIn(b"Season Two Premiere", seasons.data)
        self.assertIn(b"data-season-watch", seasons.data)
        self.assertNotIn(b"data-episode-watch", seasons.data)
        self.assertIn(b'data-episodes-loaded="false"', seasons.data)
        self.assertIn(b"data-season-episodes", seasons.data)
        self.assertIn(b"rewatch", seasons.data)
        self.assertIn(b"unwatch", seasons.data)
        self.assertIn(b'aria-checked="mixed"', seasons.data)
        self.assertIn(b'aria-checked="false"', seasons.data)
        self.assertNotIn(b'<details class="season" open', seasons.data)
        self.assertNotIn(b"<!doctype html>", seasons.data.lower())
        self.assertNotIn(b"bottom-nav", seasons.data)

        episodes = self.client.get("/api/seasons/2/episodes")
        self.assertEqual(episodes.status_code, 200)
        self.assertIn(b"Season Two Premiere", episodes.data)
        self.assertIn(b"data-episode-watch", episodes.data)
        self.assertNotIn(b"data-season-watch", episodes.data)
        self.assertEqual(self.client.get("/api/seasons/999/episodes").status_code, 404)

        archived_detail = self.client.get("/api/shows/2")
        self.assertEqual(archived_detail.status_code, 200)
        self.assertIn(b"Archived Test Show", archived_detail.data)
        self.assertIn(b'<span class="state-label progress-tag" data-progress-tag>Finished</span>', archived_detail.data)
        self.assertIn(b"Resume", archived_detail.data)
        self.assertIn(b"more_vert", archived_detail.data)
        move_position = archived_detail.data.index(b'data-show-action="move"')
        refresh_position = archived_detail.data.index(b'data-show-action="refresh"')
        remove_position = archived_detail.data.index(b'data-show-action="remove"')
        self.assertLess(move_position, refresh_position)
        self.assertLess(refresh_position, remove_position)
        self.assertIn(b">Refresh</span>", archived_detail.data)

        missing = self.client.get("/api/shows/999")
        self.assertEqual(missing.status_code, 404)
        missing_seasons = self.client.get("/api/shows/999/seasons")
        self.assertEqual(missing_seasons.status_code, 404)

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

    def test_tmdb_images_are_cached_on_disk_and_recorded_in_sqlite(self):
        class ImageResponse(BytesIO):
            def __init__(self, body):
                super().__init__(body)
                self.headers = Message()
                self.headers["Content-Type"] = "image/jpeg"

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.close()

        calls = []

        def transport(request, timeout):
            calls.append((request.full_url, timeout))
            return ImageResponse(b"test-image-bytes")

        cache_directory = Path(self.temp_dir.name) / "images"
        self.app.config.update(
            IMAGE_CACHE_DIR=str(cache_directory),
            IMAGE_TRANSPORT=transport,
        )

        first = self.client.get("/media/poster/w185/example.jpg")
        second = self.client.get("/media/poster/w185/example.jpg")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data, b"test-image-bytes")
        self.assertEqual(first.mimetype, "image/jpeg")
        self.assertIn("max-age=31536000", first.headers["Cache-Control"])
        self.assertEqual(second.data, b"test-image-bytes")
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            calls[0][0], "https://image.tmdb.org/t/p/w185/example.jpg"
        )

        connection = sqlite3.connect(self.database)
        cached = connection.execute(
            """
            SELECT tmdb_path, image_type, size, content_type, local_filename
            FROM image_cache
            """
        ).fetchone()
        connection.close()
        self.assertEqual(cached[:4], ("/example.jpg", "poster", "w185", "image/jpeg"))
        self.assertTrue((cache_directory / cached[4]).is_file())

        unsupported = self.client.get("/media/poster/original/example.jpg")
        self.assertEqual(unsupported.status_code, 404)
        first.close()
        second.close()
        unsupported.close()

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
        self.assertEqual(first_data["season_min_watch_count"], 1)
        self.assertEqual(first_data["watched_count"], 11)
        self.assertTrue(all(item["watch_count"] == 1 for item in first_data["episodes"]))

        rewatch = self.client.post(
            "/api/seasons/2/watch-count", json={"action": "increment"}
        )
        rewatch_data = rewatch.get_json()
        self.assertEqual(rewatch_data["watched_count"], 11)
        self.assertEqual(rewatch_data["season_min_watch_count"], 2)
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
        self.assertEqual(fully_unwatched_data["season_min_watch_count"], 0)
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

    def test_episode_detail_is_a_fragment_with_current_watch_log(self):
        detail = self.client.get("/api/episodes/1")
        self.assertEqual(detail.status_code, 200)
        self.assertIn(b'data-detail-episode', detail.data)
        self.assertIn(b'data-detail-title="Opening Episode"', detail.data)
        self.assertIn(b'class="detail-app-bar-title">Episode details</span>', detail.data)
        self.assertIn(b'data-back-show-id="1"', detail.data)
        self.assertIn(b'data-episode-show-open data-show-id="1"', detail.data)
        self.assertIn(b">Active Test Show</span>", detail.data)
        self.assertIn(b"Watch log", detail.data)
        self.assertIn(b'data-activity-type="watched"', detail.data)
        self.assertIn(b'class="activity-log watch-log"', detail.data)
        self.assertNotIn(b'<details class="activity-log watch-log"', detail.data)
        self.assertIn(b'data-watch-log-entry', detail.data)
        self.assertIn(b'data-episode-detail-watch', detail.data)
        self.assertIn(b'data-episode-navigation', detail.data)
        self.assertIn(b'data-adjacent-episode="previous"', detail.data)
        self.assertIn(b'data-adjacent-episode="next"', detail.data)
        self.assertIn(b'data-episode-id="2"', detail.data)
        self.assertIn(b'data-watch-action="increment"', detail.data)
        self.assertIn(b'data-watch-action="decrement"', detail.data)
        self.assertNotIn(b"season-list", detail.data)
        self.assertNotIn(b"<!doctype html>", detail.data.lower())

        season_boundary = self.client.get("/api/episodes/6")
        self.assertIn(b'data-adjacent-episode="previous"', season_boundary.data)
        self.assertIn(b'data-episode-id="5"', season_boundary.data)
        self.assertIn(b'data-episode-id="7"', season_boundary.data)

        javascript = (Path(__file__).parents[1] / "static" / "app.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("const episodeDetailRequests = new Map();", javascript)
        self.assertIn("const mediaImagePreloads = new Map();", javascript)
        self.assertIn("function preloadAdjacentEpisodeDetails", javascript)
        self.assertIn("function preloadEpisodeDetailImages", javascript)
        self.assertIn(".then(preloadEpisodeDetailImages)", javascript)
        self.assertIn("function navigateAdjacentEpisode", javascript)
        self.assertIn('direction === "next" ? "-18%" : "18%"', javascript)
        self.assertIn('}, "replace");', javascript)

        stylesheet = (Path(__file__).parents[1] / "static" / "app.css").read_text(
            encoding="utf-8"
        )
        self.assertIn("overflow-x: clip;", stylesheet)
        self.assertIn(".episode-navigation-switcher button:first-child", stylesheet)
        self.assertIn("border-start-start-radius: 22px", stylesheet)
        self.assertIn(".episode-navigation-switcher button:last-child", stylesheet)
        self.assertIn("border-start-end-radius: 22px", stylesheet)

        connection = sqlite3.connect(self.database)
        connection.execute(
            "UPDATE episodes SET air_date = NULL, runtime_minutes = NULL WHERE id = 2"
        )
        connection.commit()
        connection.close()
        no_duration = self.client.get("/api/episodes/2")
        self.assertNotIn(b"None min", no_duration.data)
        self.assertNotIn(b'datetime="None"', no_duration.data)
        episode_list = self.client.get("/api/seasons/1/episodes")
        self.assertNotIn(b"None min", episode_list.data)
        self.assertNotIn(b'datetime="None"', episode_list.data)

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

        detail = self.client.get("/api/seasons/1/episodes")

        self.assertEqual(detail.status_code, 200)
        self.assertIn(b'data-watch-count="2"', detail.data)
        self.assertIn(b'data-watch-counter', detail.data)
        self.assertIn(b'>2</span>', detail.data)

    def test_watch_controls_are_never_disabled_or_cached_as_disabled(self):
        javascript = (Path(__file__).parents[1] / "static" / "app.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("const episodeDetailCache = new Map();", javascript)
        self.assertIn("if (cachedEpisode)", javascript)
        self.assertIn(
            "renderEpisodeDetail(cachedEpisode, previousWasShow, false)", javascript
        )
        self.assertIn(
            "renderEpisodeDetail(episodeHtml, previousWasShow, true)", javascript
        )
        episode_change = javascript[
            javascript.index("async function changeEpisodeWatchCount"):
            javascript.index("async function changeSeasonWatchCount")
        ]
        season_change = javascript[
            javascript.index("async function changeSeasonWatchCount"):
            javascript.index('document.addEventListener("click"')
        ]
        self.assertNotIn(".disabled", episode_change)
        self.assertNotIn(".disabled", season_change)
        self.assertIn("const pendingWatchChanges = new WeakSet();", javascript)
        self.assertIn("enableWatchControls(cachedList)", javascript)
        self.assertIn('enableWatchControls(views.get("detail"))', javascript)

        seasons = self.client.get("/api/seasons/1/episodes")
        self.assertNotIn(b" disabled", seasons.data)

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
        self.assertIn(b'data-progress-state="started"', home.data)

    def test_fully_watched_ongoing_show_is_caught_up(self):
        db = sqlite3.connect(self.database)
        db.execute("UPDATE shows SET status = 'Returning Series' WHERE id = 1")
        db.executemany(
            "INSERT INTO episode_watch_history (episode_id, added_at) VALUES (?, ?)",
            [(episode_id, "2026-08-24T12:00:00+00:00") for episode_id in range(6, 14)],
        )
        db.commit()
        db.close()

        home = self.client.get("/")
        match = re.search(
            rb'<article class="show-card" data-show-id="1".*?</article>',
            home.data,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        self.assertIn(b'data-progress-state="caught-up"', match.group(0))
        self.assertIn(b">Caught up</span>", match.group(0))

    def test_progress_colors_share_status_variables(self):
        css = (Path(__file__).parents[1] / "static" / "app.css").read_text(
            encoding="utf-8"
        )
        self.assertIn("--progress-complete: var(--accent)", css)
        self.assertIn("--progress-not-started:", css)
        self.assertIn("--progress-started: var(--primary)", css)
        self.assertIn("--progress-stopped: var(--error)", css)
        self.assertIn('[data-progress-state="caught-up"],', css)
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

    def test_show_can_be_archived_and_made_active_with_history(self):
        archive = self.client.post(
            "/api/shows/1/state", json={"state": "ARCHIVED"}
        )
        self.assertEqual(archive.status_code, 200)
        self.assertEqual(archive.get_json()["move_label"], "Resume")

        make_active = self.client.post(
            "/api/shows/1/state", json={"state": "ACTIVE"}
        )
        self.assertEqual(make_active.status_code, 200)
        self.assertEqual(make_active.get_json()["move_label"], "Archive")

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
        self.assertIn(b">Made active</strong>", detail.data)

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
        self.assertNotIn(b"Archived Test Show", self.client.get("/").data)
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

    def test_fresh_database_has_no_shows_or_watchlist_state(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "empty.db"
            empty_app = create_app({"TESTING": True, "DATABASE": str(database)})
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
            self.assertNotIn("WATCHING", show_sql)
            self.assertIn("ACTIVE", show_sql)
            self.assertNotIn("watchlist_at", columns)
            self.assertIn("active_at", columns)
            self.assertNotIn("watching_at", columns)
            self.assertIn("tmdb_refreshed_at", columns)

    def test_watching_state_database_migrates_to_active_without_losing_history(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "legacy.db"
            connection = sqlite3.connect(database)
            connection.executescript(
                """
                CREATE TABLE shows (
                    id INTEGER PRIMARY KEY,
                    tmdb_id INTEGER UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    original_name TEXT,
                    overview TEXT,
                    tagline TEXT,
                    poster_path TEXT,
                    backdrop_path TEXT,
                    first_air_date TEXT,
                    status TEXT,
                    genres TEXT,
                    original_language TEXT,
                    state TEXT NOT NULL CHECK (state IN ('WATCHING', 'ARCHIVED')),
                    is_tracked INTEGER NOT NULL DEFAULT 1 CHECK (is_tracked IN (0, 1)),
                    added_at TEXT NOT NULL,
                    watching_at TEXT,
                    archived_at TEXT,
                    updated_at TEXT,
                    tmdb_refreshed_at TEXT,
                    tmdb_payload TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE show_state_history (
                    id INTEGER PRIMARY KEY,
                    show_id INTEGER NOT NULL REFERENCES shows(id) ON DELETE CASCADE,
                    state TEXT NOT NULL CHECK (state IN ('WATCHING', 'ARCHIVED')),
                    entered_at TEXT NOT NULL
                );
                CREATE TABLE schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );
                INSERT INTO schema_migrations (version, applied_at)
                VALUES (1, '2026-01-01'), (2, '2026-01-01'), (3, '2026-01-01'),
                       (4, '2026-01-01'), (5, '2026-01-01');
                INSERT INTO shows (
                    id, tmdb_id, name, state, added_at, watching_at, tmdb_payload
                ) VALUES (
                    1, 1234, 'Legacy Show', 'WATCHING', '2026-01-01',
                    '2026-01-02', '{"id": 1234}'
                );
                INSERT INTO show_state_history (show_id, state, entered_at)
                VALUES (1, 'WATCHING', '2026-01-02');
                """
            )
            connection.commit()
            connection.close()

            create_app({"TESTING": True, "DATABASE": str(database)})

            connection = sqlite3.connect(database)
            connection.row_factory = sqlite3.Row
            show = connection.execute("SELECT * FROM shows WHERE id = 1").fetchone()
            history = connection.execute(
                "SELECT state, entered_at FROM show_state_history WHERE show_id = 1"
            ).fetchone()
            versions = connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(shows)")
            }
            connection.close()

            self.assertEqual(show["state"], "ACTIVE")
            self.assertEqual(show["active_at"], "2026-01-02")
            self.assertEqual(json.loads(show["tmdb_payload"]), {"id": 1234})
            self.assertEqual(tuple(history), ("ACTIVE", "2026-01-02"))
            self.assertEqual([row[0] for row in versions], [1, 2, 3, 4, 5, 6, 7])
            self.assertIn("active_at", columns)
            self.assertNotIn("watching_at", columns)

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
                    }
                )
                self.assertEqual(
                    environment_app.config["TMDB_READ_ACCESS_TOKEN"],
                    "token-from-environment",
                )

    def test_tv_search_is_remote_and_only_returns_addable_shows(self):
        class FakeClient:
            def __init__(self):
                self.search_calls = []

            def search_tv(self, query):
                self.search_calls.append(query)
                return {
                    "results": [
                        {"id": 900001, "name": "Already Watching"},
                        {"id": 22, "name": "Previously Removed"},
                        {"id": 21, "name": f"Result {query}"},
                    ]
                }

        connection = sqlite3.connect(self.database)
        connection.execute(
            """
            INSERT INTO shows (
                id, tmdb_id, name, state, is_tracked, added_at
            ) VALUES (3, 22, 'Previously Removed', 'ACTIVE', 0, '2026-01-01')
            """
        )
        connection.commit()
        connection.close()

        fake = FakeClient()
        self.app.config.update(
            TMDB_READ_ACCESS_TOKEN="test-token",
            TMDB_CLIENT_FACTORY=lambda _token: fake,
        )
        search = self.client.get("/api/tv/search?q=Severance")

        self.assertEqual(search.status_code, 200)
        self.assertEqual(fake.search_calls, ["Severance"])
        results = search.get_json()["results"]
        self.assertEqual([result["tmdb_id"] for result in results], [22, 21])
        self.assertEqual(results[0]["show_id"], 3)
        self.assertFalse(results[0]["is_tracked"])
        self.assertIsNone(results[1]["show_id"])
        self.assertEqual(self.client.get("/api/discover/popular").status_code, 404)
        self.assertEqual(self.client.get("/api/discover/search?q=Severance").status_code, 404)

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
            "/api/tv/shows/900/import", json={"state": "ACTIVE"}
        )
        duplicate = self.client.post(
            "/api/tv/shows/900/import", json={"state": "ARCHIVED"}
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
        season_list = self.client.get(
            f"/api/shows/{imported_show['id']}/seasons"
        ).data
        self.assertLess(season_list.find(b">Season 1</strong>"), season_list.find(b">Specials</strong>"))
        special_detail = self.client.get(f"/api/episodes/{special_episode_id}")
        self.assertNotIn(
            f'data-episode-id="{regular_episode_id}"'.encode(), special_detail.data
        )
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

    def test_show_metadata_refresh_respects_the_daily_ttl_and_manual_force(self):
        class FakeClient:
            def __init__(self):
                self.calls = 0

            def show_bundle(self, tmdb_id):
                self.calls += 1
                return (
                    {
                        "id": tmdb_id,
                        "name": "Active Test Show",
                        "first_air_date": "2008-01-20",
                        "genres": [{"id": 18, "name": "Drama"}],
                    },
                    [],
                )

        fake = FakeClient()
        self.app.config.update(
            TMDB_READ_ACCESS_TOKEN="test-token",
            TMDB_CLIENT_FACTORY=lambda _token: fake,
        )

        stale_refresh = self.client.post(
            "/api/shows/1/refresh", json={"force": False}
        )
        fresh_skip = self.client.post(
            "/api/shows/1/refresh", json={"force": False}
        )
        manual_refresh = self.client.post(
            "/api/shows/1/refresh", json={"force": True}
        )

        self.assertTrue(stale_refresh.get_json()["refreshed"])
        self.assertFalse(fresh_skip.get_json()["refreshed"])
        self.assertTrue(manual_refresh.get_json()["refreshed"])
        self.assertEqual(fake.calls, 2)
        self.assertIsNotNone(stale_refresh.get_json()["refreshed_at"])
        self.assertIn("show-card", manual_refresh.get_json()["card_html"])

        detail = self.client.get("/api/shows/1")
        self.assertIn(b'data-metadata-refresh-due="false"', detail.data)

        invalid = self.client.post(
            "/api/shows/1/refresh", json={"force": "yes"}
        )
        self.assertEqual(invalid.status_code, 400)

    def test_stale_tracked_shows_refresh_as_an_independent_batch(self):
        class FakeClient:
            def __init__(self):
                self.calls = []

            def show_bundle(self, tmdb_id):
                self.calls.append(tmdb_id)
                return (
                    {
                        "id": tmdb_id,
                        "name": f"Refreshed {tmdb_id}",
                        "first_air_date": "2020-01-01",
                        "genres": [{"id": 18, "name": "Drama"}],
                    },
                    [],
                )

        fake = FakeClient()
        self.app.config.update(
            TMDB_READ_ACCESS_TOKEN="test-token",
            TMDB_CLIENT_FACTORY=lambda _token: fake,
        )

        first = self.client.post("/api/shows/refresh-stale")
        second = self.client.post("/api/shows/refresh-stale")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(
            [item["show_id"] for item in first.get_json()["refreshed"]],
            [1, 2],
        )
        self.assertTrue(
            all("show-card" in item["card_html"] for item in first.get_json()["refreshed"])
        )
        self.assertEqual(first.get_json()["failures"], [])
        self.assertEqual(second.get_json()["refreshed"], [])
        self.assertEqual(second.get_json()["skipped"], 2)
        self.assertEqual(fake.calls, [900001, 900002])

        connection = sqlite3.connect(self.database)
        connection.execute("UPDATE shows SET tmdb_refreshed_at = NULL")
        connection.commit()
        connection.close()
        with self.app.app_context():
            background_result = self.app.extensions["refresh_stale_tracked_shows"]()
        self.assertEqual(
            [item["show_id"] for item in background_result["refreshed"]],
            [1, 2],
        )
        self.assertTrue(
            all("card_html" not in item for item in background_result["refreshed"])
        )

    def test_background_refresh_worker_runs_without_a_browser(self):
        completed = threading.Event()
        calls = []

        def refresh_once():
            calls.append(True)
            completed.set()
            return {"refreshed": [], "failures": [], "skipped": 0}

        self.app.extensions["refresh_stale_tracked_shows"] = refresh_once
        self.app.config["BACKGROUND_REFRESH_INTERVAL_SECONDS"] = 60
        thread, stop_event = start_background_refresh(self.app)
        try:
            self.assertTrue(completed.wait(1))
            self.assertEqual(calls, [True])
        finally:
            stop_event.set()
            thread.join(timeout=1)
        self.assertFalse(thread.is_alive())

    def test_tv_search_preview_stays_untracked_until_added(self):
        show_payload = {
            "id": 920,
            "name": "Preview Show",
            "overview": "A show opened from TV search.",
            "poster_path": "/preview.jpg",
            "first_air_date": "2022-04-10",
            "genres": [{"id": 18, "name": "Drama"}],
        }
        seasons = [
            {
                "id": 921,
                "season_number": 1,
                "name": "Season 1",
                "poster_path": "/preview-season.jpg",
                "episodes": [
                    {
                        "id": 922,
                        "episode_number": 1,
                        "name": "First Look",
                        "still_path": "/preview-still.jpg",
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
            "/api/tv/shows/920/import", json={"state": None}
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
        self.assertIn(b'data-show-tracked="false"', detail.data)
        self.assertNotIn(b"data-progress-summary", detail.data)
        self.assertNotIn(b"data-show-menu-button", detail.data)
        self.assertIn(b"/media/poster/w342/preview.jpg", detail.data)
        self.assertIn(
            b'data-full-image-src="https://image.tmdb.org/t/p/w780/preview.jpg"',
            detail.data,
        )

        seasons_detail = self.client.get(
            f"/api/shows/{preview_data['show_id']}/seasons"
        )
        self.assertIn(b"/media/season/w185/preview-season.jpg", seasons_detail.data)
        self.assertIn(
            b'data-full-image-src="https://image.tmdb.org/t/p/w780/preview-season.jpg"',
            seasons_detail.data,
        )

        connection = sqlite3.connect(self.database)
        preview_episode_id = connection.execute(
            "SELECT id FROM episodes WHERE tmdb_id = 922"
        ).fetchone()[0]
        connection.close()
        episode_detail = self.client.get(f"/api/episodes/{preview_episode_id}")
        self.assertIn(b"/media/still/w300/preview-still.jpg", episode_detail.data)
        self.assertIn(
            b'data-full-image-src="https://image.tmdb.org/t/p/w780/preview-still.jpg"',
            episode_detail.data,
        )

        javascript = (Path(__file__).parents[1] / "static" / "app.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("function openImageViewer(trigger)", javascript)
        self.assertIn("imageViewer.showModal()", javascript)
        self.assertIn('imageViewerImage?.removeAttribute("src")', javascript)

        css = (Path(__file__).parents[1] / "static" / "app.css").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            '[data-detail-show][data-show-tracked="false"] .season-list .watch-control-wrap',
            css,
        )
        self.assertIn(
            '[data-detail-show][data-show-tracked="false"] .episode', css
        )

        tracked = self.client.post(
            f"/api/shows/{preview_data['show_id']}/state",
            json={"state": "ARCHIVED"},
        )
        tracked_data = tracked.get_json()
        self.assertEqual(tracked.status_code, 200)
        self.assertTrue(tracked_data["newly_tracked"])
        self.assertIn("show-card", tracked_data["card_html"])
        self.assertIn("/media/poster/w342/preview.jpg", tracked_data["card_html"])
        self.assertIn("data-media-fallback-template", tracked_data["card_html"])
        self.assertNotIn("hidden data-media-fallback", tracked_data["card_html"])

        tracked_detail = self.client.get(f"/api/shows/{preview_data['show_id']}")
        self.assertIn(b"data-progress-summary", tracked_detail.data)
        self.assertNotIn(b"data-track-show-state", tracked_detail.data)
        archived_home = self.client.get("/")
        self.assertIn(b"Preview Show", archived_home.data)

    def test_tv_add_cards_keep_new_and_previously_removed_styles(self):
        css = (Path(__file__).parents[1] / "static" / "app.css").read_text(
            encoding="utf-8"
        )
        javascript = (Path(__file__).parents[1] / "static" / "app.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("grid-template-columns: 88px 1fr", css)
        self.assertIn("overflow: hidden", css)
        self.assertNotIn(".popular-card.is-added", css)
        self.assertIn(".popular-card.is-cached::after", css)
        self.assertIn("background: var(--outline);", css)
        self.assertIn(".has-media-image:not(.is-image-loaded)", css)
        self.assertIn("animation: skeleton-pulse 1.2s", css)
        self.assertIn(
            "background: color-mix(in srgb, var(--primary-light) 16%, var(--surface-card))",
            css,
        )
        self.assertIn(".mini-poster {\n  position: relative;", css)
        self.assertIn(".mini-poster img {\n  position: absolute;", css)
        self.assertIn("inset: 0 0 0 auto", css)
        self.assertNotIn("box-shadow: inset 0 0 0 2px var(--accent)", css)
        self.assertIn('if (show.show_id) article.classList.add("is-cached")', javascript)
        self.assertNotIn("function markCatalogTracked", javascript)
        self.assertIn('openShow(data.show_id, "tv", false, "replace")', javascript)
        self.assertIn("const cachedShowId = card.dataset.showId", javascript)
        self.assertIn(
            'await openShow(cachedShowId, "tv", true, historyMode)',
            javascript,
        )
        self.assertIn("if (hasCachedDetails) {", javascript)
        self.assertIn("refreshShowMetadata(showId);", javascript)
        seasons_ready = javascript.index("nextSeasonList.innerHTML = seasonsHtml")
        detail_swap = javascript.index('views.get("detail").replaceChildren(template.content)')
        self.assertLess(seasons_ready, detail_swap)
        self.assertIn('const searching = view.dataset.view === "tv" && Boolean(query)', javascript)
        self.assertIn("const matchesProgress = searching || !preferences.progress", javascript)
        self.assertIn("section.hidden = searching ? visibleCount === 0 : !stateSelected", javascript)
        self.assertIn("localCount + addCount > 0", javascript)
        self.assertIn("const available = results.filter((show) => !show.is_tracked)", javascript)
        self.assertIn("fallback.hidden = false", javascript)
        self.assertIn('document.createElement("template")', javascript)
        self.assertIn('template[data-media-fallback-template]', javascript)

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
            "/api/tv/shows/910/import", json={"state": "ACTIVE"}
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
