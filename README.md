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
- `episode_watch_history` stores one timestamped row per watch event, supporting rewatches. Unchecking retires active events without deleting their original watch dates.
- `season_watch_history` records whole-season watch actions. Unwatching retires the latest visible season entry while preserving its original timestamp.
- `popular_show_stubs` supplies placeholder Search content until TMDB integration.

Episode and season controls support individual rewatches. Their collapsible activity logs show active watch entries; unwatching removes the latest entry from the visible log while retaining the underlying historical row.
