# Genre Airplay Charts & Artist Versus — Design

Date: 2026-07-30
Status: approved design, pending implementation plan

## Goal

Two features:

1. Add five genre/format airplay charts with full history.
2. Add an artist-vs-artist comparison page ("versus") scoped to a selected chart.

## Non-goals

- Song-vs-song comparison. Artist comparison only.
- Cross-chart aggregate stats. Each comparison is scoped to one chart.
- Any invented "chart power" composite metric.
- Reworking `billboard200.html` unless it proves to be a near-duplicate of the song templates.

## Current state

The app is a single Flask file (`app.py`, 1623 lines) serving nine chart pages from nine CSVs in `data/`. Each chart is four things: a CSV, one `_load_global_chart()` call, one route, and one ~38KB template.

The eight song-chart templates differ from each other by 20 diff lines out of ~900 — `<title>`, which nav anchor carries `class="active"`, the `<h1>`, and a `chart=` query param. `artist100.html` differs by 36 lines: the same four, plus it omits the `.song-artist` subtitle div and calls `/api/artist-image/` instead of `/api/song-image/`.

Nav is a flat 10-item list, hardcoded identically in every template. The cost of this is measurable: commit `cd05690`, which added the single Pop Airplay chart, had to touch **11 template files** to do it — one line in each, purely to add the nav link.

There is no graph rendering in the app. `results.html:643` assigns `chartData` from `prepare_visualization_data()` and never reads it; the `.chart-wrap canvas` rule at `results.html:222` is vestigial. No external script tags exist anywhere in the project.

There is no test suite.

`/` redirects to `/top100`, so the Hot 100 page is the de facto landing page. `templates/index.html` no longer exists.

## Part 1 — Chart registry

Replace the per-chart copy-paste with one source of truth in `app.py`:

```python
CHARTS = {
  'top100': dict(
      label='The Hot 100', csv='hot100.csv', bb_slug='hot-100',
      depth=100, kind='song', nav='Songs',
      subtitle='Ranked by streaming, airplay & sales'),
  'country_airplay': dict(
      label='Country Airplay', csv='country_airplay.csv', bb_slug='country-airplay',
      depth=60, kind='song', nav='Airplay',
      subtitle='Ranked by country radio airplay audience'),
  # ... one entry per chart
}
```

Field meanings:

| Field | Use |
|---|---|
| dict key | Flask endpoint name and URL path; must match today's names |
| `label` | nav text, `<title>`, `<h1>` |
| `csv` | filename under `data/` |
| `bb_slug` | Billboard URL slug for the scraper |
| `depth` | chart size; drives scraper expected-count and the validity threshold |
| `kind` | `'song'` or `'artist'`; drives the two artist-chart template flags |
| `nav` | nav group: `Songs`, `Airplay`, or `Albums & Artists` |
| `subtitle` | `.page-meta` text |

### Data loading

The seven `_load_global_chart()` calls at `app.py:138-144` become a loop populating `CHART_DATA[key] = {'df': df, 'dates': [...], 'dt': parsed_dates}`.

Hot 100 keeps its `find_data_file()` path with the Desktop fallback (`app.py:69-89`) — that quirk is preserved, just isolated to one registry entry.

**Dates are parsed once at load** into a `dt` series stored alongside the frame. Today every request calls `pd.to_datetime` over the full column; the versus feature would multiply that per artist. This change benefits every existing page too.

### Routes

Endpoint names must not change — `about.html`, `search.html`, and `results.html` all call `url_for('top100')`, `url_for('radio')`, etc., and the nav does too.

Register in a loop with `add_url_rule`, binding the loop variable as a default argument:

```python
for key in CHARTS:
    app.add_url_rule(f'/{key}', key,
                     limiter.exempt(lambda k=key: _chart_page(k)))
```

The `k=key` default binding is required. Without it, Python's late closure binding makes all 14 routes serve whichever chart was last in the loop — a failure that renders correctly and is easy to miss.

`albums200` keeps its bespoke route body (`app.py:1270+`), which does not use `_song_chart_page`.

### One template

The eight song templates plus `artist100.html` collapse into `templates/chart.html`, receiving the chart's registry dict. The two artist-chart differences become conditionals on `chart.kind == 'artist'`.

Nav becomes a loop over `CHARTS` grouped by `nav`, with the active class derived from `request.endpoint` — so it cannot drift out of sync.

### Nav grouping

The current nav is already at its limit: at 9 items the labels wrap to two lines
and reach the right edge of the viewport. Adding five more inline is not
possible, and grouping them inline does not help enough.

So the whole chart list moves into **one dropdown**. The bar becomes three items:

- **Charts ▾** — a single trigger opening a panel with all 14 charts in labeled
  sections: *Songs* (Hot 100, Global 200, Global Excl. US, Radio, Digital,
  Streaming) · *Airplay* (Pop, Adult Pop, Adult Contemporary, Rhythmic, Country,
  Alternative) · *Albums & Artists* (Billboard 200, Artist 100)
- **Versus** — top-level
- **Reports** — top-level

The trigger shows the current chart's name when one is active, so the nav still
says where you are. The panel is built by looping the registry grouped by `nav`,
so it cannot drift.

### Landing page note

Collapsing `hot100.html` touches the de facto landing page. Verification requirement: capture the rendered HTML of `/top100` before and after the refactor and diff them. The only acceptable differences are the nav restructure.

## Part 2 — The five new charts

All five slugs were verified live against Billboard for week 2024-06-01:

| Chart | Slug | Depth | Verified #1 (2024-06-01) |
|---|---|---|---|
| Adult Contemporary | `adult-contemporary` | 30 | Flowers — Miley Cyrus |
| Adult Pop Airplay | `adult-pop-songs` | 40 | Beautiful Things — Benson Boone |
| Rhythmic Airplay | `rhythmic-40` | 40 | Like That — Future, Metro Boomin & Kendrick Lamar |
| Country Airplay | `country-airplay` | 60 | Where It Ends — Bailey Zimmerman |
| Alternative Airplay | `alternative-airplay` | 40 | Dilemma — Green Day |

Add all five to the expected-count map at `fast_billboard_scraper.py:119`, which currently knows only `artist-100` and `pop-songs` and defaults everything else to 20.

### Scrape plan

Five detached background processes in parallel, reusing the Pop Airplay backfill pattern, which is already resumable: read the existing CSV, compute the missing week list, retry each week 3 times with backoff, checkpoint to disk every 25 weeks, and report a fail list at the end.

One change from the Pop run: it hardcoded `len(entries) >= 30` as its validity test. That is too lax for Country Airplay's 60 rows and exactly borderline for Adult Contemporary's 30. Use per-chart `min_entries = int(depth * 0.75)`.

### The clamping hazard

This was the most important finding of the design phase, and it invalidates the
obvious approach.

Billboard serves **any** out-of-range date — before a chart launched, or after its
newest week — by returning the boundary week's rankings under whatever date was
requested. There is no redirect (the final URL equals the requested date) and no
date anywhere in the page: `c-tagline`, which `fast_billboard_scraper.py:45`
inspects, holds the chart's *description*, not its date. Lines 50 and 52 of that
file are identical, so the located element is never used and rows are always
labelled with the requested date.

Consequence: a single response cannot reveal that a week is fabricated. Guessing
start dates and letting failures reveal the boundary does not work, because
out-of-range dates do not fail — they return a full, valid-looking chart.

Two mitigations, both implemented:

1. **`scripts/find_chart_start.py`** binary-searches each chart's true first week
   as the latest date whose full ranking still matches a known pre-launch date.
   Verified: all dates from 1950 through 1990-01-20 return one identical
   `country-airplay` ranking, so the clamped region is contiguous and the search
   is sound.
2. **`scripts/backfill_chart.py`** drops any week whose full
   `(rank, song, artist)` ordering matches the adjacent accepted week. Real
   consecutive weeks always differ. This guards the future end too, where dates
   past the newest chart clamp to it.

Note the guard's limit: it compares against the *previous accepted* week, so the
very first week of a run is accepted unconditionally. Starting at a wrong date
would still write one bad week — which is why step 1 is not optional.

A matching #1 is **not** evidence of a clamped week; a song can hold #1 for many
weeks. Only the full ranking signature settles it.

### Verified launch weeks

Determined empirically, not from published chart histories:

| Chart | True first week | Rows at launch | Weeks to fetch |
|---|---|---|---|
| Adult Contemporary | 1961-07-15 | 20 | 3,395 |
| Alternative Airplay | 1988-09-10 | 30 | 1,978 |
| Country Airplay | 1990-01-20 | 60 | 1,907 |
| Rhythmic Airplay | 1992-10-03 | 40 | 1,766 |
| Adult Pop Airplay | 1995-10-07 | 40 | 1,609 |

10,655 weeks total; roughly 3 hours wall clock in parallel, bounded by Adult
Contemporary.

Adult Pop Airplay begins **1995-10-07**, not March 1996 as commonly published.
Trusting the published date would have written 22 weeks of clamped duplicates.

### Chart depths changed over time

Adult Contemporary was a 20-position chart in 1961; Alternative Airplay was 30 in
1988. Both are deeper today. So the completeness gate at
`fast_billboard_scraper.py:117` uses a **floor of 20** for these five charts
rather than their modern depth — setting it to the modern depth silently rejects
every early week as "incomplete". Truncated-but-not-short weeks are caught by the
duplicate-ranking check instead.

The registry's `depth` field therefore describes the chart's *current* depth, for
y-axis scaling and display, and must not be reused as a scrape validity
threshold.

### Weekly updates

Add all five to `auto_update_data.py`, matching the existing calls at lines 252-256, so they refresh with everything else.

## Part 3 — Artist versus

### URL

`GET /versus?chart=top100&artists=Taylor+Swift|Drake|Morgan+Wallen`

All state in the URL: comparisons are shareable and browser back/forward works. Missing or empty `artists` renders the picker. Unlimited artists — no cap.

### API

`GET /api/versus?chart=<key>&artists=<pipe-separated>`

Per artist:

- `display_name` — modal capitalization from the data
- `entries` — unique songs
- `number_ones`, `weeks_at_1`
- `top_10s`, `top_40s`
- `best_peak`, `total_weeks_charted`
- `first_entry`, `last_entry`
- `biggest_hit` — best peak, ties broken by weeks on chart
- `timeline` — `[{date, rank}]`, the artist's best rank in each week they charted

Unknown artist returns a null-stats entry rather than an error, so one typo in a four-artist comparison doesn't blank the page.

### Correctness constraints

These are all lessons already paid for in this repo's history. Violating any of them produces plausible, wrong numbers.

1. **Compute peak from the Rank history. Never read the `Peak Position` column.** Commit `f1cb2ad` established the stored `Peak Position` / `Last Week` columns are corrupt — they showed a false #1 peak on every chart.
2. **Key songs by `(song_lower, primary_artist(credit))`.** Commits `e78a0dd` and `6166ed4`: mid-run credit changes otherwise split one hit into two entries and truncate its run.
3. **Match artists with `artist_match_mask()` (`app.py:164`), not substring.** Commit `127a996`: substring matching pulls "Tyla Yaweh" into a search for "Tyla".
4. **Dedupe on `(Date, Rank)` before counting.** Duplicate scrape rows otherwise inflate every week and entry total.

`weeks_at_1` is the count of that artist's rows at Rank 1 after dedupe — only one song holds #1 per week, so no further collapsing is needed.

### Autocomplete

`MODERN_ARTISTS` (`app.py:116`) is built from Hot 100 data filtered to 1990+. That fails this feature twice: a country act who never crossed to the Hot 100 would never autocomplete on Country Airplay, and Adult Contemporary reaches back to 1961.

`/api/artists` gains a `chart` param and builds its pool from the selected chart. Pools are computed once per chart at load, matching how `MODERN_ARTISTS` is precomputed today.

### Graph

Hand-rolled inline SVG. No external dependency — consistent with the project having no script tags today, and it inherits the SF Pro / Paxel styling directly.

- X axis: calendar time, spanning the union of all artists' chart spans
- Y axis: rank, **inverted** — #1 at the top; scaled to the chart's `depth`
- One polyline per artist from `timeline`
- Cycling palette; hover a legend entry or line to isolate it and dim the rest
- Gaps: weeks where an artist did not chart break the line rather than interpolating across the gap, which would imply chart presence that did not exist

### Scorecard

Stats as rows, artists as columns. Best value in each row accented. The table wraps in `overflow-x: auto` so many artists scroll horizontally instead of crushing the layout.

### Performance

Each artist costs one `artist_match_mask` scan plus two groupbys over a frame up to ~350k rows. Parsing dates at load (Part 1) removes the dominant per-request cost. With that done, the practical ceiling on artist count is browser rendering of the SVG, not the server.

## Verification

No test suite exists, so verification is explicit:

1. **`scripts/verify_charts.py`** — per chart, assert: no duplicate `(Date, Rank)`; no missing weeks in the date sequence; dates parse and are monotonic; and **no two consecutive weeks share an identical full ranking**, which is the post-hoc check for clamped weeks that slipped past the backfill guard. Row counts are checked for plausibility only, not against `depth`, since depths changed over time. Run against all 14 charts.
2. **Landing-page diff** — rendered HTML of `/top100` before vs after the template collapse; only the nav restructure may differ.
3. **Every route loads** — walk all 14 endpoints plus `/versus` and assert HTTP 200, guarding against the closure late-binding bug.
4. **Versus numbers hand-checked** — pick two well-documented artists and reconcile `number_ones`, `weeks_at_1`, and `entries` against Billboard's published totals. Silently-wrong stats are this feature's main risk.

## Risks

| Risk | Mitigation |
|---|---|
| Closure late-binding makes all routes serve one chart | Default-arg binding; route walk test |
| Template collapse changes the landing page | Before/after rendered HTML diff |
| Scrape start dates guessed too early | Conservative start; read true first week off the fail list |
| Wrong versus stats look plausible | Hand-reconcile against Billboard's published totals |
| `billboard200.html` has diverged more than assumed | Diff it first; leave it on its own template if so |

## Sequencing

1. Launch the five scrapes in the background. (Pop Airplay is done and already committed in `cd05690` — 1,766 weeks, 1992-10-03 → 2026-08-01, working tree clean.)
2. Build the registry and collapse the templates while scraping runs.
3. Add the five registry entries and nav grouping.
4. Build `/api/versus`, then the versus page.
5. Run all four verifications.
