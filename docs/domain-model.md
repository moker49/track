# Track domain model

This document defines the vocabulary used by the database, Flask, templates,
and browser code. UI wording may be friendlier than stored values, but it must
map to these concepts.

## Tracking state

A locally cached show is either untracked or tracked. `is_tracked` is the only
authority for that distinction.

Tracked shows have one of two stored `state` values:

| Stored value | Meaning | Primary UI label |
| --- | --- | --- |
| `ACTIVE` | Included in Queue and the active TV library | Active |
| `ARCHIVED` | Retained in the archived TV library and Upcoming, but excluded from Queue | Archived |

An untracked show retains metadata and watch history. Its stored `state` is
dormant until it is tracked again and must not be interpreted as current.

## Progress state

Progress is derived from released, non-special episodes. It is never stored.

| Canonical state | Rule | Card label |
| --- | --- | --- |
| `new` | No counted episode has ever been watched | New |
| `started` | At least one, but not all, counted episodes have been watched | Watching when Active; Stopped when Archived |
| `caught-up` | Every released counted episode has been watched and the series is not ended | Caught up |
| `finished` | Every released counted episode has been watched and the series is ended or canceled | Finished |

`Watching` and `Stopped` are presentation labels for the same canonical
`started` progress state. They are not tracking states.

`Caught up` and `Finished` share the completion color and the `Caught-up`
filter option, while remaining distinct canonical states for display and future
statistics.

Specials remain watchable but have `is_progress_counted = 0`; they do not
affect these calculations, Queue, or Upcoming.

## Watch events and dates

Every watch is an append-only row in `episode_watch_history` with:

- `added_at`: immutable UTC timestamp recording when Track created the event.
- `watch_date`: optional date-only override chosen by the user.

The canonical effective watch date is:

```sql
COALESCE(watch_date, substr(added_at, 1, 10))
```

Therefore, an event without an override belongs to the UTC calendar date of
`added_at`. Diary and statistics code must use the shared
`effective_watch_date_sql()` helper rather than reproducing this expression.
If local-time attribution is added later, it must be introduced as an explicit
migration and domain change rather than silently changing historical results.

Unwatching removes the latest event ordered by effective date, then
`added_at`, then row ID. Rewatches are separate events and must remain separate
for diary and statistics calculations.

## Lifecycle history

`show_state_history` records entries into `ACTIVE` and `ARCHIVED`. Demoting a
show sets `is_tracked = 0`; it does not delete metadata, watch events, or state
history.
