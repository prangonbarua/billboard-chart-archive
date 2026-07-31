# Follow-ups from the artist-versus branch

Deliberately deferred during execution of
`docs/superpowers/plans/2026-07-30-artist-versus-and-verification.md`.
Each was reviewed and ruled non-blocking. Nothing here is a regression
introduced by that branch unless stated.

## Do this first

**Nobody has ever loaded `/versus` in a browser.** There is no JS test harness
in this repo and building one was ruled out of scope, so every piece of the
page's JavaScript — graph geometry, gap breaking, history push/pop, tie
highlighting, hover isolation — was verified only by code reading and by
extracting functions into Node. The 31 Python tests cover routes and the API,
not a line of the JS.

Open these two and look at them:

- `/versus?chart=top100&artists=Taylor+Swift|Drake|Mariah+Carey`
- `/versus?chart=adult_contemporary&artists=Barry+Manilow` — the rank-31-to-50
  clipping case fixed in `069bf26`; 83 of Manilow's 523 points used to be
  drawn outside the viewBox.

## Correctness

- **Slash credits are dropped from versus totals.** `artist_match_mask` does not
  split on `/`, so `George Michael/Elton John`, `Lil Nas X Featuring Elton
  John`, `Jennifer Rush (Duet With Elton John)` and `The Elton John Band` all
  fail to match a search for "Elton John" — the API returns `number_ones: 7`
  against a real 9. Pre-existing matcher behavior, but the versus scorecard is
  the first surface that presents these as headline numbers.
- **`EMPTY_STATS` is inconsistent with the `kind='artist'` nulling.** It sets
  `number_ones` / `top_10s` / `top_40s` to `0` regardless of `kind`, so an
  unmatched artist on Artist 100 shows `0` where a matched one now shows `—`.
- **`primary_artist` is duplicated across `app.py` and `versus.py`** with
  byte-identical `_CREDIT_MARKER_RE` definitions and no test pinning them
  together; `app.py` additionally has a different `_CREDIT_SPLIT_RE`. Song
  keying and artist matching must stay consistent.

## Client-side

- `async load()` has no request-sequencing guard. `renderChips()` runs
  synchronously while the scorecard and graph wait on the fetch, so after rapid
  Back-Back the chips can show one artist set and the scorecard another, with
  swatch colors that no longer match the lines. An `AbortController` or a
  request token is a five-line fix.
- A failed `/api/versus` silently leaves the previous comparison on screen —
  both `!res.ok` paths return after the chips and URL have already updated.
  Reachable via `popstate` with a chart key not in the `<option>` list.
- Hover isolation binds `mouseenter`, so it does not exist on touch devices,
  while `.legend span { cursor: pointer }` advertises it. The hit target is
  also only the 2px painted stroke.
- Autocomplete fires an unthrottled fetch per keystroke with no ordering guard;
  `<datalist>` repaint behavior differs materially across browsers.
- Empty-state copy says "Add two or more artists to compare" but a full
  scorecard renders with only one artist added.
- Unused `i` in `series.map((a, i) => ...)` in `templates/versus.html`.

## Data

- **`scripts/verify_charts.py` fails six pre-existing charts** on the
  clamped-week check: top100 (17 weeks), albums200 (15), global200 (5),
  globalexus (4), radio (2), streaming (1). None of the five new genre charts
  fail. Triage:
  - top100 / albums200 hits cluster on New Year weeks (1962-01-06, 1977-01-01,
    1977-12-31, 1978-12-30, 1979-12-29) where Billboard historically
    republished the prior chart. Likely genuine — the sibling AC, country and
    alternative charts show 14-day gaps at those same dates.
  - global200 / globalexus hits (2020-08-22 .. 2020-09-19) **pre-date the
    Global 200's September 2020 launch** and are likely fabricated by boundary
    clamping. Worth deleting.
  - radio, digital and streaming all show a 3-day step 2025-10-22 -> 2025-10-25,
    and streaming duplicates 2025-10-25. Recent scrape hiccup.
- **Running the weekly scraper wrote clamped duplicate rows** into radio,
  digital_songs and streaming_songs for a 2025-08-02 .. 2025-10-18 window
  during verification. They were reverted, not committed — but the Wednesday
  GitHub Action runs the same code path with no verification step. Consider
  adding `scripts/verify_charts.py` to the workflow, scoped so the six known
  pre-existing failures do not fail the run.
- The clamped-week signature uses `Song.astype(str)` with no `.strip()` /
  `.casefold()`, so casing or whitespace drift between scrapes evades the
  check. False negatives only, never false alarms.

## Environment

- **Three different pandas versions are in play and the pinned one has never
  been exercised.** The dev/test environment runs pandas 2.2.3 on python 3.13,
  `requirements.txt` pins 2.1.4, and `.github/workflows/update-charts.yml`
  installs a bare floating `pip install pandas`. Nothing on this branch has
  ever run against the pinned production version. Repo-wide, pre-existing.
- `pytest` is not in any requirements file. This branch introduced the repo's
  first tests; a `requirements-dev.txt` is the right home.

## Cosmetic

- `_song_chart_page` still re-parses chart dates per request (the versus path
  was moved to a startup parse). The `source_df.copy()` on the same line costs
  more; measured page loads are fine.
- `test_support_routes_load` accepts `(200, 302)` for all four paths though
  only `/` legitimately redirects.
- Unused `meta` loop variable in `tests/test_routes.py`.

## Out of scope, tracked by the plan itself

1. Migrating the eight legacy chart templates onto `chart.html` (~300KB of
   near-duplicate Jinja).
2. Song-vs-song comparison and cross-chart aggregate stats — explicit spec
   non-goals.
