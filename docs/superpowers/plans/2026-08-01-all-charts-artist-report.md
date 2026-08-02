# All-Charts Artist Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/analyze` report an artist's history across all 16 registered charts and the full Hot 100 back to 1958, instead of the Hot 100 1990+ and Billboard 200 only.

**Architecture:** The versus feature already has the primitives — `_versus_artist_rows` filters one chart by artist with correct credit matching, and `versus.compute_artist_stats` computes the whole scorecard. This change sweeps those over the `CHARTS` registry (0.25s, measured) and server-renders a coverage table, then lazy-loads per-chart song detail from a new JSON endpoint (the all-16 detail payload is 519 KB, too large to inline).

**Tech Stack:** Flask, pandas, Jinja2, Chart.js, pytest.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-01-all-charts-artist-report-design.md`
- Run tests with `python3 -m pytest` from the repo root. Tests importing `app` load every CSV and are slow by design — use the `scope='session'` fixture pattern from `tests/test_versus_api.py`.
- No emoji or decorative glyphs anywhere in templates or code — this repo uses blank SVG rects for placeholders.
- No Claude/AI mentions in any commit message, comment, or file in this repo.
- No CSS animations or transitions. `static/paxel.css` kills them globally with `*{animation:none;transition:none}!important`; do not add styles that depend on them, and never use a base `opacity:0` that relies on an animation to reveal content.
- Stats that are `None` render as an em dash (`—`), never `0`. `None` means "not meaningful for this chart kind"; `0` means "genuinely none".
- Chart validation: any endpoint taking a `chart` param returns HTTP 400 for a key not in `CHARTS`, matching `/api/versus` (`app.py:645`).

**Correction to the spec:** the spec lists four keys nulled for `kind='artist'`. There are five — `versus.py:109` nulls `entries`, `biggest_hit`, `number_ones`, `top_10s`, `top_40s`. Use the constant `versus._ARTIST_KIND_NULLS`, not a hand-copied list.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `app.py` | `artist_chart_summaries`, `artist_chart_detail`, `/api/artist-chart`, widened `/api/artists` pool, rewired `/analyze` | Modify |
| `templates/results.html` | Coverage table, chart picker, lazy detail fetch | Modify |
| `tests/test_artist_report.py` | All tests for this feature | Create |

`versus.py` is **not** modified. Its stat math is already correct and unit-tested; this feature consumes it.

---

### Task 1: `artist_chart_summaries`

**Files:**
- Modify: `app.py` (add function near `prepare_visualization_data`, `app.py:415`)
- Test: `tests/test_artist_report.py` (create)

**Interfaces:**
- Consumes: `CHARTS`, `CHART_DATA`, `_versus_artist_rows(chart_key, artist_name)`, `versus.compute_artist_stats(rows, kind=)`
- Produces: `artist_chart_summaries(artist_name)` → `None` if the artist charted nowhere, else
  `{'charts': [ {key, label, group, depth, kind, entries, number_ones, weeks_at_1, top_10s, top_40s, best_peak, total_weeks_charted, first_entry, last_entry, biggest_hit}, ... ], 'hidden': int}`.
  `charts` is in `CHARTS` registry order. The `timeline` key from `compute_artist_stats` is **removed** — it is 7,532 points across 16 charts and the coverage table does not use it.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_artist_report.py`:

```python
"""Wiring tests for the all-charts artist report. These import app, which
loads every CSV — slow by design. Fixture artists are real rows in data/."""
import pytest


@pytest.fixture(scope='session')
def application():
    import app
    return app


def test_summaries_cover_more_than_hot100_and_albums(application):
    """The bug this feature exists to fix: the old report read two frames."""
    result = application.artist_chart_summaries('Taylor Swift')
    keys = {c['key'] for c in result['charts']}
    assert len(keys) > 2
    assert 'country_airplay' in keys, 'format charts must reach the report'


def test_summaries_only_include_charts_with_rows(application):
    result = application.artist_chart_summaries('Aaron Watson')
    for c in result['charts']:
        assert c['total_weeks_charted'] > 0, f"{c['key']} has no weeks charted"
    assert result['hidden'] == len(application.CHARTS) - len(result['charts'])


def test_summaries_preserve_registry_order(application):
    result = application.artist_chart_summaries('Taylor Swift')
    order = [k for k in application.CHARTS if k in {c['key'] for c in result['charts']}]
    assert [c['key'] for c in result['charts']] == order


def test_artist100_stats_are_none_not_zero(application):
    """An artist chart's song-level counts are booleans in disguise. Rendering
    them as 0 beside a real 0 would be a lie the em dash exists to prevent."""
    import versus
    result = application.artist_chart_summaries('Drake')
    row = next(c for c in result['charts'] if c['key'] == 'artist100')
    for key in versus._ARTIST_KIND_NULLS:
        assert row[key] is None, f'{key} should be None on an artist chart'
    assert row['best_peak'] is not None, 'best_peak is meaningful on artist charts'


def test_summaries_omit_timeline(application):
    """519 KB of timeline has no business in a 3 KB coverage table."""
    result = application.artist_chart_summaries('Taylor Swift')
    assert all('timeline' not in c for c in result['charts'])


def test_summaries_none_for_unknown_artist(application):
    assert application.artist_chart_summaries('Zzzz Not A Real Artist') is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_artist_report.py -v`
Expected: FAIL with `AttributeError: module 'app' has no attribute 'artist_chart_summaries'`

- [ ] **Step 3: Write the implementation**

Add to `app.py` immediately above `prepare_visualization_data` (`app.py:415`):

```python
def artist_chart_summaries(artist_name):
    """One artist's scorecard on every chart they appear on.

    Built on the versus primitives rather than new stat logic: the report and
    the versus scorecard must never be able to disagree about the same peak.

    `total_weeks_charted` is the "did they chart here" test, not `entries` —
    entries is nulled on artist charts, so it cannot distinguish "no rows"
    from "not a meaningful count here".
    """
    charts = []
    hidden = 0
    for key, meta in CHARTS.items():
        rows = _versus_artist_rows(key, artist_name)
        stats = versus.compute_artist_stats(rows, kind=meta['kind'])
        if not stats['total_weeks_charted']:
            hidden += 1
            continue
        stats.pop('timeline', None)
        charts.append({
            'key': key,
            'label': meta['label'],
            'group': meta['group'],
            'depth': meta['depth'],
            'kind': meta['kind'],
            **stats,
        })
    if not charts:
        return None
    return {'charts': charts, 'hidden': hidden}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_artist_report.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_artist_report.py
git commit -m "Add per-chart artist summaries across the whole registry"
```

---

### Task 2: `artist_chart_detail`

**Files:**
- Modify: `app.py` (replace `prepare_visualization_data`, `app.py:415-486`)
- Test: `tests/test_artist_report.py`

**Interfaces:**
- Consumes: `CHART_DATA`, `CHART_DT`, `CHARTS`, `artist_match_mask`
- Produces: `artist_chart_detail(artist_name, chart_key)` → `None` when the artist has no rows on that chart, else
  `{'chart': {'key', 'label', 'kind', 'depth'}, 'series': {title: [{'date': 'YYYY-MM-DD', 'rank': int}, ...]}, 'items': [{'name', 'peak', 'weeks', 'first_date', 'first_date_sort', 'is_number_one'}, ...]}`.
  `items` is sorted by weeks descending then peak ascending. `series` keys are song titles (album titles on `albums200`).

This replaces `prepare_visualization_data`, whose two defects are the `Date >= 1990-01-01` filter and the hardcoded `BILLBOARD_DATA` frame. It also replaces `prepare_album_data` (`app.py:488-541`), which is the same computation against a different frame — `albums200` is now just another `chart_key`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_artist_report.py`:

```python
def test_detail_includes_pre_1990_history(application):
    """The 1990 cutoff dropped 163,861 Hot 100 rows — 46% of that chart."""
    detail = application.artist_chart_detail('The Supremes', 'top100')
    assert detail is not None, 'a pre-1990 artist must have a Hot 100 report'
    earliest = min(p['date'] for s in detail['series'].values() for p in s)
    assert earliest < '1990-01-01'


def test_detail_reads_the_requested_chart_not_hot100(application):
    detail = application.artist_chart_detail('Aaron Watson', 'country_airplay')
    assert detail is not None
    assert detail['chart']['key'] == 'country_airplay'
    assert detail['items']


def test_detail_items_sorted_by_weeks_then_peak(application):
    detail = application.artist_chart_detail('Taylor Swift', 'top100')
    keys = [(-i['weeks'], i['peak']) for i in detail['items']]
    assert keys == sorted(keys)


def test_detail_serves_albums_for_albums200(application):
    detail = application.artist_chart_detail('Taylor Swift', 'albums200')
    assert detail['chart']['kind'] == 'album'
    assert detail['items']


def test_detail_none_when_artist_absent_from_chart(application):
    assert application.artist_chart_detail('Aaron Watson', 'globalexus') is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_artist_report.py -v`
Expected: FAIL with `AttributeError: module 'app' has no attribute 'artist_chart_detail'`

- [ ] **Step 3: Write the implementation**

In `app.py`, delete `prepare_visualization_data` (`app.py:415-486`) and `prepare_album_data` (`app.py:488-541`) and put this in their place:

```python
def artist_chart_detail(artist_name, chart_key):
    """Per-entry rank history for one artist on one chart.

    The frame comes from CHART_DATA and there is no date floor — the version
    this replaced hardcoded the Hot 100 and cut everything before 1990, which
    silently truncated 46% of that chart's history.
    """
    meta = CHARTS.get(chart_key)
    df, _dates = CHART_DATA.get(chart_key, (None, None))
    if meta is None or df is None or not len(df):
        return None

    rows = df[artist_match_mask(df['Artist'], artist_name)].copy()
    if rows.empty:
        return None
    rows['Date'] = CHART_DT[chart_key].loc[rows.index]
    rows['Rank'] = pd.to_numeric(rows['Rank'], errors='coerce')
    rows = rows.dropna(subset=['Date', 'Rank'])
    if rows.empty:
        return None

    # Casing drifts week to week in the scraped data ("The Kid LAROI" vs
    # "The Kid Laroi"), so group case-insensitively and display the spelling
    # that appears most often.
    rows['Title_Clean'] = rows['Song'].astype(str).str.strip()
    rows['Title_Lower'] = rows['Title_Clean'].str.lower()
    titles = (
        rows.groupby('Title_Lower')['Title_Clean']
        .agg(lambda x: x.mode().iloc[0] if not x.mode().empty else x.iloc[0])
    )
    rows['Title'] = rows['Title_Lower'].map(titles)

    ordered = rows.sort_values('Date')
    series = {
        title: [{'date': d.strftime('%Y-%m-%d'), 'rank': int(r)}
                for d, r in zip(grp['Date'], grp['Rank'])]
        for title, grp in ordered.groupby('Title')
    }

    agg = rows.groupby('Title').agg(
        first_date=('Date', 'min'),
        weeks=('Date', 'nunique'),
        peak=('Rank', 'min'),
    )
    items = [
        {
            'name': title,
            'peak': int(row['peak']),
            'weeks': int(row['weeks']),
            'first_date': row['first_date'].strftime('%b %Y'),
            'first_date_sort': row['first_date'].strftime('%Y-%m-%d'),
            'is_number_one': int(row['peak']) == 1,
        }
        for title, row in agg.iterrows()
    ]
    items.sort(key=lambda x: (-x['weeks'], x['peak']))

    return {
        'chart': {'key': chart_key, 'label': meta['label'],
                  'kind': meta['kind'], 'depth': meta['depth']},
        'series': series,
        'items': items,
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_artist_report.py -v`
Expected: 11 passed

`/analyze` still references the deleted functions and will fail until Task 5. That is expected; the route is rewired there.

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_artist_report.py
git commit -m "Serve per-chart artist detail with no date floor

The version this replaces read only the Hot 100 and dropped everything
before 1990 — 163,861 rows, 46% of that chart's history."
```

---

### Task 3: `/api/artist-chart` endpoint

**Files:**
- Modify: `app.py` (add route beside `/api/versus`, `app.py:640`)
- Test: `tests/test_artist_report.py`

**Interfaces:**
- Consumes: `artist_chart_detail(artist_name, chart_key)` from Task 2
- Produces: `GET /api/artist-chart?artist=<name>&chart=<key>` → 200 with the `artist_chart_detail` dict; 400 on unknown or missing `chart`; 400 on blank `artist`; 404 when the artist has no rows on that chart.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_artist_report.py`:

```python
def test_artist_chart_endpoint_returns_detail(application):
    c = application.app.test_client()
    r = c.get('/api/artist-chart?artist=Taylor+Swift&chart=country_airplay')
    assert r.status_code == 200
    body = r.get_json()
    assert body['chart']['key'] == 'country_airplay'
    assert body['items']


def test_artist_chart_endpoint_rejects_unknown_chart(application):
    c = application.app.test_client()
    assert c.get('/api/artist-chart?artist=Drake&chart=nope').status_code == 400


def test_artist_chart_endpoint_rejects_blank_artist(application):
    c = application.app.test_client()
    assert c.get('/api/artist-chart?artist=&chart=top100').status_code == 400


def test_artist_chart_endpoint_404s_when_artist_absent(application):
    c = application.app.test_client()
    r = c.get('/api/artist-chart?artist=Aaron+Watson&chart=globalexus')
    assert r.status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_artist_report.py -v`
Expected: FAIL with 404 on all four (route not registered)

- [ ] **Step 3: Write the implementation**

Add to `app.py` directly after the `api_versus` function (ends `app.py:671`):

```python
@app.route('/api/artist-chart')
@limiter.exempt
def api_artist_chart():
    """One artist's detail on one chart, for the report's chart picker.

    The report lazy-loads this instead of inlining every chart: all 16 charts'
    detail is 519 KB on a heavy artist, against ~3 KB for the coverage table.
    """
    artist_name = (request.args.get('artist') or '').strip()
    if not artist_name:
        return {'error': 'Missing artist'}, 400
    chart_key = request.args.get('chart', 'top100')
    if chart_key not in CHARTS:
        return {'error': 'Unknown chart'}, 400
    detail = artist_chart_detail(artist_name, chart_key)
    if detail is None:
        return {'error': 'No data for artist on this chart'}, 404
    return detail
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_artist_report.py -v`
Expected: 15 passed

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_artist_report.py
git commit -m "Add /api/artist-chart for lazy per-chart report detail"
```

---

### Task 4: Widen the search autocomplete pool

**Files:**
- Modify: `app.py:222-231` (the `CHART_ARTISTS` build), `app.py:591` (the `/api/artists` pool selection)
- Test: `tests/test_artist_report.py`

**Interfaces:**
- Consumes: `CHART_ARTISTS`
- Produces: module global `ALL_ARTISTS` — sorted union of every chart's artist pool, 15,152 names. `/api/artists` with no `chart` param serves it. `/api/artists?chart=<key>` is unchanged.

Without this, 12,209 artists gain a report they cannot reach: `/search`'s autocomplete serves `MODERN_ARTISTS`, which is Hot 100 1990+ only (2,943 names).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_artist_report.py`:

```python
def test_all_artists_pool_covers_every_chart(application):
    union = set()
    for names in application.CHART_ARTISTS.values():
        union |= set(names)
    assert set(application.ALL_ARTISTS) == union
    assert application.ALL_ARTISTS == sorted(application.ALL_ARTISTS)


def test_autocomplete_finds_a_pre_1990_artist(application):
    """The Supremes are reportable but absent from MODERN_ARTISTS."""
    assert 'The Supremes' not in application.MODERN_ARTISTS
    c = application.app.test_client()
    got = c.get('/api/artists?q=the+supremes').get_json()['artists']
    assert 'The Supremes' in got


def test_autocomplete_finds_a_country_only_artist(application):
    assert 'Aaron Watson' not in application.MODERN_ARTISTS
    c = application.app.test_client()
    got = c.get('/api/artists?q=aaron+watson').get_json()['artists']
    assert 'Aaron Watson' in got


def test_autocomplete_chart_scoped_pool_unchanged(application):
    """The versus page passes ?chart= and must keep its own pool."""
    c = application.app.test_client()
    got = c.get('/api/artists?chart=country_airplay&q=aaron').get_json()['artists']
    assert set(got) <= set(application.CHART_ARTISTS['country_airplay'])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_artist_report.py -v`
Expected: FAIL with `AttributeError: module 'app' has no attribute 'ALL_ARTISTS'`

- [ ] **Step 3: Write the implementation**

In `app.py`, after the `CHART_ARTISTS` loop's `del` line (`app.py:231`), add:

```python
# Every artist on any chart, for the report search box. MODERN_ARTISTS is Hot
# 100 1990+ (2,943 names) — against 15,152 here, it made 12,209 artists
# unreachable from a search box that can now report on all of them.
ALL_ARTISTS = sorted({a for names in CHART_ARTISTS.values() for a in names})
```

Then in `get_artists` change the pool line (`app.py:591`) from:

```python
    pool = CHART_ARTISTS.get(request.args.get('chart', ''), MODERN_ARTISTS)
```

to:

```python
    pool = CHART_ARTISTS.get(request.args.get('chart', ''), ALL_ARTISTS)
```

Leave `MODERN_ARTISTS` defined — `app.py:916` still uses the 1990+ Hot 100 slice for a different purpose.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_artist_report.py -v`
Expected: 19 passed

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_artist_report.py
git commit -m "Search every chart's artists, not just the Hot 100 since 1990

12,209 artists had a report and no way to reach it."
```

---

### Task 5: Rewire `/analyze` and render the coverage table

**Files:**
- Modify: `app.py:543-579` (the `analyze` route)
- Modify: `templates/results.html:485-592` (stat pills, tabs, songs/albums tables)
- Test: `tests/test_artist_report.py`

**Interfaces:**
- Consumes: `artist_chart_summaries` (Task 1), `artist_chart_detail` (Task 2)
- Produces: `results.html` rendered with `artist_name`, `coverage` (the `charts` list), `hidden_count`, `selected_key`, and `detail` (the default chart's `artist_chart_detail` result).

Default selected chart is the one with the most entries, so a country act does not land on a Hot 100 view they barely charted on. `entries` is `None` on artist charts, so sort with `(c['entries'] or 0)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_artist_report.py`:

```python
def test_analyze_renders_a_format_chart_row(application):
    c = application.app.test_client()
    r = c.post('/analyze', data={'artist_name': 'Taylor Swift'})
    assert r.status_code == 200
    assert 'Country Airplay' in r.get_data(as_text=True)


def test_analyze_works_for_a_pre_1990_artist(application):
    """This 302'd to /search with 'No results found' before this change."""
    c = application.app.test_client()
    r = c.post('/analyze', data={'artist_name': 'The Supremes'})
    assert r.status_code == 200


def test_analyze_works_for_a_country_only_artist(application):
    c = application.app.test_client()
    r = c.post('/analyze', data={'artist_name': 'Aaron Watson'})
    assert r.status_code == 200
    assert 'Country Airplay' in r.get_data(as_text=True)


def test_analyze_defaults_to_the_most_charted_chart(application):
    c = application.app.test_client()
    body = c.post('/analyze', data={'artist_name': 'Aaron Watson'}).get_data(as_text=True)
    assert 'data-selected-chart="country_airplay"' in body


def test_analyze_still_redirects_for_an_unknown_artist(application):
    c = application.app.test_client()
    r = c.post('/analyze', data={'artist_name': 'Zzzz Not A Real Artist'})
    assert r.status_code == 302
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_artist_report.py -v`
Expected: FAIL — `/analyze` raises `NameError: name 'prepare_visualization_data' is not defined` (deleted in Task 2)

- [ ] **Step 3: Rewrite the `analyze` route**

Replace `app.py:543-579` entirely with:

```python
@app.route('/analyze', methods=['POST'])
def analyze():
    artist_name = request.form.get('artist_name', '').strip()
    if not artist_name:
        flash('Please enter an artist name', 'error')
        return redirect(url_for('search'))

    try:
        summary = artist_chart_summaries(artist_name)
        if summary is None:
            flash(f'No results found for artist: {artist_name}', 'error')
            return redirect(url_for('search'))

        # Default to where they charted most, not always the Hot 100 — a
        # country act should not open on a chart they barely touched. entries
        # is None on artist charts, hence the `or 0`.
        selected = max(summary['charts'], key=lambda c: (c['entries'] or 0,
                                                         c['total_weeks_charted']))
        detail = artist_chart_detail(artist_name, selected['key'])

        return render_template(
            'results.html',
            artist_name=artist_name.title(),
            coverage=summary['charts'],
            hidden_count=summary['hidden'],
            selected_key=selected['key'],
            detail=detail,
        )
    except Exception as e:
        flash(f'An error occurred: {str(e)}', 'error')
        return redirect(url_for('search'))
```

- [ ] **Step 4: Replace the stat pills and tables in `results.html`**

In `templates/results.html`, replace the block from the stat-pill row (`results.html:487`) through the end of the albums table (`results.html:592`) with:

```html
            <div class="coverage-head">
                <h2 class="coverage-title">Chart coverage</h2>
                <span class="coverage-count">charted on {{ coverage|length }} of {{ coverage|length + hidden_count }}</span>
            </div>

            <div class="coverage-scroll">
            <table class="coverage-table" data-selected-chart="{{ selected_key|e }}">
                <thead>
                    <tr>
                        <th>Chart</th><th>Peak</th><th>Entries</th>
                        <th>#1s</th><th>Weeks</th><th>Span</th>
                    </tr>
                </thead>
                <tbody>
                    {% for c in coverage %}
                    <tr class="coverage-row{% if c.key == selected_key %} is-selected{% endif %}"
                        data-chart="{{ c.key|e }}">
                        <td class="coverage-label">{{ c.label }}</td>
                        <td>{% if c.best_peak %}#{{ c.best_peak }}{% else %}&mdash;{% endif %}</td>
                        <td>{% if c.entries is none %}&mdash;{% else %}{{ c.entries }}{% endif %}</td>
                        <td>{% if c.number_ones is none %}&mdash;{% else %}{{ c.number_ones }}{% endif %}</td>
                        <td>{{ c.total_weeks_charted }}</td>
                        <td>{{ c.first_entry[:4] }}&ndash;{{ c.last_entry[:4] }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            </div>
            {% if hidden_count %}
            <p class="coverage-note">{{ hidden_count }} chart{{ 's' if hidden_count != 1 }} with no entries {{ 'are' if hidden_count != 1 else 'is' }} hidden.</p>
            {% endif %}

            <div class="detail-head">
                <h2 class="detail-title" id="detailTitle">{{ detail.chart.label }}</h2>
                <a class="detail-download" id="detailDownload"
                   href="/download-csv/{{ artist_name|urlencode }}?chart={{ selected_key|e }}">Download CSV</a>
            </div>

            <div id="detailTable">
                <h3 class="detail-subtitle" id="detailCount">
                    {{ 'Albums' if detail.chart.kind == 'album' else 'Songs' }} ({{ detail['items']|length }})
                </h3>
                <table class="song-table">
                    <thead>
                        <tr><th>#</th><th>Title</th><th>Peak</th><th class="col-hide">Weeks</th><th class="col-hide">Debut</th></tr>
                    </thead>
                    <tbody>
                        {% for item in detail['items'] %}
                        <tr data-song="{{ item.name|e }}">
                            <td>{{ loop.index }}</td>
                            <td>{{ item.name }}</td>
                            <td>{% if item.is_number_one %}<strong>#1</strong>{% else %}#{{ item.peak }}{% endif %}</td>
                            <td class="col-hide"><div class="stat-val">{{ item.weeks }}</div></td>
                            <td class="col-hide"><div class="stat-val">{{ item.first_date }}</div></td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
```

Add to the page's inline `<style>` block, above the `</style>` tag. Use existing CSS variables only — no new colors, no transitions:

```css
        .coverage-head { display:flex; align-items:baseline; justify-content:space-between; gap:1rem; margin:2rem 0 0.75rem; }
        .coverage-title { font-size:1rem; font-weight:700; color:var(--text); }
        .coverage-count { font-size:0.75rem; color:var(--text-muted); }
        .coverage-scroll { overflow-x:auto; }
        .coverage-table { width:100%; border-collapse:collapse; font-size:0.85rem; }
        .coverage-table th { text-align:left; font-size:0.68rem; letter-spacing:0.08em; text-transform:uppercase; color:var(--text-muted); padding:0.5rem 0.75rem; border-bottom:1px solid var(--border); }
        .coverage-table td { padding:0.6rem 0.75rem; border-bottom:1px solid var(--border); white-space:nowrap; }
        .coverage-row { cursor:pointer; }
        .coverage-row.is-selected { background:var(--surface-hover); font-weight:700; }
        .coverage-label { white-space:nowrap; }
        .coverage-note { font-size:0.75rem; color:var(--text-muted); margin:0.5rem 0 0; }
        .detail-head { display:flex; align-items:baseline; justify-content:space-between; gap:1rem; margin:2rem 0 0.5rem; }
        .detail-title { font-size:1rem; font-weight:700; color:var(--text); }
        .detail-download { font-size:0.75rem; color:var(--text-muted); }
        .detail-subtitle { font-size:0.8rem; color:var(--text-muted); margin:0 0 0.5rem; }
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_artist_report.py tests/test_routes.py -v`
Expected: 24 passed. `test_routes.py` must stay green — it is the regression guard for every other page.

- [ ] **Step 6: Verify in the browser**

Run: `python3 app.py`, open `http://localhost:5001/search`, search `Aaron Watson`.
Expected: a coverage table opening on Country Airplay, with a hidden-charts note. Then search `The Supremes` and confirm a non-empty report reaching back before 1990.

- [ ] **Step 7: Commit**

```bash
git add app.py templates/results.html tests/test_artist_report.py
git commit -m "Report an artist's coverage across every chart they charted on"
```

---

### Task 6: Make the coverage rows drive the detail view

**Files:**
- Modify: `templates/results.html` (the `<script>` block, `results.html:633` and `switchTab` at `results.html:847-854`)
- Test: `tests/test_artist_report.py`

**Interfaces:**
- Consumes: `GET /api/artist-chart` (Task 3), the `data-chart` attributes rendered in Task 5
- Produces: no server interface. Clicking a coverage row fetches that chart's detail, re-renders the graph and table, updates the download link, and caches the response keyed by chart key.

The old `switchTab` function and both tab buttons are removed — Billboard 200 is now a coverage row, not a tab.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_artist_report.py`:

```python
def test_results_page_has_no_tab_switcher(application):
    """The Songs/Albums tabs are replaced by coverage rows."""
    c = application.app.test_client()
    body = c.post('/analyze', data={'artist_name': 'Taylor Swift'}).get_data(as_text=True)
    assert 'switchTab' not in body
    assert 'id="albumsTab"' not in body


def test_results_page_rows_carry_chart_keys(application):
    c = application.app.test_client()
    body = c.post('/analyze', data={'artist_name': 'Taylor Swift'}).get_data(as_text=True)
    assert 'data-chart="albums200"' in body
    assert 'data-chart="country_airplay"' in body
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_artist_report.py -v`
Expected: FAIL on `test_results_page_has_no_tab_switcher` — `switchTab` is still in the template

- [ ] **Step 3: Remove the tab machinery**

In `templates/results.html`, delete the `switchTab` function (`results.html:847-854`) and any remaining `#songsContent` / `#albumsContent` references in the script block, replacing the two selectors at `results.html:670-673` with a single `#detailTable tbody tr` selector.

- [ ] **Step 4: Add the picker script**

Add to the `<script>` block in `templates/results.html`, after the existing `chartData` declaration (`results.html:633`):

```javascript
        const ARTIST_NAME = {{ artist_name|tojson }};
        const detailCache = { {{ selected_key|tojson }}: {{ detail|tojson }} };
        let selectedChart = {{ selected_key|tojson }};

        async function selectChart(key) {
            if (key === selectedChart) return;
            let detail = detailCache[key];
            if (!detail) {
                const url = '/api/artist-chart?artist=' + encodeURIComponent(ARTIST_NAME)
                          + '&chart=' + encodeURIComponent(key);
                const res = await fetch(url);
                if (!res.ok) return;
                detail = await res.json();
                detailCache[key] = detail;
            }
            selectedChart = key;
            document.querySelectorAll('.coverage-row').forEach(r => {
                r.classList.toggle('is-selected', r.dataset.chart === key);
            });
            renderDetail(detail);
        }

        function renderDetail(detail) {
            const noun = detail.chart.kind === 'album' ? 'Albums' : 'Songs';
            document.getElementById('detailTitle').textContent = detail.chart.label;
            document.getElementById('detailCount').textContent =
                noun + ' (' + detail.items.length + ')';
            document.getElementById('detailDownload').href =
                '/download-csv/' + encodeURIComponent(ARTIST_NAME)
                + '?chart=' + encodeURIComponent(detail.chart.key);

            const tbody = document.querySelector('#detailTable tbody');
            tbody.innerHTML = '';
            detail.items.forEach((item, i) => {
                const tr = document.createElement('tr');
                tr.dataset.song = item.name;

                // Every cell is built with createElement/textContent: scraped
                // fields are untrusted and this table is rebuilt from JSON on
                // every chart switch, so no cell may go through innerHTML.
                const index = document.createElement('td');
                index.textContent = i + 1;
                tr.appendChild(index);

                const title = document.createElement('td');
                title.textContent = item.name;
                tr.appendChild(title);

                const peak = document.createElement('td');
                if (item.is_number_one) {
                    const strong = document.createElement('strong');
                    strong.textContent = '#1';
                    peak.appendChild(strong);
                } else {
                    peak.textContent = '#' + item.peak;
                }
                tr.appendChild(peak);

                const weeks = document.createElement('td');
                weeks.className = 'col-hide';
                const weeksVal = document.createElement('div');
                weeksVal.className = 'stat-val';
                weeksVal.textContent = item.weeks;
                weeks.appendChild(weeksVal);
                tr.appendChild(weeks);

                const firstDate = document.createElement('td');
                firstDate.className = 'col-hide';
                const firstDateVal = document.createElement('div');
                firstDateVal.className = 'stat-val';
                firstDateVal.textContent = item.first_date;
                firstDate.appendChild(firstDateVal);
                tr.appendChild(firstDate);

                tbody.appendChild(tr);
            });
            renderGraph(detail.series);
        }

        document.querySelectorAll('.coverage-row').forEach(row => {
            row.addEventListener('click', () => selectChart(row.dataset.chart));
        });
```

Then rename the existing Chart.js setup into a `renderGraph(series)` function that destroys the previous chart instance before building a new one — without the destroy, each chart switch leaks a canvas and the tooltips of every previously-viewed chart stack up:

```javascript
        let rankChart = null;
        function renderGraph(series) {
            if (rankChart) { rankChart.destroy(); rankChart = null; }
            // ... existing Chart.js dataset construction, reading `series`
            //     instead of the old `chartData` global ...
        }
```

Call `renderGraph({{ detail['series']|tojson }})` on page load in place of the old initialisation that read `chartData`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest tests/ -v`
Expected: all tests pass, including `test_routes.py` and `test_versus_api.py`

- [ ] **Step 6: Verify the interaction in the browser**

Run: `python3 app.py`, open `http://localhost:5001/search`, search `Taylor Swift`.
Expected, checked in order:
1. The page opens on the Hot 100 with a populated graph and song table.
2. Clicking the Billboard 200 row re-renders the table headed "Albums (N)" and redraws the graph.
3. Clicking back to the Hot 100 is instant — the second fetch is served from cache (confirm in the Network tab: one request per chart, not per click).
4. The Download CSV link's `?chart=` matches the highlighted row.
5. The Artist 100 row shows em dashes for entries and #1s, not zeroes.

- [ ] **Step 7: Commit**

```bash
git add templates/results.html tests/test_artist_report.py
git commit -m "Drive the report's detail view from the coverage rows"
```

---

## Self-Review

**Spec coverage.** Every spec section maps to a task: `artist_chart_summaries` → Task 1; `artist_chart_detail` and the deleted 1990 filter → Task 2; `/api/artist-chart` → Task 3; the widened `/api/artists` pool → Task 4; the coverage table, hidden-chart note, default chart and removed tabs → Tasks 5 and 6; `?chart=` on the download link → Task 6, using the existing `app.py:1866` support with no backend change. The em-dash-not-zero rule is enforced in the Task 5 template and tested in Task 1.

**Placeholders.** One deliberate ellipsis, in Task 6 Step 4's `renderGraph` — the existing Chart.js dataset construction is being moved, not written, so reproducing it here would be a stale copy of code the implementer can already see at `results.html:633`. The surrounding destroy/rebuild logic that is new is given in full.

**Type consistency.** `artist_chart_detail` returns `items` (not `songs`) and `series` (not `chart_data`) throughout Tasks 2, 3, 5 and 6. `total_weeks_charted` is the charted-here predicate in both Task 1's implementation and its test. `versus._ARTIST_KIND_NULLS` is referenced rather than hand-copied, which is what caught the spec's four-versus-five discrepancy noted under Global Constraints.
