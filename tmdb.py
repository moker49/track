from __future__ import annotations

import json
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


class TMDBError(RuntimeError):
    pass


class TokenBucketRateLimiter:
    """Thread-safe limiter shared by all TMDB clients in this process."""

    def __init__(
        self,
        requests_per_second: float = 4,
        burst_size: int = 8,
        *,
        clock=time.monotonic,
        sleep=time.sleep,
    ):
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        if burst_size < 1:
            raise ValueError("burst_size must be at least one")
        self.requests_per_second = requests_per_second
        self.burst_size = burst_size
        self._clock = clock
        self._sleep = sleep
        self._tokens = float(burst_size)
        self._updated_at = clock()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Wait until one request token is available."""
        while True:
            with self._lock:
                now = self._clock()
                elapsed = max(0.0, now - self._updated_at)
                self._tokens = min(
                    float(self.burst_size),
                    self._tokens + elapsed * self.requests_per_second,
                )
                self._updated_at = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                wait_seconds = (1 - self._tokens) / self.requests_per_second
            self._sleep(wait_seconds)


TMDB_REQUEST_LIMITER = TokenBucketRateLimiter()


class TMDBClient:
    BASE_URL = "https://api.themoviedb.org/3"

    def __init__(self, access_token: str, transport=None, rate_limiter=None):
        self.access_token = access_token.strip()
        self.transport = transport or urlopen
        self.rate_limiter = rate_limiter or TMDB_REQUEST_LIMITER

    @property
    def configured(self) -> bool:
        return bool(self.access_token)

    def _get(self, path: str, **params) -> dict:
        if not self.configured:
            raise TMDBError("TMDB is not configured")
        query = urlencode({key: value for key, value in params.items() if value is not None})
        url = f"{self.BASE_URL}{path}" + (f"?{query}" if query else "")
        request = Request(
            url,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Accept": "application/json",
                "User-Agent": "Track/1.0",
            },
        )
        try:
            self.rate_limiter.acquire()
            with self.transport(request, timeout=15) as response:
                return json.load(response)
        except HTTPError as error:
            raise TMDBError(f"TMDB returned HTTP {error.code}") from error
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            raise TMDBError("TMDB could not be reached") from error

    def popular_tv(self, page: int = 1) -> dict:
        return self._get("/tv/popular", language="en-US", page=page)

    def search_tv(self, query: str, page: int = 1) -> dict:
        return self._get(
            "/search/tv",
            query=query,
            include_adult="false",
            language="en-US",
            page=page,
        )

    def search_movie(self, query: str, page: int = 1) -> dict:
        return self._get(
            "/search/movie",
            query=query,
            include_adult="false",
            language="en-US",
            page=page,
        )

    def movie(self, tmdb_id: int) -> dict:
        return self._get(f"/movie/{tmdb_id}", language="en-US")

    def movie_credits(self, tmdb_id: int) -> dict:
        return self._get(f"/movie/{tmdb_id}/credits", language="en-US")

    def show_credits(self, tmdb_id: int) -> dict:
        return self._get(f"/tv/{tmdb_id}/credits", language="en-US")

    def show_bundle(self, tmdb_id: int) -> tuple[dict, list[dict]]:
        show = self._get(f"/tv/{tmdb_id}", language="en-US")
        seasons = []
        for season in show.get("seasons", []):
            season_number = season.get("season_number")
            if season_number is None:
                continue
            seasons.append(
                self._get(
                    f"/tv/{tmdb_id}/season/{quote(str(season_number))}",
                    language="en-US",
                )
            )
        return show, seasons
