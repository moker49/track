from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


IMAGE_BASE_URL = "https://image.tmdb.org/t/p"
ALLOWED_SIZES = {
    "poster": {"w185", "w342"},
    "backdrop": {"w780"},
    "season": {"w185", "w342"},
    "still": {"w300"},
}
CONTENT_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
TMDB_PATH_PATTERN = re.compile(r"^/[A-Za-z0-9_.-]+$")


class ImageCacheError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_tmdb_path(value: str) -> str:
    path = f"/{value.lstrip('/')}"
    if not TMDB_PATH_PATTERN.fullmatch(path):
        raise ImageCacheError("Invalid TMDB image path")
    return path


def cached_image(
    db: sqlite3.Connection,
    cache_root: Path,
    image_type: str,
    size: str,
    tmdb_path: str,
    transport=urlopen,
) -> tuple[Path, str]:
    if image_type not in ALLOWED_SIZES or size not in ALLOWED_SIZES[image_type]:
        raise ImageCacheError("Unsupported image size")
    tmdb_path = normalize_tmdb_path(tmdb_path)
    cached = db.execute(
        """
        SELECT local_filename, content_type
        FROM image_cache
        WHERE tmdb_path = ? AND image_type = ? AND size = ?
        """,
        (tmdb_path, image_type, size),
    ).fetchone()
    if cached is not None:
        cached_path = cache_root / cached["local_filename"]
        if cached_path.is_file():
            return cached_path, cached["content_type"]

    request = Request(
        f"{IMAGE_BASE_URL}/{size}{tmdb_path}",
        headers={"Accept": "image/avif,image/webp,image/png,image/jpeg", "User-Agent": "Track/1.0"},
    )
    try:
        with transport(request, timeout=15) as response:
            content_type = response.headers.get_content_type().lower()
            extension = CONTENT_EXTENSIONS.get(content_type)
            if extension is None:
                raise ImageCacheError("TMDB returned an unsupported image")
            digest = hashlib.sha256(f"{size}:{tmdb_path}".encode()).hexdigest()
            relative_path = Path(image_type) / size / f"{digest}{extension}"
            final_path = cache_root / relative_path
            final_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_name = None
            try:
                with tempfile.NamedTemporaryFile(
                    dir=final_path.parent, prefix=".download-", delete=False
                ) as temporary:
                    temporary_name = temporary.name
                    total = 0
                    while chunk := response.read(64 * 1024):
                        total += len(chunk)
                        if total > MAX_IMAGE_BYTES:
                            raise ImageCacheError("TMDB image is too large")
                        temporary.write(chunk)
                os.replace(temporary_name, final_path)
            finally:
                if temporary_name and os.path.exists(temporary_name):
                    os.unlink(temporary_name)
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise ImageCacheError("TMDB image could not be downloaded") from error

    db.execute(
        """
        INSERT INTO image_cache (
            tmdb_path, image_type, size, local_filename, content_type, downloaded_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(tmdb_path, image_type, size) DO UPDATE SET
            local_filename = excluded.local_filename,
            content_type = excluded.content_type,
            downloaded_at = excluded.downloaded_at
        """,
        (tmdb_path, image_type, size, relative_path.as_posix(), content_type, _now()),
    )
    db.commit()
    return final_path, content_type
