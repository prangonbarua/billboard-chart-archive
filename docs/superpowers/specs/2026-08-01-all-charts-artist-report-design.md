# All-charts artist report

Date: 2026-08-01

## Problem

`/analyze` calls exactly two functions. `prepare_visualization_data` reads
`BILLBOARD_DATA` and filters to `Date >= 1990-01-01`; `prepare_album_data`
reads `BILLBOARD_200_DATA`. Neither touches `CHART_DATA`.

Two consequences, both measured against the current data:

- 14 of the 16 registered charts are invisible to the report. An artist whose
  career lives on Country Airplay or Adult Contemporary gets a report that says
  nothing about it.
- 163,861 Hot 100 rows are dropped, 46% of that chart's history. Pre-1990
  artists get a truncated report that reads as a complete one.

A third gap sits upstream of both: `/search`'s autocomplete pool is
`MODERN_ARTISTS`, 2,943 names drawn from Hot 100 1990+. The union of all 16
charts' artist pools is 15,152. **12,209 artists would have a report under this
change and no way to reach it.** Widening the pool is therefore part of this
work, not a follow-up.

## Scope

This spec covers chart coverage only. Song-level search — a song entity the app
does not have today, since only artists are searchable — is a separate feature
and gets its own spec.

## Approach

The versus feature already solved the hard half. `_versus_artist_rows`
(`app.py:603`) does per-chart artist filtering with correct credit matching, and
`versus.compute_artist_stats` (`versus.py:125`) returns entries, number ones,
weeks at #1, top 10s, top 40s, best peak, weeks charted, first and last entry,
biggest hit, and a weekly timeline. This change wires those over the whole
registry rather than writing new stat logic.

### Measurements that shaped the design

| Measurement | Value |
|---|---|
| Full 16-chart summary sweep, per artist | 0.25s |
| All-16 per-song detail payload (Taylor Swift) | 519 KB |
| Hot 100 rows currently excluded by the 1990 filter | 163,861 of 354,761 |
| Artists reportable but not searchable | 12,209 |

The sweep is cheap enough to run inline on the POST. The detail payload is not
cheap enough to inline. That split is the architecture.

## Backend

Replace `prepare_visualization_data` and `prepare_album_data` with:

**`artist_chart_summaries(artist_name)`** — iterates the 16 `CHARTS` entries,
calls `_versus_artist_rows` then `versus.compute_artist_stats(rows,
kind=meta['kind'])`, drops charts with zero rows. Returns the coverage rows plus
the count of charts hidden for having no entries. Returns `None` when the artist
charted nowhere, so `/analyze`'s existing "no results" flash path is unchanged.

**`artist_chart_detail(artist_name, chart_key)`** — per-song series and song
table for one chart. This is today's `prepare_visualization_data` body with the
`>= 1990-01-01` filter deleted and the frame parameterized off `CHART_DATA`.

**`GET /api/artist-chart?artist=&chart=`** — returns `artist_chart_detail`.
Validates `chart` against `CHARTS` and returns 400 on an unknown key, matching
`/api/versus`.

**`/api/artists`** — the no-`chart` case serves the union of every chart's
artist pool instead of `MODERN_ARTISTS`. Precomputed at startup alongside
`CHART_ARTISTS`. The `?chart=` case is untouched, so the versus page is
unaffected.

`/download-csv/<artist>` already accepts `?chart=` (`app.py:1866`). No backend
change; the report's download button passes the selected key.

## Frontend

`results.html`. The coverage table renders one row per chart the artist actually
charted on, in registry order so it reads in the same order as the nav, with a
note stating how many charts were hidden for having no entries — absence should
be explicit rather than looking like missing data.

**Coverage rows are the picker.** Clicking a row selects that chart and
re-renders the graph and song table below it; the selected row is highlighted. A
separate dropdown alongside a 16-row clickable table would be two controls doing
one job.

Detail is fetched from `/api/artist-chart` on selection and cached in a JS object
keyed by chart key, so re-selecting is instant. The default chart's detail is
server-rendered with the page, so there is no blank flash on load.

The default selected chart is the one with the most entries, not always the Hot
100 — a country act should not land on a view they barely charted on.

The **Songs/Albums tabs are removed**. Billboard 200 is now a row in the coverage
table whose detail view is headed "Albums" rather than "Songs".

## Edge cases

**`artist100` is `kind='artist'`.** `compute_artist_stats` nulls `entries`,
`number_ones`, `top_10s` and `top_40s` for that kind (`versus.py`,
`_ARTIST_KIND_NULLS`), because grouping an artist chart by (song, artist)
collapses to one group and those stats become booleans in disguise. Its coverage
row renders an em dash for each nulled stat, matching how the versus scorecard
draws the same distinction. Its detail view shows the rank timeline and no song
table, since there is only ever one pseudo-entry.

**Charts with no entries are hidden**, not rendered empty.

**Nulled stats never render as 0.** An em dash means "not meaningful for this
chart kind"; 0 means "genuinely none". Conflating them is the bug this rule
exists to prevent.

## Testing

The stat math already lives in `versus.py`, which is unit-testable without
loading 1.5M rows, and is already covered. New tests target the wiring:

- `artist_chart_summaries` returns only charts the artist actually charted on.
- `artist_chart_summaries` yields `None`, not `0`, for `artist100`'s nulled
  stats.
- `/api/artist-chart` returns 400 on an unknown chart key.
- The widened autocomplete pool contains a known pre-1990 artist and a known
  country-only artist, neither of which is in `MODERN_ARTISTS`.
- A pre-1990 artist's report is non-empty. This is the regression the change
  exists to fix, so it gets a test that fails against the current code.
