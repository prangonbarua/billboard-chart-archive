# Cross-chart song and album lookup

Answers one question everywhere it can be asked: **where else did this title chart?**

Today that question has exactly one answer, for exactly one pair of charts.
`_crossover_run` (app.py) joins Bubbling Under against the Hot 100 and nothing
else, because `CROSSOVER_CHART = {'bubbling': 'top100', 'top100': 'bubbling'}` is
a hardcoded pair. Every other chart's song modal shows no crossover section at
all. This generalizes that one pair to the whole archive.

Two requested entry points — highlight a song on a chart, and search a song by
name — are the same capability behind two surfaces, not two features.

## Scope

In:

- Every weekly chart in the registry, matched by `kind`.
- Song modals on every chart page.
- A title search on the reports page.

Out, deliberately:

- **The nav redesign.** Declined 2026-08-21. The chart dropdown's crowding is
  a separate concern and is not addressed here, in any form — no search-in-nav,
  no sub-grouping.
- Rank sparklines in the result rows.
- Year-end charts. They live in a separate structure from the weekly frames.

## Measurements

Taken 2026-08-21 against the real data (157 CSVs, 6,413,280 rows, 400 MB), not
estimated. These numbers are what decided the architecture.

| approach | memory | per lookup | build |
|---|---|---|---|
| Naive scan of every chart per request | none | **0.94s** | none |
| Index as a dict of tuples | ~100-150 MB live | 0.8us | 9.0s |
| **Index as a DataFrame, sorted MultiIndex** | **33 MB** | **0.53ms** | 10.7s |

AS BUILT the frame is 543,400 rows, **63 MB**, **1.5ms** per lookup, and **8.4s**
of a 15.4s import. The gap from the 33 MB prototype is entirely the two display
columns added during implementation: `display` (~18 MB) and `credit` (~8 MB) over
the ~26 MB MultiIndex. See "Two keys, two labels" below for why they are not
optional.

The naive scan is the shape `_crossover_run` already has, generalized. At 0.94s
per lookup it is a real regression on a modal that is currently fast, so it is
rejected.

The dict's microsecond lookup buys nothing a user can perceive over the
DataFrame's 0.53ms, and costs 3-4x the memory. The DataFrame wins.

The 10.7s build above includes re-reading the CSVs from disk. The app already
holds them in `CHART_DATA`, and `_primary_artist_col` (app.py:751) maps credits
over *uniques* rather than per row — an optimization the measurement did not
use. The real marginal build cost should land under 8s.

## Architecture

A new module, `chart_index.py`: pure functions, data in and data out, no Flask
and no module globals. `app.py` is already 2804 lines, and `versus.py` is the
existing precedent for primitives living outside it. The point is that the index
can be built and asserted against in a test without booting the app.

```
build(chart_data, chart_dt, charts_meta) -> DataFrame
lookup(index, title, artist, kind, exclude_chart) -> list[dict]
title_pool(index, kind, prefix) -> list[str]
```

### The index

One row per (title, artist, chart). 547,988 rows over 245,949 distinct
(title, artist) keys.

| column | type | notes |
|---|---|---|
| `title` | index level 0 | casefolded, stripped |
| `artist` | index level 1 | `primary_artist(credit)` |
| `chart` | category | registry key |
| `kind` | category | `song` / `album` |
| `peak` | int16 | min rank over the run |
| `weeks` | int16 | `nunique` of dates |
| `debut` | datetime | min date |

MultiIndex sorted at build time — an unsorted MultiIndex makes `.loc` fall back
to a scan, which would quietly hand back the 0.94s this design exists to avoid.

`app.py` builds `CHART_INDEX` at import from the already-loaded `CHART_DATA` and
`CHART_DT`, in the same startup pass as `CHART_DT` and `CHART_ARTISTS`
(app.py:640-663). That is the established pattern in this file for
precomputed per-chart structures.

Boot goes up by roughly 8s. `railway.json` sets no `healthcheckPath`, so Railway
waits for the port to bind rather than polling an endpoint — a slower import
delays the bind, it cannot fail a healthcheck.

### Matching rules

**The key is casefolded title plus `primary_artist(credit)`.** This is what
`_crossover_run` already does, and it is load-bearing: scraped artist casing
drifts week to week ("The Kid LAROI" vs "The Kid Laroi" — the 2026-07-01 bug),
and an exact-key join silently returns nothing. Building the key into the index
means the casefold cannot be forgotten at a call site, which is the failure mode
a per-call-site convention invites.

`primary_artist` and not `primary_credit`: `primary_artist` splits on commas and
is the grouping key, `primary_credit` preserves the full credit and is for
display. Grouping is what a join needs. This matches `_crossover_run` today.

**Kind-matched, symmetric.** A song looks up `kind='song'` charts; an album modal
looks up `kind='album'` charts. Charts with `kind='artist'` are excluded from
both — they carry no title to match.

The reason is that a cross-kind match is a coincidence rather than a fact. A
song called "1989" is not evidence about the album *1989*; reporting "also
charted on Top Album Sales" for it would be wrong, not merely noisy.

`kind` is read from the registry at build time. It is not counted or hardcoded
here: charts are declared across several structures (`CHARTS`, `BATCH_CHARTS`
and others), so any fixed count written into this document would be wrong by the
next batch.

**The origin chart is excluded from its own results.**

`/api/song-history` does not take a `kind` parameter. It already receives `chart`,
and `kind` is read from the registry for that chart — so a song modal opened on an
album chart searches album charts without the caller having to know anything. Only
the standalone search endpoints, which have no origin chart, take `kind` directly.

### Result rows

Chart, peak, weeks, debut — the shape `_crossover_run` already returns. Sorted
by peak ascending, then weeks descending.

The existing `later` flag is preserved and now computed for **every** result row,
not only the Bubbling Under pair: whether that run began after this one, which is
the difference between "reached the Hot 100" and "was already there." It is null
when the origin run has no usable debut date.

Charts differ in depth, from 10 to 200. A peak of 8 on a chart 10 deep does not
mean what a peak of 8 on the Hot 100 means. Not solved here; noted so that a
future reader knows it was seen and left alone.

## Components

1. **`_crossover_run` and `CROSSOVER_CHART` are deleted**, replaced by
   `chart_index.lookup`.

2. **`/api/song-history`'s `crossover` field changes from a single object to a
   list.** This is a breaking contract change with exactly one consumer,
   `templates/chart.html:696`, which changes in lockstep. Every song modal on
   every chart page gains an "Also charted on" section; album modals get the
   same against album charts.

3. **`/api/song-charts?song=&artist=&kind=`** — new, serving the search page
   from the same `lookup`.

4. **`/api/songs?q=&kind=`** — title autocomplete, mirroring `/api/artists`
   (app.py:1068). Serves `suggest`, not `title_pool` — see below.

6. **`/api/album-history` gains the same `crossover`/`crossover_ok` pair.** The
   Billboard 200 is the one album chart that does not render through
   `chart.html`; it has its own template and its own endpoint. Without this the
   flagship album chart would be the only one with no "also charted on".

5. **`search.html`** gains a title mode alongside its existing artist mode,
   rendering the same row shape.

## Two keys, two labels

Discovered in implementation, and it changed the API. `primary_artist` casefolds
AND drops featured acts: `'The Kid LAROI & Justin Bieber'` becomes
`'the kid laroi'`. That is correct for a join key and unusable as a label — a
search box offering "the kid laroi" reads as broken.

So the index carries both a key and a label on each axis: `title`/`display` and
`artist`/`credit`. A suggestion returns `credit` to show and `artist` to query
with.

This is also why `title_pool` alone could not serve the search box. The index is
keyed on (title, artist), and a bare title does not identify a record — "Hold On"
is Justin Bieber's and Wilson Phillips'. `suggest` returns pairs, ranked by how
many charts each reached.

## Error handling

**"Charted nowhere else" and "the lookup broke" must never render identically.**
This is the single most important rule here. That exact ambiguity is what let the
casefold bug hide: a join returning zero rows looked the same as a song that
genuinely never crossed over.

So the payload carries both: `{"crossover": [], "crossover_ok": true}` is "charted
nowhere else" and renders as that sentence. A lookup that could not run returns
`crossover_ok: false` and the UI renders an error, never the empty-state sentence.

Charts missing `Song`, `Rank` or `Date` are skipped at build time **with a logged
count**. A silent skip would shrink coverage invisibly, which is the same class
of bug as the row-floor truncations that have bitten this project before.

Blank-artist rows exist — Adult Contemporary has 20 — so credit mapping uses
`na_action='ignore'`, the precedent at app.py:2428. Without it, a `primary_artist`
that assumes a string raises during the build.

## Testing

`tests/test_chart_index.py`, built on small synthetic frames so the assertions
are readable and fast:

- casing drift across two charts still joins
- a song lookup returns no album charts, and an album lookup no song charts
- the origin chart is absent from its own results
- a miss is distinguishable from a failure
- a chart missing required columns is skipped and counted, not dropped silently
- **a characterization test pinning the current bubbling <-> top100 result.** The
  generalization must not regress the one pair that ships today. This is the test
  that makes deleting `_crossover_run` safe.

Plus route tests for `/api/song-charts` and `/api/songs`, and a test that
`/api/song-history` returns `crossover` as a list.

## Phasing

**Phase 1** — `chart_index.py`, `CHART_INDEX` at import, `_crossover_run`
deleted, `/api/song-history` returning a list, `chart.html` rendering it. This is
the whole capability behind one surface.

**Phase 2** — `/api/song-charts`, `/api/songs`, and the title mode in
`search.html`.
