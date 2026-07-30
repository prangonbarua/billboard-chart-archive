# Artist Versus & Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an artist-vs-artist comparison page scoped to a single chart, plus the data-integrity verification the project has never had.

**Architecture:** Stat computation moves into a new pure module `versus.py` that imports no Flask and no app state — it takes a DataFrame of one artist's rows and returns a dict. `app.py` keeps the routes and does the artist matching. This split exists because the spec names silently-wrong stats as this feature's main risk, and a pure module is the only part of this codebase that can be unit-tested without loading 1.5M CSV rows.

**Tech Stack:** Flask 3.0, pandas 2.1.4, Jinja2, hand-rolled inline SVG (no charting library), pytest 8.3.4.

## Global Constraints

Copied verbatim from `docs/superpowers/specs/2026-07-30-genre-airplay-and-artist-versus-design.md`. Every task's requirements implicitly include these.

- **Compute peak from the Rank history. Never read the `Peak Position` column.** Commit `f1cb2ad` established the stored `Peak Position` / `Last Week` columns are corrupt — they showed a false #1 peak on every chart.
- **Key songs by `(song_lower, primary_artist(credit))`.** Commits `e78a0dd` and `6166ed4`: mid-run credit changes otherwise split one hit into two entries and truncate its run.
- **Match artists with `artist_match_mask()` (`app.py:235`), not substring.** Commit `127a996`: substring matching pulls "Tyla Yaweh" into a search for "Tyla".
- **Dedupe on `(Date, Rank)` before counting.** Duplicate scrape rows otherwise inflate every week and entry total.
- No external script tags, no CDN, no charting library. The project has none today.
- No emoji or glyph characters in any template, ever.
- Design system: SF Pro Display, Paxel green palette (`#ffffff` / `#111111` / `#02ff9a` / `#0c492c`), sharp edges, and **no animations or transitions** — `static/paxel.css` kills them globally. Do not add a base `opacity: 0` style that relies on an animation to reveal content.
- All state in the URL. Comparisons must be shareable and browser back/forward must work.
- Unlimited artists — no cap on comparison size.

---

## Scope Note — read before starting

The spec's Part 1 is **not** as complete as its status line implies. Verified 2026-07-30:

- `templates/chart.html` exists and serves only the five new genre charts, registered via the `add_url_rule` loop at `app.py:1351-1359` (the `key=_key` default binding is correctly present).
- The eight legacy charts still render their own ~38KB templates (`hot100.html`, `global200.html`, `globalexus.html`, `radio.html`, `digital.html`, `streaming.html`, `pop_airplay.html`, `artist100.html`) via individual `@app.route` decorators.
- `CHART_DATA` (`app.py:185`) stores `(df, dates)` tuples. The spec's "dates are parsed once at load" was **not** implemented — `_song_chart_page` still calls `pd.to_datetime` over the full column on every request.

Migrating the eight legacy templates onto `chart.html` is independent of this feature and belongs in its own plan. It is **out of scope here**.

The date-parsing change is **in scope** (Task 1) because Part 3's performance section depends on it explicitly.

Registry field names differ from the spec: the implemented `CHARTS` uses `group`, not `nav`, and has no `csv`, `bb_slug`, or `subtitle` fields. Use `group`.

---

## File Structure

| File | Responsibility |
|---|---|
| `versus.py` (create) | Pure stat computation + credit normalization. No Flask, no app imports, no I/O. |
| `tests/test_versus.py` (create) | Unit tests over synthetic frames. Fast — never imports `app`. |
| `tests/test_versus_api.py` (create) | Wiring tests. Imports `app`, slow, few tests. |
| `app.py` (modify) | `CHART_DT`, `/api/versus`, `/versus`, `/api/artists?chart=`, per-chart artist pools. |
| `templates/versus.html` (create) | Picker, scorecard, SVG graph. |
| `templates/_nav.html` (modify) | Add the Versus link. |
| `scripts/verify_charts.py` (create) | Data-integrity checks across all 14 charts. |

---

### Task 1: Parse chart dates once at load

`_song_chart_page` calls `pd.to_datetime` over an entire column on every request — on Adult Contemporary that is 123,309 rows per page view. The versus feature would multiply this per artist compared. Parse once at startup instead.

**Files:**
- Modify: `app.py:185-200` (the `CHART_DATA` dict)
- Modify: `app.py:1146-1150` (start of `_song_chart_page`)
- Test: `tests/test_versus_api.py`

**Interfaces:**
- Produces: `CHART_DT: dict[str, pd.Series]` — chart key to a `datetime64[ns]` Series aligned to that chart's DataFrame index. Tasks 3 and 4 consume it.
- `CHART_DATA` keeps its existing `(df, dates)` tuple shape so no existing caller changes.

- [ ] **Step 1: Write the failing test**

Create `tests/test_versus_api.py`:

```python
"""Wiring tests. These import app, which loads every CSV — slow by design.
Keep the fast unit tests in test_versus.py, which must never import app."""
import pandas as pd
import pytest


@pytest.fixture(scope='session')
def application():
    import app
    return app


def test_chart_dt_covers_every_loaded_chart(application):
    for key, (df, _dates) in application.CHART_DATA.items():
        if df is None or not len(df):
            continue
        dt = application.CHART_DT[key]
        assert len(dt) == len(df), f'{key}: dt length {len(dt)} != df length {len(df)}'
        assert dt.index.equals(df.index), f'{key}: dt index misaligned'
        assert pd.api.types.is_datetime64_any_dtype(dt), f'{key}: dt is not datetime64'
        assert dt.notna().all(), f'{key}: {dt.isna().sum()} unparseable dates'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_versus_api.py -v`
Expected: FAIL with `AttributeError: module 'app' has no attribute 'CHART_DT'`

- [ ] **Step 3: Add CHART_DT**

Insert immediately after the `CHART_DATA` dict closes at `app.py:200`:

```python
# Dates parsed once at startup. Every request previously re-parsed the whole
# Date column (123k rows on Adult Contemporary); the versus feature would have
# multiplied that per artist compared. Index-aligned to each frame so callers
# can mask with it directly.
CHART_DT = {}
for _k, (_df, _d) in CHART_DATA.items():
    if _df is not None and len(_df):
        CHART_DT[_k] = pd.to_datetime(_df['Date'], errors='coerce')
del _k, _df, _d
```

Note `_hot100_dates_parsed` (`app.py:110`) already computes this for Hot 100; the loop recomputes it rather than special-casing, which costs about a second at startup and keeps the dict uniform.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_versus_api.py -v`
Expected: PASS

If any chart reports unparseable dates, stop — that is a data bug that Task 7 will also catch, and it must be understood before building stats on top of it.

- [ ] **Step 5: Verify no page regressed**

Run:

```bash
python3 -c "
import app
c = app.app.test_client()
bad = [k for k in app.CHARTS if c.get('/'+k).status_code != 200]
print('FAILED:', bad or 'none')
"
```

Expected: `FAILED: none`

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_versus_api.py
git commit -m "Parse chart dates once at startup instead of per request"
```

---

### Task 2: Pure stat computation in versus.py

The whole correctness risk of this feature lives in this file. It is pure: DataFrame in, dict out.

**Files:**
- Create: `versus.py`
- Test: `tests/test_versus.py`

**Interfaces:**
- Produces:
  - `primary_artist(name: str) -> str`
  - `dedupe_weeks(rows: pd.DataFrame) -> pd.DataFrame`
  - `compute_artist_stats(rows: pd.DataFrame, kind: str = 'song') -> dict`
  - `display_name(rows: pd.DataFrame, query: str) -> str`
  - `EMPTY_STATS: dict`
- `rows` must carry columns `Date` (datetime64), `Rank`, `Song`, `Artist`.
- Returned dict keys: `entries`, `number_ones`, `weeks_at_1`, `top_10s`, `top_40s`, `best_peak`, `total_weeks_charted`, `first_entry`, `last_entry`, `biggest_hit`, `timeline`. Task 3 serializes this dict directly to JSON; Tasks 5 and 6 read these exact names.
- `timeline` is `[{'date': 'YYYY-MM-DD', 'rank': int}, ...]` ascending by date.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_versus.py`:

```python
"""Unit tests for versus stat computation. Must never import app — these run
against synthetic frames in milliseconds."""
import pandas as pd
import pytest

import versus


def frame(records):
    """records: (date, rank, song, artist) tuples."""
    df = pd.DataFrame(records, columns=['Date', 'Rank', 'Song', 'Artist'])
    df['Date'] = pd.to_datetime(df['Date'])
    return df


def test_primary_artist_strips_featured_credits():
    assert versus.primary_artist('Weezer Featuring Best Coast') == 'weezer'
    assert versus.primary_artist('  Drake  ') == 'drake'
    assert versus.primary_artist('Future & Metro Boomin') == 'future'


def test_peak_comes_from_rank_history_not_a_column():
    # The stored Peak Position column is corrupt repo-wide; a frame carrying a
    # lying column must not influence the result.
    df = frame([
        ('2024-01-06', 40, 'Song A', 'X'),
        ('2024-01-13', 12, 'Song A', 'X'),
        ('2024-01-20', 25, 'Song A', 'X'),
    ])
    df['Peak Position'] = 1
    stats = versus.compute_artist_stats(df)
    assert stats['best_peak'] == 12


def test_credit_drift_keys_as_one_song():
    df = frame([
        ('2024-01-06', 10, 'Hit', 'X'),
        ('2024-01-13', 8, 'Hit', 'X Featuring Y'),
        ('2024-01-20', 9, 'Hit', 'X'),
    ])
    stats = versus.compute_artist_stats(df)
    assert stats['entries'] == 1
    assert stats['total_weeks_charted'] == 3


def test_duplicate_scrape_rows_do_not_inflate_counts():
    df = frame([
        ('2024-01-06', 1, 'Hit', 'X'),
        ('2024-01-06', 1, 'Hit', 'X'),   # duplicate scrape row
        ('2024-01-13', 1, 'Hit', 'X'),
    ])
    stats = versus.compute_artist_stats(df)
    assert stats['weeks_at_1'] == 2
    assert stats['total_weeks_charted'] == 2


def test_number_ones_counts_songs_not_weeks():
    df = frame([
        ('2024-01-06', 1, 'Hit A', 'X'),
        ('2024-01-13', 1, 'Hit A', 'X'),
        ('2024-01-20', 1, 'Hit A', 'X'),
        ('2024-01-27', 1, 'Hit B', 'X'),
    ])
    stats = versus.compute_artist_stats(df)
    assert stats['number_ones'] == 2
    assert stats['weeks_at_1'] == 4


def test_top_tiers_count_distinct_songs_by_peak():
    df = frame([
        ('2024-01-06', 5, 'Hit A', 'X'),
        ('2024-01-13', 3, 'Hit A', 'X'),
        ('2024-01-06', 30, 'Hit B', 'X'),
        ('2024-01-06', 80, 'Hit C', 'X'),
    ])
    stats = versus.compute_artist_stats(df)
    assert stats['top_10s'] == 1
    assert stats['top_40s'] == 2
    assert stats['entries'] == 3


def test_biggest_hit_breaks_peak_ties_by_weeks():
    df = frame([
        ('2024-01-06', 2, 'Short', 'X'),
        ('2024-01-06', 2, 'Long', 'X'),
        ('2024-01-13', 4, 'Long', 'X'),
        ('2024-01-20', 6, 'Long', 'X'),
    ])
    assert versus.compute_artist_stats(df)['biggest_hit'] == 'Long'


def test_timeline_is_best_rank_per_week_ascending():
    df = frame([
        ('2024-01-13', 20, 'Hit A', 'X'),
        ('2024-01-13', 4, 'Hit B', 'X'),
        ('2024-01-06', 9, 'Hit A', 'X'),
    ])
    assert versus.compute_artist_stats(df)['timeline'] == [
        {'date': '2024-01-06', 'rank': 9},
        {'date': '2024-01-13', 'rank': 4},
    ]


def test_unknown_artist_returns_null_stats_not_an_error():
    stats = versus.compute_artist_stats(frame([]))
    assert stats['entries'] == 0
    assert stats['best_peak'] is None
    assert stats['timeline'] == []


def test_unrankable_rows_are_dropped():
    df = frame([
        ('2024-01-06', '-', 'Hit', 'X'),
        ('2024-01-13', 7, 'Hit', 'X'),
    ])
    stats = versus.compute_artist_stats(df)
    assert stats['best_peak'] == 7
    assert stats['total_weeks_charted'] == 1


def test_artist_kind_has_no_song_level_stats():
    df = frame([
        ('2024-01-06', 3, 'X', 'X'),
        ('2024-01-13', 2, 'X', 'X'),
    ])
    stats = versus.compute_artist_stats(df, kind='artist')
    assert stats['entries'] is None
    assert stats['biggest_hit'] is None
    assert stats['best_peak'] == 2
    assert stats['total_weeks_charted'] == 2


def test_display_name_uses_modal_capitalization():
    df = frame([
        ('2024-01-06', 5, 'Hit', 'The Kid LAROI'),
        ('2024-01-13', 5, 'Hit', 'The Kid LAROI'),
        ('2024-01-20', 5, 'Hit', 'The Kid Laroi'),
    ])
    assert versus.display_name(df, 'the kid laroi') == 'The Kid LAROI'


def test_display_name_falls_back_to_the_query():
    assert versus.display_name(frame([]), 'nobody') == 'nobody'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_versus.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'versus'`

- [ ] **Step 3: Write the implementation**

Create `versus.py`:

```python
"""Pure stat computation for the artist-versus feature.

Imports no Flask and nothing from app.py: every function takes a DataFrame of
one artist's rows and returns plain data. That is deliberate — silently wrong
stats are this feature's main risk, and this is the only part of the codebase
that can be unit-tested without loading 1.5M CSV rows.

Callers are responsible for selecting the artist's rows with
app.artist_match_mask(); substring matching pulls 'Tyla Yaweh' into a search
for 'Tyla'.
"""
import re

import pandas as pd

# A credit's primary artist is everything before the first collaboration marker.
_CREDIT_MARKER_RE = r'\s+(?:featuring|feat\.?|with|x|&|\+|duet)\s+.*$'


def primary_artist(name):
    """Normalize an artist credit to its primary artist so week-to-week credit
    drift ('Weezer' vs 'Weezer Featuring Best Coast') keys the same."""
    return re.sub(_CREDIT_MARKER_RE, '', str(name).strip().casefold())


def dedupe_weeks(rows):
    """One row per (Date, Rank). Duplicate scrape rows otherwise inflate every
    week and entry total."""
    return rows.drop_duplicates(subset=['Date', 'Rank'])


EMPTY_STATS = {
    'entries': 0,
    'number_ones': 0,
    'weeks_at_1': 0,
    'top_10s': 0,
    'top_40s': 0,
    'best_peak': None,
    'total_weeks_charted': 0,
    'first_entry': None,
    'last_entry': None,
    'biggest_hit': None,
    'timeline': [],
}


def _clean(rows):
    """Drop rows that cannot be ranked or dated, then dedupe."""
    if rows is None or rows.empty:
        return None
    r = rows.copy()
    r['Rank'] = pd.to_numeric(r['Rank'], errors='coerce')
    r = r.dropna(subset=['Rank', 'Date'])
    if r.empty:
        return None
    return dedupe_weeks(r)


def compute_artist_stats(rows, kind='song'):
    """Stats for one artist on one chart.

    `kind` comes from the CHARTS registry. On an artist chart the entries are
    artists rather than songs, so song-level counts are meaningless and are
    returned as None instead of a misleading number.
    """
    r = _clean(rows)
    if r is None:
        return dict(EMPTY_STATS)

    # Peak always from the Rank history — the stored Peak Position column is
    # corrupt across this repo's pre-2025 data.
    per_song = (
        r.assign(_key=[
            (s, primary_artist(a))
            for s, a in zip(r['Song'].astype(str).str.strip().str.casefold(),
                            r['Artist'].astype(str))
        ])
        .groupby('_key')
        .agg(peak=('Rank', 'min'), weeks=('Rank', 'size'), title=('Song', 'first'))
    )

    best = per_song.sort_values(['peak', 'weeks'], ascending=[True, False])

    stats = {
        'entries': int(len(per_song)),
        'number_ones': int((per_song['peak'] == 1).sum()),
        'weeks_at_1': int((r['Rank'] == 1).sum()),
        'top_10s': int((per_song['peak'] <= 10).sum()),
        'top_40s': int((per_song['peak'] <= 40).sum()),
        'best_peak': int(per_song['peak'].min()),
        'total_weeks_charted': int(r['Date'].nunique()),
        'first_entry': r['Date'].min().strftime('%Y-%m-%d'),
        'last_entry': r['Date'].max().strftime('%Y-%m-%d'),
        'biggest_hit': str(best.iloc[0]['title']).strip(),
        'timeline': [
            {'date': d.strftime('%Y-%m-%d'), 'rank': int(v)}
            for d, v in r.groupby('Date')['Rank'].min().sort_index().items()
        ],
    }

    if kind == 'artist':
        stats['entries'] = None
        stats['biggest_hit'] = None
        stats['number_ones'] = int((r['Rank'] == 1).any())

    return stats


def display_name(rows, query):
    """The artist's modal capitalization in the data. Scraped casing drifts
    week to week ('The Kid LAROI' vs 'The Kid Laroi'); show the common one."""
    if rows is None or rows.empty:
        return query
    target = primary_artist(query)
    credits = rows['Artist'].astype(str)
    exact = credits[credits.map(primary_artist) == target]
    if exact.empty:
        return query
    return str(exact.mode().iloc[0]).strip()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_versus.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add versus.py tests/test_versus.py
git commit -m "Add pure artist stat computation with unit tests"
```

---

### Task 3: The /api/versus endpoint

**Files:**
- Modify: `app.py` — add after the `/api/artists` route ends at `app.py:573`
- Test: `tests/test_versus_api.py`

**Interfaces:**
- Consumes: `CHART_DT` (Task 1); `compute_artist_stats`, `display_name` (Task 2); `artist_match_mask` (`app.py:235`).
- Produces: `GET /api/versus?chart=<key>&artists=<pipe-separated>` returning
  `{'chart': {'key', 'label', 'depth', 'kind'}, 'artists': [{'name', 'display_name', ...stats}]}`.
  Tasks 5 and 6 consume this exact shape.
- Produces: `_versus_artist_rows(key, artist) -> pd.DataFrame` — Task 4 does not use it, but Task 8 does.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_versus_api.py`:

```python
def test_versus_rejects_unknown_chart(application):
    r = application.app.test_client().get('/api/versus?chart=nope&artists=Drake')
    assert r.status_code == 400


def test_versus_returns_one_entry_per_requested_artist(application):
    r = application.app.test_client().get(
        '/api/versus?chart=top100&artists=Taylor+Swift|Drake')
    assert r.status_code == 200
    body = r.get_json()
    assert [a['name'] for a in body['artists']] == ['Taylor Swift', 'Drake']
    assert body['chart']['key'] == 'top100'
    assert body['chart']['depth'] == 100


def test_versus_unknown_artist_returns_null_stats_not_an_error(application):
    r = application.app.test_client().get(
        '/api/versus?chart=top100&artists=Drake|Zzzznotanartist')
    assert r.status_code == 200
    artists = r.get_json()['artists']
    assert artists[0]['entries'] > 0
    assert artists[1]['entries'] == 0
    assert artists[1]['timeline'] == []


def test_versus_does_not_substring_match_artists(application):
    """artist_match_mask must be used: 'Tyla' must not absorb 'Tyla Yaweh'."""
    r = application.app.test_client().get('/api/versus?chart=top100&artists=Tyla')
    rows = application._versus_artist_rows('top100', 'Tyla')
    credits = set(rows['Artist'].astype(str))
    assert not any('yaweh' in c.casefold() for c in credits)
    assert r.status_code == 200


def test_versus_empty_artists_param_returns_empty_list(application):
    r = application.app.test_client().get('/api/versus?chart=top100&artists=')
    assert r.status_code == 200
    assert r.get_json()['artists'] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_versus_api.py -v -k versus`
Expected: FAIL — 404 on `/api/versus`, and `AttributeError` for `_versus_artist_rows`

- [ ] **Step 3: Write the implementation**

Add `import versus` to the import block at the top of `app.py`, then insert after `app.py:573`:

```python
# ── Artist versus ───────────────────────────────────────────────────────────

def _versus_artist_rows(chart_key, artist_name):
    """That artist's rows on one chart, with Date already parsed.

    Uses artist_match_mask, not substring matching: 'Tyla' must match
    'Tyla Featuring Zara Larsson' but not 'Tyla Yaweh' (commit 127a996).
    """
    df, _dates = CHART_DATA.get(chart_key, (None, None))
    if df is None or not len(df):
        return pd.DataFrame(columns=['Date', 'Rank', 'Song', 'Artist'])
    mask = artist_match_mask(df['Artist'], artist_name)
    rows = df.loc[mask, ['Rank', 'Song', 'Artist']].copy()
    rows['Date'] = CHART_DT[chart_key].loc[rows.index]
    return rows


def _parse_artist_list(raw):
    """Pipe-separated artists, blanks dropped, original order and case kept."""
    return [a.strip() for a in (raw or '').split('|') if a.strip()]


@app.route('/api/versus')
@limiter.exempt
def api_versus():
    chart_key = request.args.get('chart', 'top100')
    meta = CHARTS.get(chart_key)
    if meta is None:
        return {'error': 'Unknown chart'}, 400
    df, _dates = CHART_DATA.get(chart_key, (None, None))
    if df is None or not len(df):
        return {'error': 'Chart data is not available'}, 400

    results = []
    for name in _parse_artist_list(request.args.get('artists')):
        rows = _versus_artist_rows(chart_key, name)
        stats = versus.compute_artist_stats(rows, kind=meta['kind'])
        # A typo in a four-artist comparison must not blank the page, so an
        # unmatched artist comes back with null stats rather than an error.
        results.append({
            'name': name,
            'display_name': versus.display_name(rows, name),
            **stats,
        })

    return {
        'chart': {
            'key': chart_key,
            'label': meta['label'],
            'depth': meta['depth'],
            'kind': meta['kind'],
        },
        'artists': results,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_versus_api.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_versus_api.py
git commit -m "Add /api/versus returning per-artist stats scoped to one chart"
```

---

### Task 4: Per-chart artist pools for autocomplete

`MODERN_ARTISTS` (`app.py:116`) is built from Hot 100 rows dated 1990+. It fails this feature twice: a country act who never crossed to the Hot 100 would never autocomplete on Country Airplay, and Adult Contemporary reaches back to 1961.

**Files:**
- Modify: `app.py:116` region (add pool builder) and `app.py:560-573` (`get_artists`)
- Test: `tests/test_versus_api.py`

**Interfaces:**
- Consumes: `CHART_DATA`, `_collab_markers` (`app.py:115`).
- Produces: `CHART_ARTISTS: dict[str, list[str]]` — chart key to a sorted artist list. `get_artists` accepts an optional `chart` param; omitting it keeps today's `MODERN_ARTISTS` behaviour so `search.html` is unaffected.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_versus_api.py`:

```python
def test_artists_endpoint_without_chart_is_unchanged(application):
    r = application.app.test_client().get('/api/artists?q=tay')
    assert r.status_code == 200
    names = r.get_json()['artists']
    assert names == [a for a in application.MODERN_ARTISTS
                     if a.lower().startswith('tay')][:50]


def test_country_pool_holds_acts_the_hot100_pool_misses(application):
    pool = set(application.CHART_ARTISTS['country_airplay'])
    assert len(pool) > 500
    # Reached country radio without a comparable Hot 100 footprint.
    assert any('Rhett Akins' == a for a in pool)


def test_adult_contemporary_pool_reaches_before_1990(application):
    """MODERN_ARTISTS is filtered to 1990+; this chart starts in 1961."""
    pool = set(application.CHART_ARTISTS['adult_contemporary'])
    assert 'Nat King Cole' in pool


def test_artists_endpoint_honours_the_chart_param(application):
    r = application.app.test_client().get('/api/artists?chart=country_airplay&q=a')
    assert r.status_code == 200
    names = r.get_json()['artists']
    assert names
    assert set(names) <= set(application.CHART_ARTISTS['country_airplay'])
    assert len(names) <= 50


def test_artists_endpoint_falls_back_on_unknown_chart(application):
    r = application.app.test_client().get('/api/artists?chart=nope&q=tay')
    assert r.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_versus_api.py -v -k "pool or artists_endpoint"`
Expected: FAIL — `AttributeError: module 'app' has no attribute 'CHART_ARTISTS'`

- [ ] **Step 3: Build the pools**

Insert after the `CHART_DT` block from Task 1:

```python
# Autocomplete pool per chart. MODERN_ARTISTS is Hot 100 rows from 1990+, which
# would never surface a country act who did not cross over, and would hide the
# pre-1990 half of Adult Contemporary. Precomputed once, like MODERN_ARTISTS.
CHART_ARTISTS = {}
for _k, (_df, _d) in CHART_DATA.items():
    if _df is None or not len(_df):
        continue
    _names = _df['Artist'].dropna().astype(str).str.strip().unique()
    CHART_ARTISTS[_k] = sorted(
        a for a in _names
        if a and not any(m in a.lower() for m in _collab_markers)
    )
del _k, _df, _d, _names
```

- [ ] **Step 4: Add the chart param**

Replace the body of `get_artists` at `app.py:562-573`:

```python
def get_artists():
    """API endpoint for artist autocomplete.

    With ?chart=<key> the pool is that chart's own artists — required by the
    versus page, where the Hot 100 pool would miss format-chart acts entirely.
    Without it, behaviour is unchanged for search.html.
    """
    query = request.args.get('q', '').lower()
    pool = CHART_ARTISTS.get(request.args.get('chart', ''), MODERN_ARTISTS)

    if query:
        artists = [a for a in pool if a.lower().startswith(query)]
    else:
        artists = pool

    # Pools are pre-sorted, so slicing preserves order.
    return {'artists': list(artists[:50])}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_versus_api.py -v`
Expected: all PASS

If `test_country_pool_holds_acts_the_hot100_pool_misses` fails on the specific name, substitute another act present in `data/country_airplay.csv` but absent from `MODERN_ARTISTS` — find one with:

```bash
python3 -c "
import app
country = set(app.CHART_ARTISTS['country_airplay'])
print(sorted(country - set(app.MODERN_ARTISTS))[:40])
"
```

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_versus_api.py
git commit -m "Scope artist autocomplete to the selected chart"
```

---

### Task 5: The versus page — picker and scorecard

Graph comes in Task 6. This task ends with a working, shareable comparison page.

**Files:**
- Create: `templates/versus.html`
- Modify: `app.py` — add the `/versus` route after `api_versus`
- Modify: `templates/_nav.html:111` — add the Versus link
- Test: `tests/test_versus_api.py`

**Interfaces:**
- Consumes: `/api/versus` and `/api/artists?chart=` (Tasks 3, 4).
- Produces: the `/versus` endpoint, and in `versus.html` a JS function
  `renderScorecard(data)` plus a `<div id="graph">` placeholder that Task 6 fills.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_versus_api.py`:

```python
def test_versus_page_renders_without_artists(application):
    r = application.app.test_client().get('/versus')
    assert r.status_code == 200
    assert b'Versus' in r.data


def test_versus_page_state_lives_in_the_url(application):
    r = application.app.test_client().get(
        '/versus?chart=country_airplay&artists=Luke+Combs|Morgan+Wallen')
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert 'country_airplay' in body
    assert 'Luke Combs' in body


def test_versus_link_is_in_the_nav(application):
    body = application.app.test_client().get('/top100').get_data(as_text=True)
    assert '/versus' in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_versus_api.py -v -k "page or nav"`
Expected: FAIL — 404 on `/versus`

- [ ] **Step 3: Add the route**

Insert in `app.py` directly after the `api_versus` function:

```python
@app.route('/versus')
@limiter.exempt
def versus_page():
    """Artist comparison scoped to one chart. All state is in the URL so
    comparisons are shareable and browser back/forward works."""
    chart_key = request.args.get('chart', 'top100')
    if chart_key not in CHARTS:
        chart_key = 'top100'
    return render_template(
        'versus.html',
        chart_key=chart_key,
        chart=CHARTS[chart_key],
        charts=available_charts(),
        initial_artists=_parse_artist_list(request.args.get('artists')),
    )
```

- [ ] **Step 4: Add the nav link**

In `templates/_nav.html`, insert before the Reports link at line 111:

```html
    <a href="{{ url_for('versus_page') }}"
       class="{{ 'active' if request.endpoint == 'versus_page' else '' }}">Versus</a>
```

- [ ] **Step 5: Extract the shared base styles into a partial**

**Ruling (human partner, 2026-07-30):** do NOT paste the base styles a tenth time. Extract them into a partial, matching the direction `_nav.html` established.

1. Create `templates/_head_styles.html` containing **only** the `@font-face` rule, the `:root` variable block, the universal reset (`*, *::before, *::after`), and the `body` rule — copied byte-for-byte from `templates/chart.html`, wrapped in a single `<style>` tag. Copy, do not retype: the palette hexes must match exactly.
2. In `templates/chart.html`, delete those same four rules from its inline `<style>` and put `{% include '_head_styles.html' %}` immediately before the remaining `<style>` tag. Leave every other rule in `chart.html` untouched.
3. Leave the eight legacy templates alone — they are migrated in the separate template-collapse plan.

Verify before moving on: `python3 app.py`, then load `/country_airplay` and confirm it is visually unchanged — white background, green accents, SF Pro. A missing variable renders as an unstyled page, which is obvious on sight.

- [ ] **Step 5b: Write the template**

Create `templates/versus.html` using the body below. It opens with `{% include '_head_styles.html' %}` rather than its own copy of the base styles. Do not add transitions or animations; `paxel.css` strips them.

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Versus &middot; {{ chart.label }}</title>
    {% include '_head_styles.html' %}
    <style>
    .wrap { max-width: 1100px; margin: 0 auto; padding: 2rem 1.5rem 4rem; }
    h1 { font-size: 1.75rem; font-weight: 600; letter-spacing: -0.02em; }
    .page-meta { color: var(--text-muted); font-size: 0.875rem; margin-top: 0.25rem; }

    .picker { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center;
              margin: 1.5rem 0; }
    .picker select, .picker input {
        font-family: inherit; font-size: 0.875rem; padding: 0.5rem 0.75rem;
        border: 1px solid var(--border); background: var(--surface);
        color: var(--text); border-radius: 0;
    }
    .picker input { min-width: 220px; }
    .picker button {
        font-family: inherit; font-size: 0.875rem; font-weight: 500;
        padding: 0.5rem 1rem; border: 1px solid var(--border-accent);
        background: var(--border-accent); color: #ffffff; cursor: pointer;
        border-radius: 0;
    }

    .chips { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 1.5rem; }
    .chip { display: inline-flex; align-items: center; gap: 0.5rem;
            padding: 0.375rem 0.75rem; border: 1px solid var(--border);
            font-size: 0.875rem; }
    .chip button { border: 0; background: none; color: var(--text-muted);
                   cursor: pointer; font-family: inherit; font-size: 1rem;
                   line-height: 1; padding: 0; }
    .chip .swatch { width: 10px; height: 10px; display: inline-block; }

    /* Many artists scroll horizontally rather than crushing the layout. */
    .scorecard-wrap { overflow-x: auto; }
    table.scorecard { border-collapse: collapse; width: 100%; min-width: 480px; }
    .scorecard th, .scorecard td {
        text-align: right; padding: 0.6875rem 1rem; font-size: 0.9375rem;
        border-bottom: 1px solid var(--border); white-space: nowrap;
    }
    .scorecard th:first-child, .scorecard td:first-child {
        text-align: left; color: var(--text-muted); font-weight: 500;
    }
    .scorecard thead th { font-weight: 600; color: var(--text); }
    .scorecard td.best { background: var(--surface-active); font-weight: 600; }
    .empty { color: var(--text-muted); padding: 2rem 0; }
    </style>
</head>
<body>
{% include '_nav.html' %}

<div class="wrap">
    <h1>Versus</h1>
    <div class="page-meta">Compare artists on {{ chart.label }}</div>

    <form class="picker" id="picker" autocomplete="off">
        <select id="chart" name="chart">
            {% for group, items in charts.items() %}
            <optgroup label="{{ group }}">
                {% for c in items %}
                <option value="{{ c.key }}" {{ 'selected' if c.key == chart_key else '' }}>{{ c.label }}</option>
                {% endfor %}
            </optgroup>
            {% endfor %}
        </select>
        <input id="artist" list="artist-options" placeholder="Add an artist">
        <datalist id="artist-options"></datalist>
        <button type="submit">Add</button>
    </form>

    <div class="chips" id="chips"></div>
    <div id="graph"></div>
    <div class="scorecard-wrap"><div id="scorecard"></div></div>
</div>

<script>
const CHART_KEY = {{ chart_key|tojson }};
const INITIAL   = {{ initial_artists|tojson }};

// Cycling palette. Distinct hues are required to tell series apart; the site
// green leads so the page still reads as part of the design system.
const PALETTE = ['#0c492c', '#c2410c', '#1d4ed8', '#a21caf', '#b45309', '#0f766e'];
const colorFor = i => PALETTE[i % PALETTE.length];

let artists = INITIAL.slice();

// All state in the URL: shareable, and back/forward works.
function syncUrl() {
    const q = new URLSearchParams();
    q.set('chart', document.getElementById('chart').value);
    if (artists.length) q.set('artists', artists.join('|'));
    history.replaceState(null, '', '/versus?' + q.toString());
}

function renderChips() {
    document.getElementById('chips').innerHTML = artists.map((a, i) =>
        `<span class="chip"><span class="swatch" style="background:${colorFor(i)}"></span>`
        + `${escapeHtml(a)}<button type="button" data-i="${i}" aria-label="Remove">&times;</button></span>`
    ).join('');
}

function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c =>
        ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

const ROWS = [
    ['Entries',            a => a.entries,             'high'],
    ['Number ones',        a => a.number_ones,         'high'],
    ['Weeks at #1',        a => a.weeks_at_1,          'high'],
    ['Top 10s',            a => a.top_10s,             'high'],
    ['Top 40s',            a => a.top_40s,             'high'],
    ['Best peak',          a => a.best_peak,           'low'],
    ['Weeks charted',      a => a.total_weeks_charted, 'high'],
    ['First entry',        a => a.first_entry,         null],
    ['Last entry',         a => a.last_entry,          null],
    ['Biggest hit',        a => a.biggest_hit,         null],
];

function renderScorecard(data) {
    const list = data.artists;
    if (!list.length) {
        document.getElementById('scorecard').innerHTML =
            '<div class="empty">Add two or more artists to compare.</div>';
        return;
    }
    const head = '<tr><th></th>' + list.map(a =>
        `<th>${escapeHtml(a.display_name)}</th>`).join('') + '</tr>';

    const body = ROWS.map(([label, get, better]) => {
        const vals = list.map(get);
        let bestIdx = -1;
        if (better) {
            const nums = vals.map(v => (typeof v === 'number' ? v : null));
            const real = nums.filter(v => v !== null);
            if (real.length) {
                const target = better === 'high' ? Math.max(...real) : Math.min(...real);
                bestIdx = nums.indexOf(target);
            }
        }
        const cells = vals.map((v, i) =>
            `<td class="${i === bestIdx ? 'best' : ''}">${v === null || v === undefined ? '&mdash;' : escapeHtml(v)}</td>`
        ).join('');
        return `<tr><td>${label}</td>${cells}</tr>`;
    }).join('');

    document.getElementById('scorecard').innerHTML =
        `<table class="scorecard"><thead>${head}</thead><tbody>${body}</tbody></table>`;
}

async function load() {
    renderChips();
    syncUrl();
    if (!artists.length) { renderScorecard({artists: []}); return; }
    const chart = document.getElementById('chart').value;
    const res = await fetch(`/api/versus?chart=${encodeURIComponent(chart)}`
        + `&artists=${encodeURIComponent(artists.join('|'))}`);
    if (!res.ok) return;
    const data = await res.json();
    renderScorecard(data);
    if (window.renderGraph) window.renderGraph(data);   // filled in by Task 6
}

document.getElementById('picker').addEventListener('submit', e => {
    e.preventDefault();
    const input = document.getElementById('artist');
    const name = input.value.trim();
    if (name && !artists.includes(name)) { artists.push(name); load(); }
    input.value = '';
});

document.getElementById('chips').addEventListener('click', e => {
    const btn = e.target.closest('button[data-i]');
    if (!btn) return;
    artists.splice(Number(btn.dataset.i), 1);
    load();
});

document.getElementById('chart').addEventListener('change', load);

// Autocomplete against the selected chart's own artist pool.
document.getElementById('artist').addEventListener('input', async e => {
    const q = e.target.value.trim();
    if (q.length < 2) return;
    const chart = document.getElementById('chart').value;
    const res = await fetch(`/api/artists?chart=${encodeURIComponent(chart)}`
        + `&q=${encodeURIComponent(q)}`);
    if (!res.ok) return;
    const {artists: opts} = await res.json();
    document.getElementById('artist-options').innerHTML =
        opts.map(a => `<option value="${escapeHtml(a)}">`).join('');
});

load();
</script>
</body>
</html>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_versus_api.py -v`
Expected: all PASS

- [ ] **Step 7: Check it in a browser**

Run `python3 app.py`, open `http://localhost:5001/versus?chart=top100&artists=Taylor+Swift|Drake`, and confirm: both artists appear as chips, the scorecard fills, removing a chip updates the URL, and the nav dropdown still opens.

- [ ] **Step 8: Commit**

```bash
git add app.py templates/versus.html templates/_nav.html tests/test_versus_api.py
git commit -m "Add artist versus page with picker and scorecard"
```

---

### Task 6: The rank-over-time graph

**REQUIRED:** load the `dataviz` skill before writing any of this task's code — it governs chart color, axis, and legend decisions.

Hand-rolled inline SVG. No external dependency: the project has no script tags today and must keep none.

**Files:**
- Modify: `templates/versus.html` — add `renderGraph` and its styles

**Interfaces:**
- Consumes: the `/api/versus` payload, `PALETTE`, `colorFor`, `escapeHtml` (Task 5).
- Produces: `window.renderGraph(data)` — Task 5's `load()` already calls it.

- [ ] **Step 1: Add the graph styles**

Add to the `<style>` block in `versus.html`:

```css
.graph-wrap { overflow-x: auto; margin: 1.5rem 0 2rem; }
.graph { display: block; }
.graph .axis { stroke: var(--border); stroke-width: 1; }
.graph .tick { fill: var(--text-muted); font-size: 11px; }
.graph .series { fill: none; stroke-width: 1.75; }
.graph .series.dim { opacity: 0.15; }
.legend { display: flex; flex-wrap: wrap; gap: 1rem; font-size: 0.875rem; }
.legend span { display: inline-flex; align-items: center; gap: 0.375rem;
               cursor: pointer; }
.legend i { width: 14px; height: 3px; display: inline-block; }
```

- [ ] **Step 2: Write renderGraph**

Add before `load()` in the `<script>` block:

```javascript
// Hand-rolled SVG. Y is rank, inverted so #1 sits at the top, scaled to the
// chart's depth. Weeks an artist did not chart break the line rather than
// interpolating across the gap, which would imply chart presence that did not
// exist.
window.renderGraph = function (data) {
    const host = document.getElementById('graph');
    const series = data.artists.filter(a => a.timeline.length);
    if (!series.length) { host.innerHTML = ''; return; }

    const W = 1040, H = 420, M = {t: 16, r: 16, b: 28, l: 40};
    const depth = data.chart.depth;

    const times = series.flatMap(a => a.timeline.map(p => Date.parse(p.date)));
    const t0 = Math.min(...times), t1 = Math.max(...times);
    const spanX = (t1 - t0) || 1;

    const x = t => M.l + ((t - t0) / spanX) * (W - M.l - M.r);
    const y = r => M.t + ((r - 1) / Math.max(depth - 1, 1)) * (H - M.t - M.b);

    // A gap longer than 10 days means at least one missed week: break the path.
    const GAP_MS = 10 * 864e5;
    const pathFor = tl => {
        let d = '', prev = null;
        for (const p of tl) {
            const t = Date.parse(p.date);
            d += (prev === null || t - prev > GAP_MS ? 'M' : 'L')
               + x(t).toFixed(1) + ' ' + y(p.rank).toFixed(1) + ' ';
            prev = t;
        }
        return d.trim();
    };

    const rankTicks = [1, ...[10, 25, 50, 100, 200].filter(r => r < depth), depth];
    const yAxis = rankTicks.map(r =>
        `<text class="tick" x="${M.l - 8}" y="${y(r) + 4}" text-anchor="end">${r}</text>`
    ).join('');

    const yearOf = t => new Date(t).getUTCFullYear();
    const years = [];
    for (let s = 0; s < 6; s++) {
        const t = t0 + (spanX * s) / 5;
        years.push(`<text class="tick" x="${x(t).toFixed(1)}" y="${H - 8}" `
            + `text-anchor="middle">${yearOf(t)}</text>`);
    }

    const lines = series.map((a, i) =>
        `<path class="series" data-name="${escapeHtml(a.name)}" `
        + `stroke="${colorFor(data.artists.indexOf(a))}" d="${pathFor(a.timeline)}"></path>`
    ).join('');

    host.innerHTML = `
      <div class="graph-wrap">
        <svg class="graph" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}"
             role="img" aria-label="Chart rank over time">
          <line class="axis" x1="${M.l}" y1="${M.t}" x2="${M.l}" y2="${H - M.b}"></line>
          <line class="axis" x1="${M.l}" y1="${H - M.b}" x2="${W - M.r}" y2="${H - M.b}"></line>
          ${yAxis}${years}${lines}
        </svg>
      </div>
      <div class="legend">${series.map(a =>
        `<span data-name="${escapeHtml(a.name)}">`
        + `<i style="background:${colorFor(data.artists.indexOf(a))}"></i>`
        + `${escapeHtml(a.display_name)}</span>`).join('')}
      </div>`;

    // Hovering a legend entry or a line isolates it and dims the rest.
    const paths = host.querySelectorAll('.series');
    const isolate = name => paths.forEach(p =>
        p.classList.toggle('dim', name !== null && p.dataset.name !== name));
    host.querySelectorAll('.legend span, .series').forEach(el => {
        el.addEventListener('mouseenter', () => isolate(el.dataset.name));
        el.addEventListener('mouseleave', () => isolate(null));
    });
};
```

- [ ] **Step 3: Verify in a browser**

Run `python3 app.py` and open:

`http://localhost:5001/versus?chart=top100&artists=Taylor+Swift|Drake|Mariah+Carey`

Confirm: `#1` is at the **top** of the y axis; each artist is a distinct color matching its chip; hovering a legend entry dims the others; and an artist with a long chart absence shows a break, not a straight line across it.

Then check a deep chart renders sensibly: `?chart=country_airplay&artists=George+Strait|Alan+Jackson` — the y axis should top out at 60, not 100.

- [ ] **Step 4: Commit**

```bash
git add templates/versus.html
git commit -m "Add rank-over-time SVG graph to the versus page"
```

---

### Task 7: Data-integrity verification script

Spec verification item 1. This is the first automated check this repo has ever had over its CSVs.

**Files:**
- Create: `scripts/verify_charts.py`

**Interfaces:**
- Consumes: `CHARTS`, `CHART_DATA` from `app.py`.
- Produces: a CLI reporting per-chart results; exit 1 if any hard check fails.

- [ ] **Step 1: Write the script**

Create `scripts/verify_charts.py`:

```python
#!/usr/bin/env python3
"""Data-integrity checks across every loaded chart. Run from the repo root:

    python3 scripts/verify_charts.py

Row counts are checked for plausibility only, never against the registry's
`depth`: these charts changed depth over their lifetimes (Adult Contemporary
ran 19-20 rows in 1961 against 30 today), so depth is a display value.

The consecutive-ranking check is the post-hoc guard for clamped weeks. Billboard
serves any out-of-range date by returning the boundary week's rankings under the
requested date, so a fabricated week looks entirely valid on its own. Only an
identical full (rank, song) ordering against the neighbouring week reveals it.
A repeated #1 proves nothing — songs hold #1 for months.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app  # noqa: E402


def check_chart(key, df):
    """Return (hard_failures, warnings) for one chart."""
    hard, warn = [], []

    dt = pd.to_datetime(df['Date'], errors='coerce')
    if dt.isna().any():
        hard.append(f'{int(dt.isna().sum())} unparseable dates')

    d = df.assign(_dt=dt).dropna(subset=['_dt'])

    dupes = d.duplicated(subset=['_dt', 'Rank']).sum()
    if dupes:
        hard.append(f'{int(dupes)} duplicate (Date, Rank) rows')

    weeks = sorted(d['_dt'].unique())
    if weeks != sorted(set(weeks)):
        hard.append('week list is not unique')

    # Gaps. Reported, not fatal: several charts have genuine publication gaps
    # and a hand-filled seam week, and those are known rather than corrupt.
    gaps = []
    for a, b in zip(weeks, weeks[1:]):
        delta = (pd.Timestamp(b) - pd.Timestamp(a)).days
        if delta != 7:
            gaps.append((pd.Timestamp(a).date(), pd.Timestamp(b).date(), delta))
    if gaps:
        shown = ', '.join(f'{a}->{b} ({n}d)' for a, b, n in gaps[:5])
        warn.append(f'{len(gaps)} non-weekly steps: {shown}'
                    + (' ...' if len(gaps) > 5 else ''))

    # Clamped-week detection.
    # Columns are selected before .apply so this works on both the pinned
    # pandas 2.1.4 and newer versions, where passing the grouping column
    # through warns and needs include_groups=False (2.2+ only).
    sig = (d.sort_values(['_dt', 'Rank'])
             .groupby('_dt')[['Rank', 'Song']]
             .apply(lambda g: tuple(zip(g['Rank'], g['Song'].astype(str)))))
    clamped = [str(pd.Timestamp(b).date())
               for a, b in zip(sig.index, sig.index[1:])
               if sig.loc[a] == sig.loc[b]]
    if clamped:
        hard.append(f'{len(clamped)} week(s) identical to the previous week '
                    f'(clamped?): {", ".join(clamped[:5])}')

    counts = d.groupby('_dt').size()
    if (counts < 5).any():
        n = int((counts < 5).sum())
        warn.append(f'{n} week(s) with fewer than 5 rows')

    return hard, warn


def main():
    failed = False
    for key in app.CHARTS:
        df, _dates = app.CHART_DATA.get(key, (None, None))
        if df is None or not len(df):
            print(f'SKIP  {key:22} no data loaded')
            continue

        hard, warn = check_chart(key, df)
        weeks = pd.to_datetime(df['Date'], errors='coerce').nunique()
        status = 'FAIL' if hard else 'OK  '
        print(f'{status}  {key:22} {len(df):>7} rows  {weeks:>5} weeks')
        for m in hard:
            print(f'        FAIL: {m}')
            failed = True
        for m in warn:
            print(f'        warn: {m}')

    print('\nRESULT:', 'FAILURES PRESENT' if failed else 'all charts passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 2: Run it**

Run: `python3 scripts/verify_charts.py`

Expected: a line per chart. **Read the output rather than assuming it passes.** If any chart reports clamped weeks or duplicate `(Date, Rank)` rows, that is a real data defect in the freshly scraped CSVs and must be fixed in the data before this feature ships — the versus stats are computed directly from these rows.

- [ ] **Step 3: Commit**

```bash
git add scripts/verify_charts.py
git commit -m "Add chart data integrity verification script"
```

---

### Task 8: Final verification and data commit

Spec verification items 3 and 4, plus committing the five scraped CSVs, which are still untracked.

**Files:**
- Create: `tests/test_routes.py`
- Commit: `data/adult_contemporary.csv`, `data/adult_pop_airplay.csv`, `data/alternative_airplay.csv`, `data/country_airplay.csv`, `data/rhythmic_airplay.csv`

- [ ] **Step 1: Write the route walk**

Create `tests/test_routes.py`:

```python
"""Every route loads. Guards the closure late-binding failure mode, where all
loop-registered routes serve whichever chart the loop ended on — a bug that
renders perfectly and is invisible without checking each page's own heading."""
import re

import pytest


@pytest.fixture(scope='session')
def client():
    import app
    return app.app.test_client()


@pytest.fixture(scope='session')
def charts():
    import app
    return app.CHARTS


def test_every_chart_route_returns_200(client, charts):
    bad = [k for k in charts if client.get('/' + k).status_code != 200]
    assert bad == []


def test_every_chart_renders_its_own_heading(client, charts):
    """The late-binding bug's signature: several routes sharing one heading."""
    seen = {}
    for key, meta in charts.items():
        body = client.get('/' + key).get_data(as_text=True)
        h1 = re.search(r'<h1[^>]*>(.*?)</h1>', body, re.S)
        assert h1, f'{key}: no <h1>'
        seen[key] = h1.group(1).strip()
    assert len(set(seen.values())) == len(seen), f'duplicate headings: {seen}'


def test_support_routes_load(client):
    for path in ('/', '/versus', '/search', '/about'):
        assert client.get(path).status_code in (200, 302), path
```

- [ ] **Step 2: Run the whole suite**

Run: `python3 -m pytest tests/ -v`
Expected: all PASS

- [ ] **Step 3: Hand-reconcile the versus numbers**

Spec verification item 4. Silently-wrong stats are this feature's main risk, so this step is not optional and its output must be read, not skimmed.

Run:

```bash
python3 -c "
import app, versus, json
for name in ['Mariah Carey', 'The Beatles', 'Drake']:
    rows = app._versus_artist_rows('top100', name)
    s = versus.compute_artist_stats(rows)
    print(f\"{name}: entries={s['entries']} number_ones={s['number_ones']} \"
          f\"weeks_at_1={s['weeks_at_1']} best_peak={s['best_peak']} \"
          f\"first={s['first_entry']} biggest={s['biggest_hit']}\")
"
```

Reconcile against Billboard's published totals. Known reference points:
- The Beatles: 20 Hot 100 number ones.
- Mariah Carey: 19 Hot 100 number ones (this repo previously reported 82 by counting weeks instead of distinct songs — the bug fixed in `app.py:617`; if `number_ones` comes back in the dozens, that regression is back).
- Drake: best peak must be 1, first entry in 2009.

If a figure is off, do **not** adjust the number to match — find which of the four Global Constraints is being violated.

- [ ] **Step 4: Commit the scraped data**

The five CSVs are 448,448 rows and still untracked. Check size first — GitHub warns above 50MB per file:

```bash
du -sh data/adult_contemporary.csv data/adult_pop_airplay.csv \
       data/alternative_airplay.csv data/country_airplay.csv \
       data/rhythmic_airplay.csv
```

Then:

```bash
git add data/adult_contemporary.csv data/adult_pop_airplay.csv \
        data/alternative_airplay.csv data/country_airplay.csv \
        data/rhythmic_airplay.csv
git commit -m "Add full history for five genre airplay charts"
```

- [ ] **Step 5: Add the five charts to the weekly updater**

Spec Part 2, "Weekly updates". **The spec is wrong about which file this is.** It says `auto_update_data.py:252-256`, but that file is 162 lines long and is a dead Kaggle-era path. The live updater is `scripts/fast_billboard_scraper.py`, which `.github/workflows/update-charts.yml:28` runs every Wednesday.

Verified 2026-07-30: the five new charts are **absent** from its call list, so without this step they go stale the moment they ship while the other nine keep refreshing.

Their slugs are already in the completeness map at `fast_billboard_scraper.py:127-129` with a floor of 10 (commit `46529c8`), so only the call list needs changing.

In `scripts/fast_billboard_scraper.py`, insert after the `pop-songs` line at 266:

```python
    # Genre/format airplay charts. Full histories were backfilled separately;
    # these keep them current. The completeness floor for these slugs is 10
    # rows, not their modern depth — they ran shallower in early decades.
    update_chart_data('adult-contemporary', 'data/adult_contemporary.csv', weeks_to_fetch=15)
    update_chart_data('adult-pop-songs', 'data/adult_pop_airplay.csv', weeks_to_fetch=15)
    update_chart_data('rhythmic-40', 'data/rhythmic_airplay.csv', weeks_to_fetch=15)
    update_chart_data('country-airplay', 'data/country_airplay.csv', weeks_to_fetch=15)
    update_chart_data('alternative-airplay', 'data/alternative_airplay.csv', weeks_to_fetch=15)
```

- [ ] **Step 6: Verify the updater runs**

Run: `python3 scripts/fast_billboard_scraper.py`

Expected: all 14 charts report as already current through 2026-08-01, and `git status` shows no CSV changes. This does hit Billboard over the network — if it writes rows, diff them before committing and confirm the dates are genuinely new rather than clamped duplicates (`python3 scripts/verify_charts.py` from Task 7 is the check).

- [ ] **Step 7: Commit**

```bash
git add scripts/fast_billboard_scraper.py tests/test_routes.py
git commit -m "Cover five genre airplay charts in the weekly updater"
```

- [ ] **Step 8: Push**

```bash
git pull --rebase
git push
```

The CI workflow commits `data/*.csv` on Wednesdays; rebase before pushing or the weekly bot commit will conflict.

---

## Out of Scope

Tracked here so it is not lost, but belongs in separate plans:

1. **Migrating the eight legacy chart templates onto `chart.html`.** ~300KB of near-duplicate Jinja remains. The spec's landing-page diff verification (item 2) exists for this work; it has no bearing on versus.
2. **Adding `pytest` to `requirements.txt`.** This plan introduces the first tests in the repo. `requirements.txt` is the production/Docker dependency list, so a test-only dependency does not belong in it. A `requirements-dev.txt` is the right home — deferred rather than decided here.
3. **Song-vs-song comparison and cross-chart aggregate stats.** Explicit spec non-goals.
