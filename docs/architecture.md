# Architecture

Track is a server-rendered Flask application with a persistent, single-page browser shell. It deliberately avoids a frontend framework and keeps SQLite as the source of truth.

## Backend boundaries

- `app.py` owns application construction, HTTP validation, response codes, and template/JSON responses.
- `database.py` owns SQLite connections and the one-pass bootstrap/migration sequence.
- `migrations.py` owns ordered, idempotent schema upgrades. A migration version is recorded only after it succeeds.
- `domain.py` owns tracking/progress vocabulary, presentation rules, and the canonical effective-watch-date expression.
- `queries.py` owns read models used by the TV, Queue, Upcoming, show, and watch-progress views.
- `watch_service.py` owns transactional episode/season watch mutations.
- `refresh_service.py` owns batch refresh orchestration and failure isolation.
- `tmdb.py` and `image_cache.py` own external TMDB metadata and image concerns.

Routes should validate HTTP input, call one of these boundaries, and serialize the result. New business rules should not be embedded in route functions or duplicated in templates.

## Browser state and invalidation

The HTML shell is loaded once. `static/app.js` swaps fragments into Queue, Upcoming, TV, show detail, and episode detail views. The in-memory caches are intentionally session-only:

- show overview fragments;
- show season fragments;
- season episode fragments;
- episode detail fragments;
- decoded/preloaded media.

Every watch mutation goes through `invalidateWatchCaches(...)`. It clears the affected episode/show fragments and, for season-wide operations, all episode fragments for that show. Metadata refreshes additionally clear season fragments. Keeping invalidation behind these helpers prevents one screen from retaining stale watch controls after another screen changes them.

Frontend modularization is intentionally deferred until a bundler is introduced.

## Database startup

On a new database, the canonical schema is created once and all migration versions are recorded. On an existing database, pending migrations run first; the idempotent schema is then applied once to restore indexes that SQLite table-rebuild migrations may remove. `PRAGMA optimize` finishes startup.

Startup is safe to repeat. Tests open the same database more than once and verify the migration ledger remains unique and complete.

## Test layers

- `tests/test_domain.py` covers vocabulary and effective-date rules.
- `tests/test_app.py` covers API, rendering, migration, TMDB, media, and background-refresh behavior.
- `tests/test_smoke.py` covers end-to-end server workflows across several endpoints and persisted records.
- `tests/test_browser_smoke.py` is an optional Playwright suite for the persistent-shell interactions. It skips cleanly when Playwright is not installed.

Run the standard suite with `python -m unittest discover -s tests -q`. See the README for the optional browser setup.
