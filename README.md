# Track

A lightweight, single-user TV-show tracker built with Flask, SQLite, HTML, CSS, and vanilla JavaScript.

## Run locally

```powershell
python -m pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5050`. The SQLite database and realistic sample show are created automatically in `instance/track.db` on first run.

## Navigation

The browser loads one persistent application shell at `/`. Watching, Archive, and Discover are included in the initial HTML and switch in place without changing the URL. Selecting a show or episode renders an immediate skeleton and fetches only its detail fragment; the outer app shell and navigation are never replaced.

## Data model

- `shows` stores imported show metadata, the current state, and lifecycle timestamps.
- `show_state_history` retains every state entry for future transitions and reporting.
- `seasons` and `episodes` store local TMDB-shaped metadata and IDs.
- `episode_watch_history` stores one row per watch event with an immutable `added_at` timestamp and an optional user-selected `watch_date`.
- `season_watch_history` uses the same two-date model for whole-season watch actions.
- `popular_show_stubs` supplies placeholder Search content until TMDB integration.

Episode and season controls support individual rewatches. Watch logs use the chosen watch date when present and otherwise fall back to the added date. Unwatching removes the latest effective entry. Tapping a watch-log entry opens the date picker without changing normal watch behavior.
