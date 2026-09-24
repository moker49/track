# Architecture

Track is a server-rendered Flask application with a persistent, single-page browser shell. It deliberately avoids a frontend framework and keeps SQLite as the source of truth.

## Backend boundaries

- `app.py` owns application construction, HTTP validation, response codes, and template/JSON responses.
- `database.py` owns SQLite connections and idempotent schema bootstrap.
- `domain.py` owns tracking/progress vocabulary, presentation rules, and the canonical effective-watch-date expression.
- `queries.py` owns read models used by the TV, Queue, Upcoming, show, and watch-progress views.
- `watch_service.py` owns transactional episode/season watch mutations.
- `refresh_service.py` owns oldest-first TV-show and recent-movie refresh orchestration, persisted retry backoff, and failure isolation.
- `tmdb.py` and `image_cache.py` own external TMDB metadata and image concerns.

Cast hydration runs through two background workers and a bounded queue. Each job
fetches one title's credits and caches its portraits sequentially. Tests drain
and stop the workers before removing their temporary databases.

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

The former Profile floating-chrome interaction is retained as an implementation reference in [profile-floating-chrome.md](profile-floating-chrome.md). It is not active in the current navigation.

## Database startup

The canonical schema is applied idempotently at startup, followed by `PRAGMA optimize`. Startup creates missing canonical tables and indexes only; it does not alter existing table layouts or migrate historical data. Schema changes that require an upgrade must be delivered as an explicit, separately run migration.

Startup is safe to repeat. Tests open the same database more than once and verify that tables and indexes remain intact.

## Season log batches

A season watch or skip is one atomic action. It creates a `season_log_batches` row,
one season-level activity row, and one episode-level resolution row for every
episode in that season. Each record shares the batch ID, action kind, creation
timestamp, and Diary date. Editing or removing the season-level log applies to
the complete batch only; individually created episode logs are never affected.

## Test layers

- `tests/test_domain.py` covers vocabulary and effective-date rules.
- `tests/test_app.py` covers API, rendering, TMDB, media, and background-refresh behavior.
- `tests/test_smoke.py` covers end-to-end server workflows across several endpoints and persisted records.
- `tests/test_browser_smoke.py` is an optional Playwright suite for the persistent-shell interactions. It skips cleanly when Playwright is not installed.

Run the standard suite with `python -m unittest discover -s tests -q`. See the README for the optional browser setup.
