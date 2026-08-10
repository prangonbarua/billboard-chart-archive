# Adding charts 22-31 — measured facts

Written 2026-08-09. Everything below was measured against billboard.com, not
assumed. Read this before starting or resuming any of these backfills.

## Three charts that CANNOT be added

Requested, probed thoroughly, and unavailable. Do not re-derive.

| Chart | Finding |
|---|---|
| **Pop 100** (2005-2009) | 7 slug variants x 2 in-run dates, all 404 |
| **Hot 100 Recurrents** | 6 variants 404. Billboard's own slug `hot-singles-recurrents` also 404s on www; `assets.billboard.com` is dead (expired cert, 503) |
| **European Hot 100 Singles** (1984-2010) | Weekly URL redirects to `/charts/year-end/...` — the reverse-redirect trap. No weekly archive |

**The European year-end is a trap too.** Every year 1984-2008 returns the SAME
10 rows (identical md5) and the content is 2009 music — #1 "When Love Takes
Over". 2009-2011 return 0 rows. Billboard holds one 10-row list filed under the
wrong year. Note this **breaks the consecutive-signature rule** in
`yearend_guard.py`: that rule names 2008 genuine, but the whole run is fake. The
rule assumes a fake run sits between two real years; here there is no real year.

## How a real page is distinguished from a fake one

Control: `hot-dance-singles-sales` @ 2000-01-08 → 200, **~2.0 MB**, 55 rows,
heading `Week of January 8, 2000` matching the requested date. A 404 is
**~715 KB**. Discontinued charts are absent from the `/charts/` index (133
slugs, all current) yet their dated URLs still work — **absence from the index
proves nothing**, only a dated fetch does.

## The ten that CAN be added — all verified real

Labels are Billboard's own `<h1>`, not guesses (`rock-songs` is *not* "Rock
Songs"). Depth is the CURRENT row count. First week from
`scripts/find_chart_start.py`.

| slug | label | first week | depth | weeks | est. |
|---|---|---|---|---|---|
| `dance-electronic-songs` | Hot Dance/Electronic Songs | 2014-03-22 | 25 | 646 | 2.0h |
| `japan-hot-100` | Billboard Japan Hot 100 | 2011-04-09 | 25 | 800 | 2.4h |
| `official-uk-songs` | The Official U.K. Singles Chart | 2011-01-29 | 20 | 810 | 2.5h |
| `rock-songs` | Hot Rock & Alternative Songs | 2009-06-20 | 50 | 894 | 2.7h |
| `gospel-songs` | Hot Gospel Songs | 2005-03-19 | 25 | 1116 | 3.4h |
| `christian-songs` | Hot Christian Songs | 2003-06-21 | 50 | 1207 | 3.7h |
| `top-album-sales` | Top Album Sales | 1991-05-25 | 50 | 1837 | 5.6h |
| `latin-songs` | Hot Latin Songs | 1986-09-06 | 50 | 2083 | 6.4h |
| `country-songs` | Hot Country Songs | 1958-10-18 | 50 | 3538 | 10.8h |
| `r-b-hip-hop-songs` | Hot R&B/Hip-Hop Songs | 1958-10-18 | 50 | 3538 | 10.8h |

**Total ~16,470 weeks.** The 11s/week figure from the Canadian Hot 100 backfill
turned out to be far too pessimistic: Dance/Electronic did 647 weeks in about
20 minutes, i.e. **~2s/week, so the whole set is closer to 9 hours than 50.**
The per-chart hour estimates in the table above are the old pessimistic ones —
divide by roughly five.

None of these keys collide with the existing 21. The existing `country_airplay`
and `rnb_hiphop` are the AIRPLAY charts; these are the consumption charts and
are genuinely different data.

### First weeks that still need a second look

`find_chart_start.py` reports the row count of the clamp page, and three came
back implausibly shallow: **latin-songs "1 rows at launch"**, and japan-hot-100
/ official-uk-songs at "10 rows". Verify the first week directly (fetch it and
the week before, confirm distinct rankings) before trusting those three dates.
The other seven look ordinary.

## Wiring order — DATA FIRST, this is not optional

`tests/test_routes.py::test_every_chart_route_returns_200` iterates the whole
registry and requires 200. A registered chart whose CSV is missing flashes and
**302s**, so registering ahead of data turns the suite red. Backfill the CSV,
then wire that one chart.

Per chart, wiring is five edits:

1. `app.py` — a `_load_global_chart('<name>.csv')` line near the other loaders
2. `app.py` — a `CHARTS` registry entry (label / group / depth / kind)
3. `app.py` — a `CHART_DATA` entry
4. `app.py` — add the key to the route-loop tuple (~line 1853). The `key=key`
   default argument is what stops late binding serving one chart everywhere
5. `scripts/fast_billboard_scraper.py` — an `update_chart_data(...)` line, plus
   a row-count guard entry in the depth dict (~line 160)

`top-album-sales` is `kind='album'` and belongs in the `Albums & Artists` group;
the other nine are `kind='song'` in `Songs`.

`scripts/verify_charts.py` loops `app.CHARTS`, so each new chart is checked
automatically — expect genuine publication gaps to need
`known_clamped_weeks.json` entries, the same triage the other charts needed.

## Status

- **dance-electronic-songs: DONE and SHIPPED** as chart 22 (commit 3fb69fa).
  30,300 rows / 647 weeks, 2014-03-22 to current, zero gaps, verify_charts
  clean. Wired and 139 tests pass.
- **japan-hot-100**: backfill running 2026-08-09 to `data/japan_hot100.csv`.
  Not wired yet. **After it completes, raise its floor in
  `fast_billboard_scraper.py` from the backfill value 10 to the modern 25.**
- The other eight: not started. Agreed order is cheapest-first — UK, Rock,
  Gospel, Christian, then Top Album Sales, Latin, and the two 1958 charts.

### The three suspect first weeks are now CONFIRMED (2026-08-09)

latin-songs 1986-09-06, japan-hot-100 2011-04-09 and official-uk-songs
2011-01-29 are all correct. For each, the week BEFORE serves that first week's
own content under the first week's date — the pre-launch clamp — and the week
after has a distinct signature. The shallow row counts are real launch depths,
not artifacts: Japan and the UK chart launched at 10 rows, and Hot Latin Songs
genuinely serves **1 row** per week in 1986. Latin will therefore need a floor
of 1 to backfill, and that floor must be raised afterwards.

**Do NOT re-run `backfill_chart.py` over a partly-filled CSV to retry scattered
stragglers** — the known `prev_sig` bug fabricates weeks. A retry is only safe
when the missing weeks are one contiguous block after a present week.
