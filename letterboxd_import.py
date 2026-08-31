"""Import a Letterboxd export into Track.

Only exact title/year TMDB matches are imported.  The report is intentionally
written to stdout so questionable entries can be corrected rather than guessed.
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from database import connect_database, initialize_database
from domain import TRACKING_ACTIVE, TRACKING_ARCHIVED
from tmdb import TMDBClient, TMDBError
from tmdb_import import import_or_refresh_show


BASE_DIR = Path(__file__).resolve().parent


class RateLimitedTMDBClient(TMDBClient):
    """A deliberately conservative client for a one-time personal import."""

    def __init__(self, access_token: str) -> None:
        super().__init__(access_token)
        self._next_request_at = 0.0

    def _get(self, path: str, **params) -> dict:
        delay = self._next_request_at - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        try:
            return super()._get(path, **params)
        finally:
            # 2.5 requests/sec leaves substantial room below TMDB's normal
            # short-window allowance and avoids a burst at import start.
            self._next_request_at = time.monotonic() + 0.4


def rows(archive: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
    with archive.open(name) as file:
        return list(csv.DictReader((line.decode("utf-8-sig") for line in file)))


def norm(value: str | None) -> str:
    return re.sub(r"\W+", "", (value or "").casefold())


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def upsert_movie(db, movie: dict, state: str, liked: bool, undated_watched: bool) -> int:
    timestamp = now()
    db.execute(
        """
        INSERT INTO movies (tmdb_id, title, original_title, overview, poster_path,
          backdrop_path, release_date, runtime_minutes, status, genres,
          original_language, state, is_tracked, liked, is_watched_without_diary,
          added_at, active_at, archived_at, updated_at, tmdb_refreshed_at, tmdb_payload)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?,?,?,?,?)
        ON CONFLICT(tmdb_id) DO UPDATE SET
          title=excluded.title, original_title=excluded.original_title,
          overview=excluded.overview, poster_path=excluded.poster_path,
          backdrop_path=excluded.backdrop_path, release_date=excluded.release_date,
          runtime_minutes=excluded.runtime_minutes, status=excluded.status,
          genres=excluded.genres, original_language=excluded.original_language,
          state=excluded.state, is_tracked=1, liked=excluded.liked,
          is_watched_without_diary=excluded.is_watched_without_diary,
          updated_at=excluded.updated_at, tmdb_refreshed_at=excluded.tmdb_refreshed_at,
          tmdb_payload=excluded.tmdb_payload
        """,
        (movie["id"], movie.get("title") or "Untitled movie", movie.get("original_title"),
         movie.get("overview"), movie.get("poster_path"), movie.get("backdrop_path"),
         movie.get("release_date"), movie.get("runtime"), movie.get("status"),
         ", ".join(item.get("name", "") for item in movie.get("genres", [])),
         movie.get("original_language"), state, int(liked), int(undated_watched), timestamp,
         timestamp if state == TRACKING_ACTIVE else None,
         timestamp if state == TRACKING_ARCHIVED else None, timestamp, timestamp,
         json.dumps(movie)),
    )
    movie_id = db.execute("SELECT id FROM movies WHERE tmdb_id = ?", (movie["id"],)).fetchone()[0]
    db.execute(
        "INSERT INTO movie_state_history (movie_id, state, entered_at) SELECT ?, ?, ? WHERE NOT EXISTS (SELECT 1 FROM movie_state_history WHERE movie_id = ?)",
        (movie_id, state, timestamp, movie_id),
    )
    return movie_id


def main(export_path: str, retry_skipped: bool = False) -> int:
    load_dotenv(BASE_DIR / ".env")
    token = os.environ.get("TMDB_READ_ACCESS_TOKEN", "")
    if not token:
        print("TMDB_READ_ACCESS_TOKEN is not configured.", file=sys.stderr)
        return 2
    with zipfile.ZipFile(export_path) as archive:
        watched = {(row["Name"], row["Year"]) for row in rows(archive, "watched.csv")}
        watchlist = {(row["Name"], row["Year"]) for row in rows(archive, "watchlist.csv")}
        liked = {(row["Name"], row["Year"]) for row in rows(archive, "likes/films.csv")}
        diary = defaultdict(list)
        for row in rows(archive, "diary.csv"):
            diary[(row["Name"], row["Year"])].append(row["Watched Date"])

    entries = watched | watchlist | liked | set(diary)
    if retry_skipped:
        log_path = BASE_DIR / "letterboxd-import-2.log"
        skipped = {
            (match.group(1), match.group(2))
            for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            if (match := re.match(r"SKIP (.+) \((\d{4})\):", line))
        }
        entries &= skipped
        entries.discard(("Black Mirror: White Christmas", "2014"))
    client = RateLimitedTMDBClient(token)
    db = connect_database(BASE_DIR / "instance" / "track.db")
    initialize_database(db, BASE_DIR / "schema.sql")
    imported = skipped = 0
    for index, (title, year) in enumerate(sorted(entries), start=1):
        try:
            candidates = client.search_movie(title).get("results", [])
            title_matches = [item for item in candidates if norm(item.get("title")) == norm(title)]
            exact = [item for item in title_matches if item.get("release_date", "")[:4] == year]
            off_by_one = [
                item for item in title_matches
                if item.get("release_date", "")[:4].isdigit()
                and abs(int(item["release_date"][:4]) - int(year)) == 1
            ]
            selected = max(exact or off_by_one, key=lambda item: item.get("popularity") or 0, default=None)
            if selected is None:
                skipped += 1
                print(f"SKIP {title} ({year}): no title/year or one-year-off match")
                continue
            movie = client.movie(selected["id"])
            # Watchlist deliberately wins over the archived watched state.
            state = TRACKING_ACTIVE if (title, year) in watchlist else TRACKING_ARCHIVED
            movie_id = upsert_movie(db, movie, state, (title, year) in liked,
                                    (title, year) in watched and not diary[(title, year)])
            db.execute("DELETE FROM movie_watch_history WHERE movie_id = ?", (movie_id,))
            db.executemany(
                "INSERT INTO movie_watch_history (movie_id, added_at, watch_date) VALUES (?, ?, ?)",
                [(movie_id, f"{watch_date}T12:00:00+00:00", watch_date) for watch_date in diary[(title, year)]],
            )
            db.commit()
            imported += 1
            print(f"{index}/{len(entries)} imported: {title} ({year})")
        except TMDBError as error:
            db.rollback()
            print(f"SKIP {title} ({year}): {error}")
            skipped += 1
    db.close()
    print(f"Completed: {imported} imported, {skipped} skipped.")
    return 0


def import_manual_corrections(export_path: str) -> int:
    load_dotenv(BASE_DIR / ".env")
    token = os.environ.get("TMDB_READ_ACCESS_TOKEN", "")
    with zipfile.ZipFile(export_path) as archive:
        watched = {(row["Name"], row["Year"]) for row in rows(archive, "watched.csv")}
        watchlist = {(row["Name"], row["Year"]) for row in rows(archive, "watchlist.csv")}
        liked = {(row["Name"], row["Year"]) for row in rows(archive, "likes/films.csv")}
    client = RateLimitedTMDBClient(token)
    db = connect_database(BASE_DIR / "instance" / "track.db")
    initialize_database(db, BASE_DIR / "schema.sql")
    for title, year in (("Hamilton", "2020"), ("The Upside", "2017")):
        result = next(item for item in client.search_movie(title)["results"] if norm(item.get("title")) == norm(title))
        movie = client.movie(result["id"])
        state = TRACKING_ACTIVE if (title, year) in watchlist else TRACKING_ARCHIVED
        upsert_movie(db, movie, state, (title, year) in liked, (title, year) in watched)
        db.commit()
        print(f"imported movie: {title} ({movie.get('release_date', '')[:4]})")
    title, year = "The Playlist", "2022"
    result = next(item for item in client.search_tv(title)["results"] if norm(item.get("name")) == norm(title))
    show, seasons = client.show_bundle(result["id"])
    state = TRACKING_ACTIVE if (title, year) in watchlist else TRACKING_ARCHIVED
    show_id, _created, _newly_tracked = import_or_refresh_show(db, show, seasons, state)
    db.execute("UPDATE shows SET liked = ? WHERE id = ?", (int((title, year) in liked), show_id))
    db.commit()
    print(f"imported TV: {title} ({show.get('first_air_date', '')[:4]})")
    db.close()
    return 0


def apply_letterboxd_state_dates(export_path: str) -> int:
    with zipfile.ZipFile(export_path) as archive:
        watched_rows = rows(archive, "watched.csv")
        watchlist_rows = rows(archive, "watchlist.csv")
    # A title is sufficient here because these are the exact source records used
    # for this one import; watchlist deliberately overrides watched.
    source_dates = {row["Name"]: row["Date"] for row in watched_rows}
    source_dates.update({row["Name"]: row["Date"] for row in watchlist_rows})
    normalized_source_dates = {norm(title): value for title, value in source_dates.items()}
    db = connect_database(BASE_DIR / "instance" / "track.db")
    initialize_database(db, BASE_DIR / "schema.sql")
    movie_updates = show_updates = 0
    for movie in db.execute("SELECT id, title, state FROM movies WHERE is_tracked = 1").fetchall():
        source_date = source_dates.get(movie["title"]) or normalized_source_dates.get(norm(movie["title"]))
        if not source_date:
            continue
        timestamp = f"{source_date}T12:00:00+00:00"
        db.execute(
            "UPDATE movies SET added_at = ?, active_at = CASE WHEN state = 'ACTIVE' THEN ? ELSE active_at END, archived_at = CASE WHEN state = 'ARCHIVED' THEN ? ELSE archived_at END WHERE id = ?",
            (timestamp, timestamp, timestamp, movie["id"]),
        )
        db.execute(
            "UPDATE movie_state_history SET entered_at = ? WHERE id = (SELECT id FROM movie_state_history WHERE movie_id = ? ORDER BY id LIMIT 1)",
            (timestamp, movie["id"]),
        )
        movie_updates += 1
    for title, source_date in source_dates.items():
        # The Playlist is the sole TV item explicitly imported from this
        # Letterboxd export. Do not accidentally match pre-existing shows that
        # happen to share a film title.
        shows = db.execute("SELECT id, state FROM shows WHERE name = ? AND is_tracked = 1", (title,)).fetchall() if title == "The Playlist" else []
        for show in shows:
            timestamp = f"{source_date}T12:00:00+00:00"
            db.execute(
                "UPDATE shows SET added_at = ?, active_at = CASE WHEN state = 'ACTIVE' THEN ? ELSE active_at END, archived_at = CASE WHEN state = 'ARCHIVED' THEN ? ELSE archived_at END WHERE id = ?",
                (timestamp, timestamp, timestamp, show["id"]),
            )
            db.execute(
                "UPDATE show_state_history SET entered_at = ? WHERE id = (SELECT id FROM show_state_history WHERE show_id = ? ORDER BY id LIMIT 1)",
                (timestamp, show["id"]),
            )
            show_updates += 1
    db.commit()
    db.close()
    print(f"updated {movie_updates} movies and {show_updates} shows")
    return 0


if __name__ == "__main__":
    if len(sys.argv) not in {2, 3} or (len(sys.argv) == 3 and sys.argv[2] not in {"--retry-skipped", "--manual-corrections", "--apply-letterboxd-state-dates"}):
        print("Usage: python letterboxd_import.py <letterboxd-export.zip> [--retry-skipped|--manual-corrections|--apply-letterboxd-state-dates]", file=sys.stderr)
        raise SystemExit(2)
    if len(sys.argv) == 3 and sys.argv[2] == "--manual-corrections":
        raise SystemExit(import_manual_corrections(sys.argv[1]))
    if len(sys.argv) == 3 and sys.argv[2] == "--apply-letterboxd-state-dates":
        raise SystemExit(apply_letterboxd_state_dates(sys.argv[1]))
    raise SystemExit(main(sys.argv[1], retry_skipped=len(sys.argv) == 3))
