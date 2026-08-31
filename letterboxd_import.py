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
    return db.execute("SELECT id FROM movies WHERE tmdb_id = ?", (movie["id"],)).fetchone()[0]


def main(export_path: str) -> int:
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
    client = RateLimitedTMDBClient(token)
    db = connect_database(BASE_DIR / "instance" / "track.db")
    initialize_database(db, BASE_DIR / "schema.sql")
    imported = skipped = 0
    for index, (title, year) in enumerate(sorted(entries), start=1):
        try:
            candidates = client.search_movie(title).get("results", [])
            exact = [item for item in candidates if item.get("release_date", "")[:4] == year and norm(item.get("title")) == norm(title)]
            if len(exact) != 1:
                skipped += 1
                print(f"SKIP {title} ({year}): {'no exact match' if not exact else 'ambiguous exact match'}")
                continue
            movie = client.movie(exact[0]["id"])
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


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python letterboxd_import.py <letterboxd-export.zip>", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
