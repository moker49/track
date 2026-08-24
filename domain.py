from __future__ import annotations

from dataclasses import dataclass


TRACKING_ACTIVE = "ACTIVE"
TRACKING_ARCHIVED = "ARCHIVED"
TRACKING_STATES = frozenset({TRACKING_ACTIVE, TRACKING_ARCHIVED})

PROGRESS_NEW = "new"
PROGRESS_STARTED = "started"
PROGRESS_CAUGHT_UP = "caught-up"
PROGRESS_FINISHED = "finished"
PROGRESS_STATES = frozenset(
    {PROGRESS_NEW, PROGRESS_STARTED, PROGRESS_CAUGHT_UP, PROGRESS_FINISHED}
)
TERMINAL_SHOW_STATUSES = frozenset({"ended", "canceled", "cancelled"})


@dataclass(frozen=True)
class ProgressPresentation:
    state: str
    css_state: str
    label: str


@dataclass(frozen=True)
class MovePresentation:
    target_state: str
    label: str
    icon: str


def progress_presentation(
    tracking_state: str,
    watched_count: int,
    episode_count: int,
    series_status: str | None,
) -> ProgressPresentation:
    if watched_count <= 0:
        return ProgressPresentation(PROGRESS_NEW, "not-started", "New")
    if episode_count > 0 and watched_count >= episode_count:
        if (series_status or "").strip().casefold() not in TERMINAL_SHOW_STATUSES:
            return ProgressPresentation(PROGRESS_CAUGHT_UP, "caught-up", "Caught up")
        return ProgressPresentation(PROGRESS_FINISHED, "finished", "Finished")
    label = "Stopped" if tracking_state == TRACKING_ARCHIVED else "Watching"
    return ProgressPresentation(PROGRESS_STARTED, "started", label)


def move_presentation(tracking_state: str) -> MovePresentation:
    if tracking_state == TRACKING_ARCHIVED:
        return MovePresentation(TRACKING_ACTIVE, "Resume", "resume")
    return MovePresentation(TRACKING_ARCHIVED, "Archive", "archive")


def effective_watch_date_sql(alias: str = "") -> str:
    """Return the canonical effective-date SQL for a watch-history row.

    ``watch_date`` is the user's date-only override. When it is absent, the UTC
    calendar date of immutable ``added_at`` is used.
    """

    prefix = f"{alias}." if alias else ""
    return (
        f"COALESCE({prefix}watch_date, "
        f"substr({prefix}added_at, 1, 10))"
    )
