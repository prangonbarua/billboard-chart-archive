# Follow-ups from the artist-versus branch

Deliberately deferred during execution of
`docs/superpowers/plans/2026-07-30-artist-versus-and-verification.md`.
Each was reviewed and ruled non-blocking. Nothing here is a regression
introduced by that branch unless stated.

Most of this list was worked off on 2026-07-31 in commits `229330d`,
`22dbd56`, `7f25468`, `bc0f2c8` and `a2fc6b0`. What remains is below;
the closed items are kept at the bottom with what was done.

## Still open

**Nobody has ever loaded `/versus` in a browser.** There is no JS test harness
in this repo and building one was ruled out of scope, so every piece of the
page's JavaScript — graph geometry, gap breaking, history push/pop, tie
highlighting, hover isolation, and now the pinned isolation and the request
tokens — has been verified only by code reading, by extracting functions into
Node, and by `node --check` on the extracted script. The 45 Python tests cover
routes, the API and the CSV export, not a line of the JS.

Open these and look at them:

- `/versus?chart=top100&artists=Taylor+Swift|Drake|Mariah+Carey`
- `/versus?chart=adult_contemporary&artists=Barry+Manilow` — the rank-31-to-50
  clipping case fixed in `069bf26`; 83 of Manilow's 523 points used to be
  drawn outside the viewBox.

### Data

- The clamped-week check only compares a week against its immediate
  predecessor. A clamp that reproduces a week further back is invisible to it.

### Correctness

- **Slash credits still miss a handful of forms.** `artist_match_mask` now
  splits on `/`, parentheses and commas, handles two adjacent markers, and
  maps a leader's backing band to its leader, which took Elton John's Hot 100
  `number_ones` from 7 to a correct 9. It still has no alias table, so a
  credit that renames the act outright (stage names, group-to-solo changes)
  cannot be matched. Only a curated alias list fixes that class.

### Cosmetic — not attempted

- `_song_chart_page` still re-parses chart dates per request (the versus path
  was moved to a startup parse). The `source_df.copy()` on the same line costs
  more; measured page loads are fine.
- `test_support_routes_load` accepts `(200, 302)` for all four paths though
  only `/` legitimately redirects.
- Unused `meta` loop variable in `tests/test_routes.py`.

### Out of scope, tracked by the plan itself

1. Migrating the eight legacy chart templates onto `chart.html` (~300KB of
   near-duplicate Jinja).
2. Song-vs-song comparison and cross-chart aggregate stats — explicit spec
   non-goals.

## Closed

- **radio, digital_songs and streaming_songs were dated three days early for
  their entire history.** Wednesday dates until 2025-10-22, Saturday dates from
  2025-10-25, against Billboard's Saturday convention everywhere else. By
  2026-08 this had stopped being cosmetic: the scraper's 52-week gap-backfill
  looks for missing Saturdays, saw every Wednesday-stored week as absent,
  refetched it, and wrote a Saturday row identical to the Wednesday row three
  days earlier — which is what failed the 2026-08-05 scheduled run. Fixed by
  shifting 1826 radio, 1096 digital and 666 streaming weeks by +3 days.
  Two checks came first, both at source: 24 sampled weeks spread across all
  three histories matched Billboard's chart for date+3 at 100% on the top 20
  and never matched date−4; and the one collision, 2025-10-22 landing on the
  existing 2025-10-25, turned out to be the same chart week twice — all 50
  ranks identical, so the Wednesday copy was dropped rather than merged. It was
  the worse of the two anyway: `#` image URLs, no Weeks on Chart, the
  pre-2025 debut corruption in Last Week and Peak, and commas mangled to `;`
  and `|`. Only the date field of each line was rewritten; every other byte is
  unchanged. All three files now run gap-free at 7 days from first week to
  last. The stale `streaming` baseline entry came out of
  `known_clamped_weeks.json` and the two `radio` entries were re-dated.
- **Versus had no CSV export** while the artist report page did. `229330d`
  added `/download-versus-csv`, taking the same query as `/api/versus` so an
  export always matches the comparison on screen.
- **Slash, parenthetical and backing-band credits were dropped from versus
  totals.** `22dbd56` replaced credit splitting with a boundary test.
- **`EMPTY_STATS` was inconsistent with the `kind='artist'` nulling**, so an
  unmatched artist on Artist 100 showed `0` where a matched one shows `—`.
  Fixed in `22dbd56`.
- **`primary_artist` was duplicated across `app.py` and `versus.py`** with no
  test pinning them together. Credit parsing now lives only in `versus.py`;
  `app.py` aliases it, and a test asserts the aliases are the same objects.
- **`load()` had no request-sequencing guard**, so rapid Back-Back could leave
  the chips and the scorecard describing different artist sets. Tokened in
  `7f25468`.
- **A failed `/api/versus` silently left the previous comparison on screen.**
  It now says so and clears the graph.
- **Hover isolation was desktop-only and had a 2px hit target.** Click/tap now
  pins isolation, and each line has a transparent 14px hit path.
- **Autocomplete fired an unthrottled fetch per keystroke** with no ordering
  guard. Debounced to 150ms and tokened.
- **Empty-state copy** asked for two artists when one renders a full scorecard.
- **Unused `i`** in `series.map((a, i) => ...)` removed.
- **Five pre-launch Global 200 weeks and four pre-launch Global Excl. US weeks
  were fabricated by boundary clamping** — 1800 rows dated before the charts'
  2020-09-19 launch, byte-identical to the launch week. Deleted in `bc0f2c8`.
- **The Wednesday Action had no verification step.** `verify_charts.py` now
  runs between the scrape and the commit, with the pre-existing findings
  baselined in `scripts/known_clamped_weeks.json` so only new clamps fail.
- **The clamped-week signature did not normalize titles**, so casing or
  whitespace drift between scrapes evaded it. Now stripped and casefolded.
- **Three pandas versions were in play and the pinned one had never been
  exercised.** `a2fc6b0` pointed the workflow at `requirements.txt` and
  verified the pin: on a clean 3.12 venv, pandas 2.1.4 installs, all 45 tests
  pass and `verify_charts.py` exits 0. Python 3.13 is the incompatible part —
  neither pandas 2.1.4 nor numpy 1.26.4 ships a 3.13 wheel.
- **`pytest` was in no requirements file.** Added `requirements-dev.txt`.
