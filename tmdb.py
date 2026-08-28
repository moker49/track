from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


class TMDBError(RuntimeError):
    pass


class TMDBClient:
    BASE_URL = "https://api.themoviedb.org/3"

    def __init__(self, access_token: str, transport=None):
        self.access_token = access_token.strip()
        self.transport = transport or urlopen

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
