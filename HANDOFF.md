# HANDOFF — 2026-08-24

## Live and verified

All shipped to https://billboard-chart-archive-production.up.railway.app and
confirmed by fetching the live pages, not just by a green build.

| Commit | What | Live proof |
|---|---|---|
| `5425471` | Past reports keeps song + album lookups, per mode | `rememberSearch` present on `/search` |
| `e5074c1` | Hot 100 Recurrents re-probe recorded in the handoff doc | docs only |
| `64f9b8f` | Dropouts picker shows every chart group | picker lists 156 charts, was 97 |
| `5442c0c` | Derived `/recurrents` view | notice + `Last pos.` + 5 of 21 on 2026-08-15 |
| `b4f0251` | This repo's CLAUDE.md | docs only |

Nothing is committed-unpushed. Nothing is running in the background.

## Not done: the weekly chart refresh

Asked for on 2026-08-24, not started. Staleness measured across all 156 CSVs:

| Latest week in CSV | Charts | |
|---|---|---|
| 2026-08-22 | 35 | current, nothing to do |
| 2026-08-15 | 111 | one week behind |
| 2026-08-08 | 6 | two weeks behind |
| 2026-07-18 | 1 | check whether this one is discontinued |
| 2013-11-30 / 2014-11-29 / 2020-03-28 | 3 | discontinued charts, correct end dates — do NOT "refresh" these |

### The blocker, precisely

`scripts/backfill_chart.py` is the right tool and is resumable, but its
signature is:

    backfill_chart.py <bb-slug> <csv-path> <first-week> [last-week]

It needs a **Billboard slug per chart**, and nothing in the repo maps a
registry key to its slug:

- `CHARTS` / `BATCH_CHARTS` in `app.py` map key -> label, group, depth, kind,
  csv. No slug.
- `scripts/run_batch_backfill.py` reads a JSON plan of
  `{slug: {csv, first_week, key}}` — exactly the missing map — but **no such
  plan file exists in the repo**. The ones used for previous batches were
  transient and never committed.
- `scripts/fast_billboard_scraper.py` has depth entries for **110 slugs**.
  That is a slug list, not a key/CSV mapping, and there are 156 charts.

So the map has to be reconstructed before any refresh can run.

### Exact next step

1. Rebuild the map as a committed file (`scripts/chart_plan.json`) of
   `{slug: {key, csv, first_week}}` for all 156 charts. Derive candidates by
   matching the 110 scraper slugs against `BATCH_CHARTS` csv names, then
   **verify each one** — a mis-mapped slug writes the wrong chart's rows into
   a CSV, which is the worst failure mode available here and no row count
   catches it. Commit this file; it is the artifact whose absence caused this.
2. For the ~117 stale charts, run `backfill_chart.py` per chart. It is
   resumable and only fetches missing weeks, so a refresh is short.
3. Pre-flight per CLAUDE.md "Chart Data Integrity" before wiring anything:
   confirm the slug returns the right chart type, spot-check weeks, watch the
   clamp guard.
4. Do NOT deploy mid-backfill. Finish, verify, then push.

### Traps that already cost time on this repo

- Billboard serves out-of-range dates by returning the boundary week's
  rankings under the date you asked for. The clamp guard in
  `backfill_chart.py` catches identical consecutive weeks; a long freeze
  defeats it.
- The scraper's row floor is a chart's historical MINIMUM depth, not its
  current depth. Conflating them truncated Dance Singles Sales at 2007.
- Scattered per-week failures are noise; a chart failing every week is real.

## Other open items

- The user's last three messages each cut off mid-sentence ("and…"). There was
  a third item after "push everything unpushed and the recurrents chart and"
  that was never received. Ask.
- `/versus` was never checked for the same hardcoded-group-list bug that hid
  59 charts on `/dropouts` (fixed in `64f9b8f`). Worth a look.
