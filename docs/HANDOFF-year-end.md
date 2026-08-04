# Year-end charts

`data/yearend.csv` holds Billboard's year-end editions for the 18 registered
charts that have one. Columns are `Chart, Year, Rank, Song, Artist, Image URL`.
29,164 rows. Scraped 2026-08-04 with `scripts/backfill_yearend.py`.

Read this before adding a year, filling a gap, or deciding a chart is missing
data. Almost every gap below is Billboard's, not ours, and the ways this source
lies are not the ways the weekly scraper's guards catch.

## Billboard fabricates year-end pages in three different ways

None of the three returns an error. All three return HTTP 200 with clean markup
and a full row count, and **no year-end page states its year anywhere** — there
is no redirect, the URL keeps whatever year you asked for, `<title>` is just the
chart name, and `<link rel=canonical>` strips the year entirely. The weekly
scraper's "Week of ..." served-week check has no year-end equivalent, so every
guard here works by comparing pages against each other.

**1. Forward year clamp.** A year Billboard does not hold is answered with the
next year it does. `/charts/year-end/2000/hot-100-songs/` returns the real 2006
chart, led by Daniel Powter's "Bad Day". Detection: within a run of
*consecutive* years sharing one ranking signature, only the **latest** is
genuine. This is why the scraper fetches every year even though it throws most
away — the rule needs neighbours — and why it must not early-exit on the first
fake year, since a fabricated run sits between two real ones.

**2. Weekly fall-through.** A slug with no year-end edition is not a 404. It
returns the **current weekly chart** at full depth, for any year asked.
`/charts/year-end/2024/adult-contemporary/` is byte-identical to
`/charts/adult-contemporary/`. This is the dangerous one: a row-count test
accepts it, every year looks identical, and rule 1 would then keep the latest
year and store one arbitrary week as a year of chart history. Detection: fetch
the chart's own weekly page once and exclude its signature by name. Six of this
project's charts hit this path.

**3. Reverse redirect on year-end-only slugs.** The inverse of 2, and it bites
the fix for 2. A slug that exists *only* as a year-end chart has no weekly page,
and asking for one redirects to the latest year-end chart:
`/charts/hot-100-songs/` settles at `/charts/year-end/hot-100-songs/`. Taking
that as the "weekly reference" drops the newest year of every such chart — it
cost the Hot 100 its 2025 edition on the first run. Detection:
`is_weekly_url()` rejects any reference that settles on a `/year-end/` URL. A
slug with no weekly page cannot fall through to one, so there is nothing to
compare against and the guard correctly does nothing.

`scripts/yearend_guard.py` implements 1 and 2; `is_weekly_url` in
`scripts/backfill_yearend.py` implements 3. All three are covered by tests in
`tests/test_yearend_guard.py` and `tests/test_backfill_yearend.py`.

## The slug map

`scripts/yearend_slugs.json`, produced by `scripts/discover_yearend_slugs.py`.
Year-end slugs are not weekly slugs and cannot be guessed from the label.

Four charts have a year-end edition under a slug that is **not** the obvious
one, because the obvious one is the weekly slug and falls through: `digital` is
`digital-songs` (not `digital-song-sales`), `adult_contemporary` is
`adult-contemporary-songs`, `country_airplay` is `country-airplay-songs`,
`alternative` is `alternative-songs`.

**Three charts have no year-end edition at all** and are recorded as `null`:
`rnb_hiphop`, `heatseekers`, `bubbling`. Each has a plausible near miss that a
row count accepts, so do not "fix" them:

- `rnb_hiphop` — `r-and-b-hip-hop-airplay` returns 10 rows of **artists**, not
  songs. `hot-r-and-b-hip-hop-songs` returns a mixed-decade list sharing no
  titles with any single year's weekly data.
- `heatseekers`, `bubbling` — every candidate falls through to the weekly chart.

A slug is accepted only if it returns 200, parses to at least 10 rows, is not
the weekly page, **and** its top 10 for a probe year appear in that chart's own
weekly CSV for the same year. The last check is what caught `rnb_hiphop`; row
count alone passes it.

## What is in the file

| Chart | Years | Range | Rows |
|---|---|---|---|
| adult_contemporary | 40 | 1970-2025 | 1806 |
| adult_pop | 20 | 2006-2025 | 969 |
| adult_rnb | 20 | 2006-2025 | 958 |
| albums200 | 55 | 1970-2025 | 7997 |
| alternative | 23 | 1988-2025 | 1022 |
| canadian_hot100 | 18 | 2008-2025 | 1798 |
| country_airplay | 13 | 2013-2025 | 780 |
| dance_airplay | 20 | 2006-2025 | 870 |
| dance_sales | 14 | 1985-2013 | 136 |
| digital | 20 | 2006-2025 | 500 |
| global200 | 5 | 2021-2025 | 1000 |
| globalexus | 5 | 2021-2025 | 1000 |
| pop_airplay | 18 | 2008-2025 | 878 |
| radio | 20 | 2006-2025 | 1499 |
| rhythmic | 20 | 2006-2025 | 954 |
| streaming | 13 | 2013-2025 | 975 |
| top100 | 41 | 1970-2025 | 3753 |
| artist100 | 30 | 1979-2025 | 2269 |

## Gaps, and which ones are real

**1991-2005 is missing from every chart old enough to have it** — top100,
adult_contemporary, alternative, artist100, dance_sales. That is a hole in
Billboard's own year-end archive, not a scrape failure, and it is why those
fifteen years clamp forward to 2006 on every one of those charts. The Hot 100
sweep recorded in the design spec found the same boundary independently.

Other gaps: `adult_contemporary` also lacks 2010, `albums200` lacks 1984,
`artist100` lacks 1980 and 1989. Each is a single year that clamped to its
successor.

**Charts whose year-end history starts later than their weekly history** are
not missing data: `canadian_hot100` weekly starts 2007-03-31 but year-end
starts 2008, `pop_airplay` weekly starts 1992 but year-end starts 2008.
Billboard simply did not publish year-end editions that far back.

Two entries worth knowing about before treating them as bugs:

- **`artist100` year-end reaches back to 1979**, though the weekly Artist 100
  only launched in 2014. The year-end slug `top-artists` is Billboard's
  long-running year-end artists ranking, which predates the weekly chart. It is
  real data; it is just not a year-end edition *of the weekly Artist 100*.
- **`dance_sales` year-end runs to 2013**, though the weekly Dance Singles Sales
  data in `data/dance_singles_sales.csv` stops at 2007-02-24. Only about ten
  rows survive per year. Both facts come straight from the source.

## Billboard's older pages are themselves incomplete

Pre-1991 year-end pages serve fewer rows than the chart is deep, with scattered
ranks simply absent from the HTML. **1980 on the Hot 100 serves 83 of 100 rows
and omits ranks 1 and 2 outright** — the real 1980 year-end #1, Blondie's "Call
Me", does not appear anywhere in the page source. Missing ranks that year: 1, 2,
7, 9, 14, 19, 24, 29, 31, 37, 38, 51, 64, 67, 84, 88, 100.

This is stable across repeated fetches and across User-Agent and Accept header
variations, so it is Billboard's archive, not a parse or transport problem.
Neighbouring years are short by similar amounts (1978: 84 rows, 1979: 88, 1981:
88, 1982: 90). The rows are not recoverable from this source and are left out
rather than filled in. A year-end page rendering with a gap at #1 is expected.

## Re-running

    python3 scripts/backfill_yearend.py              # every chart
    python3 scripts/backfill_yearend.py top100       # one chart

Safe to re-run: it checkpoints after each chart and de-duplicates on
`(Chart, Year, Rank)` keeping the newest, and unlike `scripts/backfill_chart.py`
it holds no cross-run state that a sparse re-run can corrupt. A full run takes
roughly an hour; each chart is 68 fetches whatever its real range.

Verify the Hot 100 afterwards — it is the chart with a known-good answer:

    python3 -c "
    import pandas as pd
    df = pd.read_csv('data/yearend.csv')
    t = df[(df.Chart=='top100') & (df.Rank==1)].set_index('Year')['Song']
    assert t.get(1970) == 'Bridge Over Troubled Water'
    assert t.get(2006) == 'Bad Day'
    assert t.get(2025) == 'Die With A Smile'
    assert not any(y in t.index for y in range(1991, 2006))
    print('ok')
    "

Note 1980 has no rank 1, so do not add it to that check.
