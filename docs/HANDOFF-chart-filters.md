# Handoff: chart row filters + Bubbling Under graduation

Requested 2026-08-03. Not started. Two features, both cheaper than they look
because the data already exists.

## 1. Row filters: New / Re-entry / Growers / New peak

Add a filter control to the chart pages, plus a visual highlight for songs
hitting a new peak.

**Build it in `_song_chart_page` (app.py).** That is the shared renderer for
all 19 charts — one change covers every chart instead of 19 template edits.

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

### Two decisions to make first

1. **Grower threshold.** Any improvement, or 5+ positions? Chart depth ranges
   from 25 to 200, so "moved up 3" means something very different on
   Bubbling Under than on the Billboard 200. A percentage of depth may be
   better than a flat number.
2. **Does a debut count as a new peak?** A debut satisfies `rank == peak`
   trivially, so counting it lights up most of the lower chart and makes the
   highlight meaningless. Probably exclude debuts, or style them differently.

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
