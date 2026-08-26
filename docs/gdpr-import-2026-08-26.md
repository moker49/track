# One-time GDPR import — August 26, 2026

Track's dummy library was replaced with the user's export from the discontinued source application. The import was staged from `gdpr-data.zip`, TMDB metadata was downloaded before mutation, and the database replacement ran atomically.

## Imported

- 167 locally cached shows: 117 Active, 22 Archived, and 28 Untracked.
- 710 seasons and 11,071 episodes, including specials.
- 5,651 local watch events spanning May 2, 2014 through June 30, 2026.
- 11 whole-season watch actions.
- Four favorite-show markers.
- One show note and four non-empty episode notes.
- TVDB identifiers for shows and all 4,595 source episodes represented by watch history.

The source contained 5,670 watch rows. Nineteen same-day rows represented split parts or obsolete provider duplicates that TMDB models as one episode; these were collapsed into the corresponding single local watch event. Rewatch rows remain separate watch-history entries. The source did not retain truthful individual rewatch dates, so its supplied timestamps were preserved without inventing dates.

## Provider reconciliation

- TVDB's anthology record `345246` (`The Haunting`) was mapped to TMDB `72844`, matching the exported Hill House season and its ten watched episodes.
- TVDB modeled `Jury Duty Presents: Company Retreat` as season 2 of `Jury Duty`; TMDB models it as show `312697`, so it was imported as a separate Active show.
- Provider numbering differences and combined finales were reconciled by exact episode title and air date. All source TVDB aliases are retained in `episode_external_ids`.
- Three source records without a current TMDB episode equivalent were retained as non-progress-counted specials: `A Parks and Recreation Special`, `Black Mirror: Bandersnatch`, and one unidentified deleted Grey's Anatomy source record.
- Historical timestamps without timezone offsets were interpreted as UTC, matching the source export's server timestamps.

## Deliberately excluded

Credentials and tokens, IP/device/ad identifiers, sessions, social graph data, notification history, install analytics, and campaign data were not imported. Two third-party reaction/vote records were also excluded because the export does not define their value scale well enough to translate them accurately.

The temporary extraction, metadata cache, one-time importer, and resolver were removed after integrity, foreign-key, endpoint, and automated-test validation completed. Two database recovery snapshots remain in `instance/`.

## Post-import classification adjustments

- `The Secret Life of the American Teenager` was restored as Archived. Its activity starts with `Added to My Shows` at its first imported watch on April 3, 2016 and records `Archived` at its last imported watch later that day.
- The 43 imported Active shows with no watch history were interpreted as the discontinued app's future watchlist. Each was moved to Archived, its original added timestamp was retained as its archive timestamp, and its initial activity is represented as `Added to Archive` rather than as an Active-to-Archived transition.

After these adjustments, the 167 cached shows comprise 74 Active, 66 Archived, and 27 Untracked shows.
