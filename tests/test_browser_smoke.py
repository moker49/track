import tempfile
import threading
import unittest
from pathlib import Path

from app import create_app
from tests.test_app import seed_test_library

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # Optional local browser dependency.
    sync_playwright = None


@unittest.skipUnless(sync_playwright, "install requirements-dev.txt for browser smoke tests")
class PersistentShellBrowserSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from werkzeug.serving import make_server

        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.database = Path(cls.temp_dir.name) / "browser.db"
        cls.app = create_app(
            {
                "TESTING": True,
                "DATABASE": str(cls.database),
                "TMDB_READ_ACCESS_TOKEN": "",
            }
        )
        seed_test_library(cls.database)
        cls.server = make_server("127.0.0.1", 0, cls.app, threaded=True)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(timeout=5)
        cls.temp_dir.cleanup()

    def test_primary_navigation_detail_mutation_history_and_filter_flow(self):
        page = self.browser.new_page(viewport={"width": 390, "height": 844})
        try:
            page.goto(self.base_url, wait_until="domcontentloaded")
            page.wait_for_function("!document.documentElement.classList.contains('app-booting')")
            self.assertTrue(page.locator('[data-view="backlog"]').is_visible())
            self.assertTrue(page.locator('[data-nav-view="backlog"]').get_attribute("aria-current"))

            page.locator('[data-nav-view="upcoming"]').click()
            self.assertTrue(page.locator('[data-view="upcoming"]').is_visible())
            page.locator('[data-nav-view="tv"]').click()
            self.assertTrue(page.locator('[data-view="tv"]').is_visible())

            page.locator('[data-search-profile]').click()
            page.locator('[data-view="profile"]').wait_for(state="visible")
            self.assertTrue(page.locator('[data-view="profile"]').is_visible())
            self.assertFalse(page.locator('.bottom-chrome').is_visible())
            self.assertTrue(page.locator('[data-profile-panel="diary"]').is_visible())
            self.assertFalse(page.locator('[data-profile-panel="statistics"]').is_visible())
            page.locator('[data-profile-tab="statistics"]').click()
            self.assertEqual(
                page.locator('[data-profile-tab="statistics"]').get_attribute("aria-selected"),
                "true",
            )
            self.assertTrue(page.locator('[data-profile-panel="statistics"]').is_visible())
            page.locator('[data-profile-back]').click()
            page.locator('[data-view="tv"]').wait_for(state="visible")
            self.assertTrue(page.locator('.bottom-chrome').is_visible())

            page.locator('[data-search-profile]').click()
            page.locator('[data-view="profile"]').wait_for(state="visible")
            page.go_back()
            page.locator('[data-view="tv"]').wait_for(state="visible")

            page.locator('.show-card[data-show-id="1"] [data-show-open]').click()
            page.locator('[data-detail-show][data-show-id="1"]').wait_for()
            first_season = page.locator('details.season[data-season-id="1"]')
            first_season.wait_for()
            self.assertFalse(first_season.get_attribute("open"))
            first_season.locator("summary").click()
            page.locator('[data-episode-id="1"] [data-open-episode]').wait_for()
            page.locator('[data-episode-id="1"] [data-open-episode]').click()
            episode = page.locator('[data-detail-episode][data-episode-id="1"]')
            episode.wait_for()
            count_before = int(episode.get_attribute("data-watch-count"))
            episode.locator('[data-episode-detail-watch]').click()
            if count_before:
                page.locator('[data-watch-action="increment"]:visible').click()
            page.wait_for_function(
                "expected => Number(document.querySelector('[data-detail-episode]').dataset.watchCount) === expected",
                count_before + 1,
            )

            page.locator('[data-detail-back]').click()
            page.locator('[data-detail-show][data-show-id="1"]').wait_for()
            self.assertIsNotNone(first_season.get_attribute("open"))
            page.locator('[data-detail-back]').click()
            page.locator('[data-view="tv"]').wait_for(state="visible")

            search = page.locator('[data-global-search]')
            search.fill("Active")
            self.assertTrue(page.locator('[data-search-back]').is_visible())
            self.assertTrue(page.locator('[data-clear-search]').is_visible())
            self.assertFalse(page.locator('[data-tv-control-bar]').is_visible())
            page.locator('[data-search-back]').click()
            self.assertEqual(search.input_value(), "")
            self.assertFalse(search.evaluate("element => element === document.activeElement"))

            combined_toggle = page.locator('[data-tv-dropdown-toggle="combined"]')
            combined_toggle.click()
            combined_menu = page.locator('[data-tv-dropdown-menu="combined"]')
            self.assertTrue(combined_menu.is_visible())
            page.locator('[data-tv-progress-option="started"]').click()
            combined_menu.wait_for(state="hidden")
            self.assertFalse(combined_menu.is_visible())
            self.assertIn("Started", combined_toggle.inner_text())

            combined_toggle.click()
            page.locator('[data-tv-sort-option="name"]').click()
            self.assertEqual(
                combined_toggle.locator('[data-tv-sort-icon]').inner_text(),
                "arrow_downward",
            )
        finally:
            page.close()


if __name__ == "__main__":
    unittest.main()
