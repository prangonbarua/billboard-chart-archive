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

### Rolling Stone Top 100 — measured 2026-08-10, NOT addable

Requested and probed to exhaustion. It is not a Billboard chart: it ran on
rollingstone.com/charts, compiled by Alpha Data, so nothing in this repo
reaches it. It ran mid-2019 into **2022**, a year longer than it is usually
remembered.

| Source | Finding |
|---|---|
| `rollingstone.com/charts/*` | 200 but redirects to a generic `/music/` page. All variants return an identical 517 KB, so it is one landing page. **A row count would accept this** — same shape as the European trap below |
| Dated URLs on the live site | 404 |
| `api.alphadata.fm` | connect timeout; `alphadata.fm` unreachable |
| Wayback `/charts/songs/` | alive: 1,145 daily snapshots, 104 distinct weeks of ~183 (2019: 8, 2020: 53, 2021: 43) |

**The blocker: every archived page holds ranks 1-15 only.** Weekly, the 283
archived dated URLs, and the year-end pages all carry `data-results-per="15"`.
Ranks 16-100 loaded through `wp-admin/admin-ajax.php` in batches of 15, and the
only admin-ajax responses Wayback kept are `google-get-comments`. The markup
itself is clean and parseable — `section.c-chart__table--single` with rank,
title, artist, label and stream counts — so this is not a parsing problem. The
data was never archived.

**The dated URLs lie.** `/charts/songs/2018-07-06/` serves "Hot Girl Summer"
and "Señorita", which are August 2019, and `/charts/songs/2019-01-24/` serves
the same mid-2019 chart. The page ignored the date in the URL and returned
whatever was current when the snapshot was taken. Only the Wayback timestamp
dates a snapshot. Do not treat the 283 dated URLs as 283 distinct weeks.

A Rolling Stone **Top 15** covering ~57% of weeks is buildable from Wayback and
would need a new scraper; it would be the only non-Billboard chart on the site.
That is a different chart from the one requested and has not been built.

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
| `country-songs` | Hot Country Songs | **1958-10-20** | 50 | 3539 | 10.8h |
| `r-b-hip-hop-songs` | Hot R&B/Hip-Hop Songs | **1958-10-20** | 50 | 3478 | 10.8h |

The two 1958 first weeks are corrected from the 1958-10-18 this table used to
carry — see the dating section below. `find_chart_start.py` only ever tries
Saturdays, so it named the Saturday nearest a Monday-dated launch.

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
- **japan-hot-100: DONE and SHIPPED** as chart 23 (commit 7ebf41a). 19,590 rows
  / 795 weeks. Floor already raised back to its modern 25. Six single weeks are
  absent — four early-January — where Billboard repeated the previous week's
  ranking and the clamp guard declined to store it twice. That is correct
  behaviour, not data loss to chase.
- **official-uk-songs: DONE and SHIPPED** as chart 24 (commit 379621b). 13,950
  rows / 811 weeks, 2011-01-29 to 2026-08-15. Depth runs 10 at launch (227
  weeks) and 20 thereafter (584 weeks) — nothing partial in between. One week
  absent, 2011-12-31, the New Year repeat the clamp guard correctly declined
  to store twice. Floor raised 10 -> 20. Wired and 139 tests pass.
- **rock-songs**: backfill STARTED 2026-08-10 to `data/rock_songs.csv`, under
  nohup, log `logs_rock.out`. 896 weeks. Measured 50 rows at launch and at
  2010 / 2015 / 2020 / today, so the default floor of 20 backfills it safely;
  **raise to 50 when wiring.**
- **gospel-songs**: backfill STARTED 2026-08-10 to `data/gospel_songs.csv`,
  under nohup, log `logs_gospel.out`. 1118 weeks. Measured 25 rows at launch
  and throughout; default floor of 20 is safe, **raise to 25 when wiring.**
- **rock-songs: DONE and SHIPPED** as chart 25 (commit 696fc7c). 44,750 rows /
  895 weeks, 50 rows every week, zero gaps. Floor set to 50.
- **gospel-songs: DONE and SHIPPED** as chart 26 (commit 696fc7c). 27,925 rows
  / 1117 weeks, 25 rows every week, zero gaps. Floor set to 25.
- **christian-songs: DONE and SHIPPED** as chart 27 (commit 62a518b). 55,789
  rows / 1208 weeks, no gaps, depth grew 30 -> 40 -> 50. Floor 50.
- **country-songs / r-b-hip-hop-songs / top-album-sales: DONE and SHIPPED** as
  charts 28-30 (commit 80fc752). 3521 / 3459 / 1837 weeks. Floors all 50. Each
  needed two recovery runs after the deploy starved them — see below. The only
  remaining failure on each is 2026-08-15, the leading edge Billboard has not
  posted for these charts; the weekly path picks it up.

- **latin-songs: DONE and SHIPPED** as chart 31. 96,777 rows / 2,071 weeks,
  1986-09-06 to 2026-08-08. Floor raised 1 -> 50. Depth runs 1 (1986) -> 40
  (1990s) -> 50 (2005 on), so `verify_charts.py` warns about two sub-5-row
  weeks; those are real. Eleven weeks are absent and all eleven were checked
  at source: nine year-end/New-Year freezes plus **2004-10-02**, where
  Billboard repeated the prior ranking and the clamp guard correctly declined
  to store it twice, and **1998-10-10 / 1998-10-17**, which Billboard never
  published at all (both clamp forward to 1998-10-24).
  **2004-10-09 hit the predecessor-absent hole and had to be dropped.**
  Billboard froze Hot Latin Songs for three consecutive weeks — 09-25, 10-02
  and 10-09 each serve their OWN date, heading matching, with one identical
  ranking. The guard skipped 10-02, so when 10-09 was fetched its chronological
  predecessor was missing from the CSV and there was nothing to compare it
  against, exactly as the country_songs 1987-01-03 case below predicts. It was
  dropped to match how the other ten repeats on this chart are handled.
  **The lesson generalises: a freeze longer than two weeks defeats the guard,
  because the guard's own skip creates the hole the next week falls through.**
  Always re-run `verify_charts.py` after a backfill and check any flagged week
  against its served-week heading before assuming fabrication.

**All ten charts 22-31 are wired, verified and committed. 22-26 are deployed;
27-31 are NOT yet deployed.**

None of charts 22-31 have year-end data — `data/yearend.csv` still covers only
the original 18 — so `?view=yearend` correctly 302s on all ten and the toggle
is not rendered. Extending year-end coverage to them is a separate follow-up.

Six backfills ran concurrently on 2026-08-10 with no rate limiting from
billboard.com. Each still sleeps 1s per request.

### Do not deploy while a backfill is running

`railway up` uploads the whole working directory — 208 MB, mostly `data/`.
That upload saturated the connection and starved the running scrapers: country
lost 46 weeks, r-b-hip-hop 51 and top-album-sales 34, all to read timeouts and
one DNS resolution failure, in contiguous blocks that look like Billboard
outages and are not. Pause backfills before deploying, or expect to re-run.

A second-order effect to watch for after any such loss: `country_songs`
1987-01-03 was written as a real week because its predecessor 1986-12-27 was
missing to a timeout at the time, so the clamp guard had nothing to compare it
against. The recovery run filled the predecessor and created a duplicate pair,
which `verify_charts.py` caught and which was then dropped. **After recovering
lost weeks, always re-run verify_charts** — the clamp guard cannot catch a
clamped week whose predecessor was absent when it was fetched.

Re-running to recover them IS safe. The `prev_sig` fabrication bug that the
warning at the end of this file describes is fixed — `main()` looks each
week's chronological predecessor up from the CSV rather than carrying a
rolling signature, and `tests/test_backfill_chart.py` covers the scattered
re-run case directly.

### Deploying

`railway` CLI is installed and authenticated. The service exists but is not
locally linked, so pass it explicitly:

    git push origin main
    railway up --service billboard-chart-archive --detach

Live at https://billboard-chart-archive-production.up.railway.app. A build
takes about 100 seconds to go live after upload. Verify over HTTP by fetching
each new chart's route and checking the `<h1>`, not just the status code.

**Charts 22-26 are DEPLOYED and verified live as of 2026-08-10.**

### Launch depths measured before backfilling (do not re-derive)

Probe the launch week and a few spot dates BEFORE starting any backfill — the
floor has to sit at or below the shallowest real week or that era is rejected.

| slug | launch depth | modern depth | backfill floor | floor after wiring |
|---|---|---|---|---|
| `rock-songs` | 50 | 50 | 20 (default) | 50 |
| `gospel-songs` | 25 | 25 | 20 (default) | 25 |
| `christian-songs` | 40 | 50 | 20 (default) | 50 |
| `top-album-sales` | 100 | 50 | 20 (default) | 50 |
| `country-songs` | 30 (1962) | 50 | 20 (default) | 50 |
| `r-b-hip-hop-songs` | 30 (1962) | 50 | 20 (default) | 50 |
| `latin-songs` | **1** | 50 | **must be set to 1** | 50 |

Christian was 40 at 2003-06-21 and 2004, and 50 by 2012 — so it grew, and the
default floor covers the whole run. **Top Album Sales shrank**: 100 rows from
1991 through at least 2015, 50 today, so the registry's 50 is the modern value
only and must not be read as a scrape threshold. Country and R&B were 30 rows
in 1962 and 100 by 1990, both above the default floor.

## The two 1958 charts are MONDAY-dated for their first three years

Measured 2026-08-10. `country-songs` and `r-b-hip-hop-songs` were dated
**Monday** from their 1958-10-20 launch through **1961-12-25**, and Saturday
from **1962-01-06** — a real 12-day step across the change. Both charts share
the same calendar.

This was silent. `backfill_chart.py` stepped 7 days from the first week
assuming Saturday, so every Monday week — 166 per chart — was never requested.
The Saturdays it asked for instead do not exist; Billboard clamps each to a
nearby real week and the scraper's served-week guard rejects it, so the whole
era would have surfaced as ~166 entries in the fail list, indistinguishable
from network flakiness.

Fixed in `CHART_CALENDARS` in `scripts/backfill_chart.py` (commit cf50a6c),
with tests in `tests/test_backfill_chart.py`. **Before backfilling any chart
that predates the mid-1960s, probe its launch weekday first** — request a
midweek date and read the `Week of ...` heading back; Billboard's clamp
reports the real chart date, which is what makes the weekday discoverable.

`r-b-hip-hop-songs` also has a genuine hiatus: suspended after **1963-11-23**,
resumed **1965-01-30**. Those 61 weeks are in `CHART_GAPS` and are not
requested. That is why its week count is 3478 against Country's 3539.

**Latin needs a floor of 1** to backfill (it serves 1 row/week in 1986), and
that floor must be raised to 50 afterwards. It is the most dangerous of the
seven for exactly that reason.

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

## OPEN WORK — requested 2026-08-10, NOT started

Two requests arrived after charts 22-31 shipped. Neither is started; both are
multi-hour jobs. Charts 22-31 and the hover/credit fixes are all deployed and
verified, so the tree is clean to pick up from.

### 1. Year-end editions for charts 22-31 — DISCOVERY DONE 2026-08-10

The discovery run finished. Its output was diffed against
`scripts/yearend_slugs.json.bak` and all 21 pre-existing entries survived
byte-identical, including the four hand-corrected slugs. The file is trustworthy.

**25 of 31 charts have a year-end edition.** Discovery itself said 23; two more
were recovered by re-probing its negatives, because a label-derived slug cannot
reach either one:

| chart | year-end slug | why discovery missed it |
|---|---|---|
| `rock_songs` | `hot-rock-songs` | the year-end kept the chart's OLD name. The weekly is "Hot Rock & Alternative Songs"; every label-derived candidate returns 0 rows |
| `rnb_hiphop` | `r-and-b-hip-hop-airplay-songs` | the candidate rules turn `&` into `and`, so they can only ever produce `randb`. Billboard writes `r-and-b` |

`rnb_hiphop` was previously recorded here as having NO year-end edition. **That
was wrong** and the note has been removed. The earlier check rejected two other
slugs and stopped.

**A row count is not evidence.** Each recovered slug was accepted only after
distinct years produced distinct ranking signatures AND its titles matched that
chart's own weekly CSV. For `r-and-b-hip-hop-airplay-songs` the plain overlap
was ambiguous — 90-96% against airplay, 82-91% against consumption, because the
two charts share most titles. The discriminator was EXCLUSIVE matches: of the
titles it shares with exactly one CSV, **26 are airplay-only and 2 are
consumption-only**, so it belongs to `rnb_hiphop` and not `rnb_songs`. Filing it
under `rnb_songs` would have put airplay data on the consumption chart.

The six remaining nulls are measured, not assumed. `heatseekers`, `bubbling`,
`uk_songs` and `top_album_sales` fall through to the weekly chart or 404.
`rnb_songs` has no year-end of its own — the near-miss `hot-r-and-b-hip-hop-songs`
is the weekly chart in disguise.

**`japan_hot100` is the one to be careful with.** `japan-hot-100` returns a full
100 rows for 2018-2022 and passes a row count easily, but **2020, 2021 and 2022
are the same 100 titles**, and only 19% of them appear anywhere in the 2020
weekly data — with 52 weeks scraped that year, so it is not a coverage gap. One
list filed under several years, exactly like the European Hot 100. It defeats
the clamp rule the same way: the rule would name 2022 genuine and store it. The
chart is excluded by name in `NO_YEAREND` and must stay that way.

Backfill for the seven charts that need one — the five discovery confirmed plus
the two recovered — runs as:

    python3 scripts/backfill_yearend.py dance_electronic gospel christian \
        country_songs latin_songs rock_songs rnb_hiphop

It checkpoints `data/yearend.csv` after every chart, so an interrupted run keeps
its finished charts. **Back that file up first** — it holds 18 charts of good
data and the script rewrites it in place.

**BACKFILL DONE 2026-08-10.** All seven ran; `data/yearend.csv` now covers 25
charts and 555 years. It caught the failure predicted above, twice, so the
guard has been changed.

### The clamp guard leaked, and how

`hot-rock-songs` answers 1962-1978 AND 1982-2005 with **2009's list**, and
returns 0 rows for 1979-1981 and 2006-2008. Those empty years split one clamped
run into three pieces. The old rule dropped a year only when the NEXT year was
*consecutive* and identical, so 1978 and 2005 each had no consecutive successor
and both survived — storing 2009's chart under two years in which the chart did
not exist. `yearend_guard.real_years` now drops a year when ANY later year has
the same signature, adjacent or not. Two orderings of fifty songs do not
coincide by accident. A test asserted the old behaviour on the reasoning that a
gap means the years are not one run; it was untested reasoning and is now
replaced with this case.

### The hole the guard cannot close

The guard compares years against each other, so it only catches a copy whose
original is also kept. `latin_songs` 1996 held a **2006** list ("Hips Don't
Lie", "Rompe"); 2006 was never kept, so no signature matched and it passed
every structural check. It is invisible to any year-vs-year rule.

The detector that does not need a duplicate is content: a genuine year-end for
year Y is compiled from year Y's weekly charts, so its titles must appear in
that year's weekly data. Latin 1996 scored **0%** against 52 scraped weeks of
1996. That check is now `scripts/verify_yearend.py`:

    python3 scripts/verify_yearend.py      # 555 years, 0 failed, ~15s

**Run it after every year-end backfill.** Anything it fails goes into
`backfill_yearend.FABRICATED` so a later run cannot restore it — the guard will
not catch it a second time either. Years whose weekly archive does not reach
back far enough are reported as untestable and must be triaged by hand into
`UNTESTABLE_OK`; the untriaged ones fail the run rather than passing quietly.

Three years were removed as fabricated: `rock_songs` 1978 and 2005, and
`latin_songs` 1996.

### Still untriaged, inherited

`verify_yearend.py` accepts `dance_sales` 2007-2013 and `alternative` 1988 only
to get a clean baseline. They are NOT verified. Dance Singles Sales ended in
2007, so six year-end editions after the chart stopped publishing is the same
shape as the Latin 1996 finding and deserves the same content check. This is
pre-existing data, not from this backfill.

### 1b. Mainstream Rock + Adult Alternative — MEASURED 2026-08-10, not backfilled

Requested by name. Both are real and addable. Everything below is a dated
fetch, not recall; the backfill itself has NOT been started.

| key | slug | Billboard's own label | first week | depth | weeks | est. |
|---|---|---|---|---|---|---|
| `mainstream_rock` | `hot-mainstream-rock-tracks` | Mainstream Rock Airplay | **1981-03-21** | 40 | ~2,370 | ~1.3h |
| `adult_alternative` | `triple-a` | Adult Alternative Airplay | **1996-01-20** | 40 now, **20 at launch** | ~1,594 | ~0.9h |

~3,960 weeks total, roughly 2.2 hours at the measured ~2s/week.

**Neither slug is guessable.** `mainstream-rock-songs` and
`adult-alternative-songs` both return 0 rows, and `mainstream-rock-airplay` and
`adult-alternative-airplay` both 404.

**`rock-airplay` is a DIFFERENT chart** — label "Rock & Alternative Airplay",
50 deep, clamps to 2009-06-20 so that is its launch era. It is neither of these
two and is not the existing `rock_songs` (that one is the consumption chart).
It is a third chart, unrequested and unadded.

First weeks are confirmed by clamp-forward: `hot-mainstream-rock-tracks` at
1981-03-14 and 1981-03-07 both serve March 21, 1981, and `triple-a` at
1996-01-13 and 1996-01-06 both serve January 20, 1996.

**The trap here is Adult Alternative's launch depth.** It serves 20 rows in
1996 and 2000, 30 by 2010, 40 today. The default scrape floor is exactly 20, so
the whole 1996-2000s era sits ON the boundary and any week Billboard serves at
19 rows is dropped SILENTLY, leaving a CSV that looks finished. Set an explicit
backfill floor for `triple-a` in `fast_billboard_scraper.py` alongside the
japan-hot-100 / official-uk-songs entries before running, and raise it to 40
once the CSV is complete. Mainstream Rock needs no override: it serves 40 at
every era probed, 1981 through 2026, with no clamping after launch.

**BOTH BACKFILLS ARE RUNNING as of 2026-08-10, started detached.**

    mainstream_rock    -> data/mainstream_rock.csv     logs_mainstream_rock.out
    adult_alternative  -> data/adult_alternative.csv   logs_adult_alternative.out

Check the logs before anything else: expect roughly 2,370 and 1,594 weeks
kept. Early output confirmed 40 rows at 1981 and 20 at 1996, so the floors are
holding.

**Then raise `triple-a` from 15 to 40** in `fast_billboard_scraper.py`. It is
set to 15 as a BACKFILL floor only; leaving it there weakens the guard on the
live weekly path once the chart is wired.

Order is DATA FIRST, as above — the route test requires 200 for every
registered chart, so a chart registered before its CSV exists turns the suite
red.

### 2. "All the airplay charts you can find"

Not started, nothing probed. The registry currently holds nine airplay charts:
pop_airplay, adult_pop, adult_contemporary, rhythmic, country_airplay,
alternative, rnb_hiphop, dance_airplay, adult_rnb.

Billboard publishes more. The following are CANDIDATES ONLY — they are written
from recall, NOT measured, and every one must be probed with a dated fetch
before being believed, exactly as the ten above were:

    rock-airplay, mainstream-rock-songs, triple-a, latin-airplay,
    latin-pop-airplay, tropical-airplay, regional-mexican-airplay,
    christian-airplay, gospel-airplay, smooth-jazz-songs,
    dance-mix-show-airplay

Use `scripts/find_chart_start.py <slug>` for first weeks and probe launch depth
BEFORE backfilling — the scrape floor defaults to 20 and silently rejects any
shallower era, which is the trap that nearly cost Latin its entire 1986. Note
find_chart_start.py only tries Saturdays, so probe the launch weekday too for
anything predating the mid-1960s.
