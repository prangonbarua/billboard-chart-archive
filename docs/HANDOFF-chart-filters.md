# Handoff: chart row filters + Bubbling Under graduation

Requested 2026-08-03. **Part 1 shipped 2026-08-03. Part 2 is still open.**

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

## 2. "Did this Bubbling Under song reach the Hot 100?"

On click, show whether a Bubbling Under entry later charted on the Hot 100 —
ideally its Hot 100 debut date and peak. The inverse is worth offering too: on
a Hot 100 song, show whether it started on Bubbling Under.

Both CSVs are already loaded in the same process, and the click path exists
(`showSongHistory` → `/api/song-history?chart=`). It is a lookup of the same
song in the Hot 100 data.

### The trap

**Casefold both fields on the join.** Scraped artist casing drifts week to
week ("The Kid LAROI" vs "The Kid Laroi") — this is exactly what the
2026-07-01 fix addressed, where exact-key lookups silently broke. A
cross-chart join without `.casefold()` on **both** Song and Artist will drop
real graduations and look like the feature simply found nothing.

Residual risk after casefolding is title variants — "feat." vs "Featuring",
parenthetical mixes, remix suffixes. Spot-check a handful of known
graduations before trusting the numbers, and consider reporting a match count
so a silent zero is obvious.

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
