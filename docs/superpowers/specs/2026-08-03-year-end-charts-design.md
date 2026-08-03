# Year-End Charts

Add Billboard's year-end editions to every chart on the site that has one, as a
second view on the existing chart pages.

## Why this is not a routine chart addition

Every chart added so far was weekly: a CSV of `Date, Song, Artist, Rank, ...`
rows, a registry entry, a nav line. Year-end data breaks three of those
assumptions at once.

1. **There is no week.** A year-end row has a year, a rank, a title and an
   artist. `Last Week`, `Peak Position` and `Weeks on Chart` do not exist, so
   the badges, row filters and history modal built on them have nothing to
   read.
2. **Billboard fabricates missing years, and the page does not say so.** This
   is the important one, covered below.
3. **The data barely changes.** One new row set per chart per year, versus a
   weekly scrape.

## The fabrication problem

Billboard answers `/charts/year-end/<year>/<slug>/` for any year, including
years it has no chart for. The response is HTTP 200, well-formed, with a full
row count. It is the year-end analog of the weekly clamping that nearly put
1,760 fabricated weeks into `adult_rnb_airplay.csv`.

The weekly scraper defends itself by reading the page's own `Week of ...`
heading and rejecting any response whose served week differs from the
requested one. **That defence is unavailable here.** A year-end page carries no
year anywhere:

* no redirect, the URL keeps the requested year
* `<title>` is just the chart name, e.g. `Hot 100 Songs`
* `<link rel=canonical>` strips the year entirely, to
  `https://www.billboard.com/charts/year-end/hot-100-songs/`
* no `data-year`, no JSON-LD date, no visible heading

### What the data actually shows

A sweep of all 68 years of `hot-100-songs`, hashing each year's full
`(rank, title, artist)` ordering:

| Years | Rows | Signature | Verdict |
|---|---|---|---|
| 1958-1969 | 69 | identical to 1970 | fabricated |
| 1970 | 69 | unique | real |
| 1971-1990 | 65-90 | unique per year | real |
| 1991-2005 | 100 | identical to 2006 | fabricated |
| 2006-2025 | 99-100 | unique per year | real |

41 of 68 years are genuine. `/charts/year-end/2000/hot-100-songs/` returns the
2006 chart, led by Daniel Powter's "Bad Day".

Billboard clamps a missing year **forward** to the next year it holds. Both
fabricated ranges end at a real year, which yields the detection rule.

### Detection rule

> Within a run of consecutive years sharing one ranking signature, only the
> latest year is genuine. Every earlier year in the run is a clamped copy.

1991-2006 collapses to 2006; 1958-1970 collapses to 1970. Two genuinely
adjacent year-end charts are never identical, so the rule has no false
positives in practice.

This rule requires scanning every year for a chart before deciding any of
them. It cannot short-circuit on the first fabricated year, because a
fabricated run (1991-2005) can sit between two real ones.

## Data

One combined file, `data/yearend.csv`:

```
Chart, Year, Rank, Song, Artist, Image URL
```

`Chart` holds the existing registry key (`top100`, `albums200`, ...), so
year-end rows join the weekly charts by the key already in use.

One file rather than the established one-CSV-per-chart pattern, because the
whole dataset across all charts is smaller than one weekly CSV, every row has
the same shape with no per-chart column drift, and a single file lets the
scraper keep one resumable ledger over `(chart, year)` pairs. Loaded once at
startup into:

* `YEAREND_DATA`: `{chart_key: DataFrame}`, one `groupby`
* `YEAREND_YEARS`: `{chart_key: [int]}`, descending, real years only

Missing file means the feature is simply absent, matching how
`_load_global_chart` already tolerates missing weekly CSVs.

## Components

### scripts/yearend_slugs.json

Year-end slugs differ from weekly ones: `hot-100-songs` not `hot-100`,
`top-billboard-200-albums` not `billboard-200`. A discovery pass probes
candidates per registry chart and writes the mapping. Charts with no year-end
edition are recorded explicitly as absent, so a later run does not re-probe
them and nobody has to guess whether the chart was missed or does not exist.

### scripts/backfill_yearend.py

Separate from `backfill_chart.py`. The weekly script's guard compares a week
against its chronological predecessor; this one needs the signature-run rule
above, and `backfill_chart.py` has an open bug on sparse re-runs that this
should not inherit.

Per chart: fetch every year 1958-2025, hash each ordering, collapse runs, write
only surviving years. The log records every dropped year and the real year it
duplicated. Resumable over `(chart, year)`.

Note it must fetch all years even though most are discarded, since the rule
needs neighbours to judge a year.

### app.py

* Loader and the two dicts above.
* `_yearend_chart_page(chart_key, year)` beside `_song_chart_page`.
* Existing chart routes accept `?view=yearend&year=YYYY`.
  * absent or malformed `year`: newest real year for that chart
  * year not in that chart's real list: flash and redirect, never render, so a
    link to a fabricated year cannot produce a page

No new routes, no new nav entries, no change to the registry.

### templates/chart.html

Gains `mode`, defaulting to `weekly`. Under `mode='yearend'` it hides the Last
Week / Peak / Weeks columns, the New / Re-entry / Growers / New-peak filters,
the prev/next week buttons and the song-history modal, and swaps the week
picker for a year picker.

The picker lists real years only, so the Hot 100 jumps 1990 to 2006. The page
states plainly that Billboard publishes no year-end archive for the gap, the
same way weekly gaps are already treated as real rather than hidden.

## Out of scope

`versus.py`, `/analyze` and its coverage table, `/api/artist-chart`, all CSV
exports, the weekly scraper and the nav are untouched. Year-end ranks are not
comparable to weekly ranks on one axis, and mixing them would muddy the
all-charts artist report shipped 2026-08-02.

Year-end is excluded from the weekly CI job, since these charts change once a
year. Refresh is a manual run each January.

## Testing

* **Guard unit test.** A fixture reproducing the forward clamp: years
  1998-2001 where 1998, 1999 and 2000 all return 2001's ranking. Asserts only
  2001 survives. This is the regression that matters most.
* **Boundary test.** A fabricated run between two real runs, mirroring the
  1990 / 1991-2005 / 2006 shape, asserting both real boundary years survive and
  the middle run does not.
* **Loader test.** No year outside `YEAREND_YEARS` reaches `YEAREND_DATA`.
* **Route tests.** `?view=yearend` with no year renders the newest real year;
  an unreal year redirects rather than rendering.

## Success criteria

1. Every chart with a year-end edition is browsable at every genuine year.
2. No fabricated year is reachable, in the CSV or through a URL.
3. Weekly pages behave exactly as before.
4. The dropped years are documented in the run log, so a future session can
   tell a real gap from a scrape failure without re-deriving any of this.
