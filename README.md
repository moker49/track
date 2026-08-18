# Track

A lightweight, single-user TV-show tracker built with Flask, SQLite, HTML, CSS, and vanilla JavaScript.

## Run locally

```powershell
python -m pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5050`. The SQLite database is created automatically in `instance/track.db` on first run.

## TMDB configuration

Copy `.env.example` to `.env`, then place your TMDB API Read Access Token in it. The token is used only by Flask and is never sent to the browser.

```dotenv
TMDB_READ_ACCESS_TOKEN=your-token
```

After that, start the app normally with `python app.py`. An already-defined system environment variable takes precedence over the value in `.env`.

Discover searches TMDB as you type. Popular shows are saved locally and refreshed no more than once every 24 hours. A stale saved response remains available if TMDB is temporarily unreachable. Opening a Discover card displays already-imported details immediately when available, then refreshes them from TMDB. A new card is imported as an untracked local preview; it enters the library only after choosing Start watching or Archive.

Demo data is off by default. To create the two sample shows in a new database, set `TRACK_SEED_DEMO_DATA=1` before the first run.

## Navigation

The browser loads one persistent application shell at `/`. Watching, Archive, and Discover are included in the initial HTML and switch in place without changing the URL. Selecting a show or episode renders an immediate skeleton and fetches only its detail fragment; the outer app shell and navigation are never replaced.

## Data model

- `shows` stores imported show metadata, whether the show is tracked, its Watching/Archive state, lifecycle timestamps, the last TMDB refresh, and the complete source payload.
- `show_state_history` retains every state entry for future transitions and reporting.
- `seasons` and `episodes` store local TMDB-shaped metadata and IDs.
- `episode_watch_history` stores one row per watch event with an immutable `added_at` timestamp and an optional user-selected `watch_date`.
- `season_watch_history` uses the same two-date model for whole-season watch actions.
- `tmdb_cache` stores cacheable Discover responses such as the once-daily popular list.

Schema changes are applied through the small versioned migration runner. TMDB refreshes update shows, seasons, and episodes in place by TMDB ID, preserving local row IDs and watch history. Season zero and any season marked special are imported and remain watchable, but are excluded from show and season progress.

Removing a show demotes it to an untracked preview. It disappears from Watching and Archive while its imported metadata and complete watch history remain available for Discover and later re-adding.

Episode and season controls support individual rewatches. Watch logs use the chosen watch date when present and otherwise fall back to the added date. Unwatching removes the latest effective entry. Tapping a watch-log entry opens the date picker without changing normal watch behavior.
