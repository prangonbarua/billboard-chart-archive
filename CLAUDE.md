# billboard-chart-archive

Flask app serving a weekly + year-end Billboard chart archive. 156 charts,
deployed on Railway at
https://billboard-chart-archive-production.up.railway.app

## Deployment Definition of Done

A task is NOT done until it is verified LIVE. Always: (1) commit, (2) push to
GitHub (Railway deploys from the connected GitHub repo — do NOT use
`railway up`), (3) poll the deploy status until it succeeds, (4) curl/fetch the
live URL and confirm the change is visible. When reporting status, explicitly
state repo status vs. live status:
`Committed: yes | Pushed: yes | Deployed: yes | Verified live at <url>: yes`.

Notes measured on this project:
- `railway up` is dead here; repo-connect replaced it.
- `railway.json` pins the Dockerfile builder. Without it Railpack builds on
  Python 3.13, where pandas cannot compile.
- A deploy swaps containers with a ~30s window of 502s. A 502 mid-poll is the
  build landing, not a failure — keep polling.
- Poll for a marker string from the change itself, not for HTTP 200. The old
  version also returns 200.

## Build & Test

- Run locally: `python3 app.py` (port 5001; boot takes ~90s loading CSVs).
- Full suite: `python3 -m pytest -q` (~100s).
- Do not `import app` inside a fast test — it loads every chart CSV. Parse
  `app.py` with `ast` instead; see `tests/test_nav_panel_width.py`.

## Data & Scrapers

Chart registry lives in `app.py`: `CHARTS` for hand-written entries,
`BATCH_CHARTS` for tuple-registered ones, both keyed by chart slug.
`CHART_GROUP_ORDER` is the single source of column order for every chart
picker — never hardcode a group list in a template.

### Chart Data Integrity

Billboard scrapers silently fabricate data. Before wiring ANY new chart or
backfill into the site: verify the slug returns the expected chart type (not
year-end data), spot-check 3 random weeks against billboard.com, check for
year-boundary date errors, and confirm no sparse-retry rows were invented. If
a backfill writes 0 rows or suspiciously uniform rows, stop and re-diagnose
before continuing. Add a regression test for every fabrication bug found.

Known fabrication modes, all measured on this repo:
- A slug that 404s may clamp to the nearest published week and serve it under
  the requested date. The served-week HEADING, not the ranking, is what
  distinguishes a real skipped week from a fabricated one.
- The scraper's row floor is its historical MINIMUM depth, not the chart's
  current depth. Conflating them truncated Dance Singles Sales at 2007 for
  six years.
- A weekly URL that redirects to `/charts/year-end/...` returns year-end data
  under a weekly date. A row count accepts this silently.
- Deriving a chart Billboard never published is fabrication no year-vs-year
  rule can catch. If a chart has no archive, it does not get added — see
  `docs/HANDOFF-new-charts.md`. The one sanctioned exception is `/recurrents`,
  which is labelled derived on the page itself.

## Frontend / UI

Templates share `_nav.html` (nav + dropdown panel) and `_head_styles.html`.
`paxel.css` must be linked AFTER `_head_styles.html` or the page silently gets
the legacy palette. `/albums200` has its own template and endpoint — a feature
added to the chart pages must be added there too.

### Nav / Layout Rules

All chart nav labels must fit on a single line (no wrapping). After any nav or
dropdown CSS change, run the layout tests and confirm the panel still fits at
375px, 768px, and 1440px before declaring it fixed. Horizontal scroll handlers
must never trap vertical page scrolling.

`tests/test_nav_panel_width.py` is how widths get checked — it reads the real
font metrics, chart labels and CSS and computes the fit at each width, with no
browser involved. Do not launch headless Chrome to screenshot or measure
pages; verify over HTTP. The fit is tight on purpose: 7 columns need 1249px
against a 1250px stack breakpoint, so a new group or a long chart name will
fail those tests rather than silently spilling.

## Working Style

### Scope Discipline

Implement exactly what was asked — no extra filter boxes, regroupings, or nav
changes. If you think an adjacent change is needed, ask first with
AskUserQuestion. If the user explicitly drops something from scope, do not
reintroduce it later in the session.

Standing scope decisions on this repo:
- The row filter control was deleted 2026-08-06. Do not rebuild it unasked.
- Never edit `templates/index.html` without an explicit ask.
- The nav redesign was declined 2026-08-21. Do not re-propose it.
- Commit verified work without asking; deploys still need a confirm.
- No emojis in responses or code. No `Co-Authored-By: Claude` trailer.

## Context Handoff Protocol

When context usage passes ~70%, stop starting new work. Commit and push
everything, then write/update HANDOFF.md with: what shipped and is live, what
is committed but unpushed, what is running in the background, and the exact
next step. Never end a session with unpushed commits.
