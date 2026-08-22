from __future__ import annotations

import sqlite3
from collections.abc import Callable

from queries import get_library_show
from tmdb import TMDBError
from tmdb_import import import_or_refresh_show


def refresh_stale_tracked_shows(
    db: sqlite3.Connection,
    *,
    client_factory: Callable,
    metadata_is_fresh: Callable[[str | None], bool],
    include_card_html: bool = False,
    render_card: Callable[[sqlite3.Row], str] | None = None,
) -> dict:
    tracked_shows = db.execute(
        """
        SELECT id, tmdb_id, state, tmdb_refreshed_at
        FROM shows
        WHERE is_tracked = 1
        ORDER BY id
        """
    ).fetchall()
    stale_shows = [
        show
        for show in tracked_shows
        if not metadata_is_fresh(show["tmdb_refreshed_at"])
    ]
    refreshed_shows = []
    failures = []
    client = client_factory() if stale_shows else None

    for local_show in stale_shows:
        try:
            show, seasons = client.show_bundle(local_show["tmdb_id"])
            if show.get("id") != local_show["tmdb_id"]:
                raise TMDBError("TMDB returned the wrong show")
            refreshed_id, _created, _newly_tracked = import_or_refresh_show(
                db, show, seasons, local_show["state"]
            )
            refreshed_show = get_library_show(db, refreshed_id)
            result = {
                "show_id": refreshed_id,
                "refreshed_at": refreshed_show["tmdb_refreshed_at"],
            }
            if include_card_html and render_card is not None:
                result["card_html"] = render_card(refreshed_show)
            refreshed_shows.append(result)
        except (TMDBError, ValueError, sqlite3.Error) as error:
            failures.append({"show_id": local_show["id"], "error": str(error)})

    return {
        "refreshed": refreshed_shows,
        "failures": failures,
        "skipped": len(tracked_shows) - len(stale_shows),
    }
