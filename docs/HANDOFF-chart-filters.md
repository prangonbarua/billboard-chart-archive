# Handoff: chart row filters + Bubbling Under graduation

Requested 2026-08-03. **Both parts shipped 2026-08-03.**

## 1. Row filters: New / Re-entry / Growers / New peak — SHIPPED

Filter control on every chart page, plus a highlight for songs hitting a new
peak. Built in `_song_chart_page` (app.py), so all charts get it at once.

Decisions the user made before the build:

- **Grower = a climb of at least 5% of the chart's depth**, rounded up
  (`GROWER_PCT` in app.py). +5 on the Hot 100, +10 on the Global 200, +2 at
  depth 25. Measured against the depth actually served that week, not the
  registry depth, so Digital Song Sales' 50-to-25 seam in 2023-09 does not
  change what a climb means.
- **A debut is not a new peak.** `rank == peak` holds trivially on a first
  week; the tag requires the song to have charted before and beaten its own
  best (strict comparison against prior weeks only).

Two things came out of the build that are worth knowing:

- `/albums200` was running its own near-copy of `_song_chart_page` that stopped
  just short of the 2026-07-29 debut/peak fix, so Billboard 200 was still
  showing the corrupt stored `Last Week` / `Peak Position` values — 25 of 199
  rows had a wrong Peak on the 2010-06-05 week alone. It now shares the
  renderer, which fixes those values and gives it the filters.
- The eight duplicate chart templates (`hot100.html`, `global200.html`,
  `globalexus.html`, `radio.html`, `digital.html`, `streaming.html`,
  `pop_airplay.html`, `artist100.html`) collapsed into `chart.html`, the
  consolidation the 2026-07-30 design spec had already planned. The two
  artist-chart differences are now `chart.kind == 'artist'` conditionals. Per
  that spec's verification requirement, the old and new renders of `/top100`
  were diffed: the only differences are the intended ones.

Since the 2026-07-29 debut/peak fix it already computes `last_week`, `peak`,
and the change badge from real chart history (the `pair_ranks` map), **not**
the stored `Last Week` / `Peak Position` columns, which are corrupt in
pre-2025 rows. So nothing new needs scraping or storing:

| Filter   | Condition                                  | Status                |
|----------|--------------------------------------------|-----------------------|
| New      | `last_week is None`, never charted before   | badge already computed |
| Re-entry | `last_week is None`, charted before         | badge already computed |
| Growers  | `rank < last_week`                          | derive from existing   |
| New peak | `rank == peak`, first time reached          | `peak` already computed |

### Constraints (from prior sessions — do not relearn the hard way)

- **No emoji or glyphs anywhere.** Image placeholders are blank `#f5f5f3` SVG
  rects. This is a standing rule.
- **All animations and transitions are globally killed** in `static/paxel.css`
  (`*{animation:none;transition:none}!important`). A filter must not rely on
  transition-based reveals, and must not reintroduce base `opacity:0` rows —
  that pattern was deliberately removed because the animations that revealed
  it are gone.
- Palette: `#ffffff` / `#000000` / `#02ff9a` (bright green) / `#0c492c`
  (dark green). Sharp edges, `border-radius: 0`.
- Nav is built by looping the chart registry, so it cannot fall out of sync.

The shipped filter hides rows with `display`, never opacity, for exactly the
animation reason above. Tests are in `tests/test_routes.py`.

## 2. "Did this Bubbling Under song reach the Hot 100?" — SHIPPED

`_crossover_run` (app.py) returns the song's run on the paired chart, and
`/api/song-history` carries it as a `crossover` field. The history modal renders
one line under the stats: "Reached The Hot 100 on 2026-08-01 — peak #89, 1 week"
on a Bubbling Under entry, "Started on Bubbling Under Hot 100 on 2025-08-16 —
peak #1, 11 weeks" on the Hot 100 side. `CROSSOVER_CHART` maps the pairing;
every other chart returns null. The `later` flag is what separates "reached" from
"was already on".

The join casefolds Song and normalizes Artist through `primary_artist`, so
credit drift matches too. Numbers as of 2026-08-03: 12,468 distinct Bubbling
Under titles, 5,613 of them also on the Hot 100, 5,607 with the Hot 100 run
coming later. An exact-case join finds 5,534 — 79 fewer, which is the silent
failure the trap describes, scaled down.

**Do not read a zero on the current week as a broken join.** Bubbling Under only
lists songs that have never made the Hot 100, so the newest week legitimately
returns almost no graduations. Check a historical week, or the aggregate count
that `tests/test_routes.py` asserts (> 4,000), before concluding anything.

Residual risk is title variants — "feat." vs "Featuring", remix suffixes — which
casefolding cannot merge.

## Data state as of 2026-08-03

Both charts are live and validated:

- `data/dance_singles_sales.csv` — 54,952 rows / 1,144 weeks,
  1985-02-09 → 2007-02-24 (discontinued, frozen)
- `data/bubbling_under.csv` — 43,925 rows / 1,757 weeks,
  1992-12-05 → 2026-08-01 (current, joins the weekly scraper)

Neither is contiguous and that is correct. Dance is missing 7 year-end weeks
Billboard never published. Bubbling Under is complete through 2026-08-01;
2026-08-08 is simply next week's unpublished chart.

**Validating gaps:** an unpublished week's page has no `Week of` heading. A
0-row page alone is **not** proof — Billboard served empty pages for 7 real
weeks on 2026-08-02 that returned full data the next day. Those 7 have since
been recovered. Check the heading, not the row count.
