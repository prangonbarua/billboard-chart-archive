# Visitor analytics and a private /admin page — design

Approved 2026-08-13. Status: designed, NOT implemented.

## What this is for

A private page on the site that answers one question: how many people are
visiting, and which charts do they open. No accounts, no signup, no membership
tier — those readings were considered and dropped. Nobody but the site owner
ever sees the page.

## What the site looks like today

`app.py` has no login, no sessions, no user records and no database. All chart
data lives in CSVs under `data/`. The `redis` line in `requirements.txt` is
there for Flask-Limiter and is not used for app data. So nothing here extends an
existing system; it is all new surface.

Railway wipes the container filesystem on every deploy. Anything written to a
plain local path is gone the next time `railway up` runs, which is the single
constraint that shapes the storage decision below.

## Storage

SQLite on a Railway volume mounted at `/data`. Chosen over managed Postgres
(a second service and a real monthly cost, justified only by scale this site
does not have) and over Redis HyperLogLog (uniques become approximate and it
answers "which chart is popular" badly).

Path comes from the `ANALYTICS_DB` env var, defaulting to `/data/analytics.db`.
Tests and local dev point it at a temp file.

The volume binds to one service, so this design does NOT survive a move to
multiple replicas. If that day comes, the fix is Postgres and the schema below
ports directly.

### Schema

    visits(day TEXT, path TEXT, views INTEGER)      -- PK (day, path)
    visitors(visitor_hash TEXT, first_seen TEXT,
             last_seen TEXT, visits INTEGER)        -- PK visitor_hash
    visitor_days(visitor_hash TEXT, day TEXT)       -- PK (visitor_hash, day)

- Lifetime uniques = `COUNT(*) FROM visitors`. Exact, not estimated.
- Total pageviews = `SUM(views) FROM visits`.
- Daily uniques = count over `visitor_days` for that day.
- Top pages = `visits` grouped by path. Keeping `path` now is what lets the
  per-chart question be answered later without a migration.

Days are stored as `YYYY-MM-DD` strings in UTC.

### How a visitor is identified

`sha256(salt + ip + user_agent)`, truncated to 16 hex characters. The raw IP is
never written, so nothing identifying is at rest and no consent banner is
needed.

**The salt must be a fixed `ANALYTICS_SALT` env var.** A per-boot random salt
would reset the lifetime count on every deploy. When the variable is missing the
module falls back to a stable constant and logs a warning — it must never
silently reset the numbers. Changing the salt later resets uniques by design.

Two limits, recorded so the number is not over-read: everyone behind one NAT on
the same browser version collapses to a single "person", and a phone moving from
wifi to cellular counts as two. This is a relative trend, not a headcount.

## Module boundary

`app.py` is ~2,500 lines, so this goes in a new `analytics.py` importing only
`sqlite3`, `hashlib` and stdlib — no Flask, so it is testable standalone.

    analytics.init_db()                            # once at startup
    analytics.record_visit(path, ip, user_agent)   # per request
    analytics.summary()                            # for the admin page

`app.py` gets a `before_request` hook that calls `record_visit`, and the admin
route calls `summary()`. Nothing else in `app.py` learns about analytics.

Only `GET` requests are counted. Also NOT counted: `/static/*`, favicon, `/api/*`
(machine traffic, not people), and `/admin*` — the admin page must not inflate
its own numbers.

`visitors.visits` increments on every counted pageview; `visitors.first_seen`
is written once and never updated, `last_seen` on each visit.

## The /admin page

One template, `templates/admin.html`, styled to match the site's Paxel look:
links `static/paxel.css` and carries its own inline layout styles, the same
pattern `about.html` uses. White background, black text, `#0c492c` green,
Space Grotesk, square corners, no motion.

**It is deliberately NOT added to `_nav.html`.** The page stays unlisted.

    GET  /admin         login form when signed out, stats when signed in
    POST /admin         checks the password, sets the session flag
    GET  /admin/logout  clears it

Shows: lifetime unique visitors and total pageviews as the two headline
numbers, today's uniques and views, a 30-day table, and the ten most-visited
paths.

### Password

An `ADMIN_PASSWORD` env var, compared with `hmac.compare_digest` for a
constant-time check. The login POST is rate-limited through the existing
Flask-Limiter so the form cannot be brute-forced.

**`SECRET_KEY` must be set in Railway.** `app.py:27` currently falls back to a
random key when the variable is unset, and Flask signs the session cookie with
it — so without a fixed value, every restart and every deploy silently logs the
admin out. This is a pre-existing condition this feature is the first to depend
on.

## Failure handling

Analytics must never be able to take the site down.

- `record_visit` swallows and logs any exception. A counting failure never
  reaches a user.
- If the `/data` volume is not attached, `init_db` logs a warning and the module
  degrades to a no-op. Charts serve normally with counting simply off.
- SQLite runs in WAL mode with a busy timeout, because gunicorn runs several
  workers against one file.

## Testing

New `tests/test_analytics.py` against a temp DB, plus additions to
`tests/test_routes.py`:

- the same visitor twice is 1 unique and 2 views
- a different user-agent is 2 uniques
- `/admin` signed out returns the form and no numbers in the body
- a wrong password does not sign in
- a correct password does
- a deliberately broken analytics DB does not 500 a chart page
- `/admin` does not appear in its own stats

## Manual steps (cannot be done from the CLI)

1. Railway dashboard: attach a volume to `billboard-chart-archive`, mount `/data`.
2. Set `ADMIN_PASSWORD`, `ANALYTICS_SALT` and `SECRET_KEY` as service variables.
3. Deploy, sign in at `/admin`, confirm the counters move.
