# Year-End Charts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Billboard's year-end editions to every chart that has one, as a second view on the existing chart pages, with no fabricated year reachable in the data or through a URL.

**Architecture:** A standalone scraper walks every year of every chart, hashes each year's full ranking, and keeps only the latest year in each run of identical hashes. Surviving rows land in one combined `data/yearend.csv`. `app.py` loads it into two dicts keyed by the existing chart keys, and `_song_chart_page` delegates to a year-end renderer when `?view=yearend` is present, so all 20 chart routes gain the view from one insertion point.

**Tech Stack:** Python 3, Flask, pandas, requests, BeautifulSoup, pytest. All already in `requirements.txt`.

**Spec:** `docs/superpowers/specs/2026-08-03-year-end-charts-design.md`

## Global Constraints

- Repo is public with fresh history. **No mention of AI assistants or AI assistance anywhere** — not in code, comments, docs, or commit messages, and no assistant co-author trailers on commits.
- No emojis in code or output. Existing `_load_global_chart` prints a `⚠️` character; do not copy that into new code.
- No external scripts or CDN assets in templates. Chart.js is vendored at `static/js/chart.umd.js` for this reason.
- Site design: Space Grotesk, ink `#111111`, greens `#02ff9a` (bright) and `#0c492c` (dark), `border-radius: 0`. All animations and transitions are globally disabled in `static/paxel.css`; **never reintroduce a base `opacity: 0` style that relies on an animation to reveal content.**
- Billboard blocks the default requests User-Agent with 403. Every request must send the browser UA used in `scripts/fast_billboard_scraper.py`.
- Do not modify `versus.py`, `/analyze`, `/api/artist-chart`, any CSV export, `scripts/fast_billboard_scraper.py`, `.github/workflows/update-charts.yml`, or `templates/_nav.html`.
- Run everything from the repo root: `cd ~/Documents/GitHub/billboard-chart-archive`.
- Pull before pushing. A GitHub Actions bot commits `data/*.csv` weekly.

---

### Task 1: Year-end slug map

Billboard's year-end slugs are not the weekly slugs: the Hot 100 is `hot-100` weekly but `hot-100-songs` year-end. Some registered charts have no year-end edition at all. This task records the mapping once so later tasks never guess.

**Files:**
- Create: `scripts/discover_yearend_slugs.py`
- Create: `scripts/yearend_slugs.json`

**Interfaces:**
- Produces: `scripts/yearend_slugs.json`, an object mapping every key in `app.CHARTS` to a year-end slug string, or to `null` when that chart has no year-end edition.

- [ ] **Step 1: Write the discovery script**

Create `scripts/discover_yearend_slugs.py`:

```python
"""Find each registered chart's year-end slug.

Year-end slugs differ from weekly ones ('hot-100-songs' vs 'hot-100'), and
some charts have no year-end edition at all. Probing once and storing the
result keeps every later run from guessing.

A candidate is accepted only if it returns 200 AND parses to at least 10 rows.
A wrong slug 404s, but a *near* miss can return a 200 shell with no rows, and
that must not be recorded as a working slug.
"""
import json
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

HEADERS = {'User-Agent': ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                          'AppleWebKit/537.36')}
PROBE_YEAR = 2024
OUT = Path(__file__).resolve().parent / 'yearend_slugs.json'

# Hand-checked where the pattern does not hold. Everything else is guessed
# from the label by the candidate rules below.
KNOWN = {
    'top100': 'hot-100-songs',
    'albums200': 'top-billboard-200-albums',
    'artist100': 'top-artists',
    'radio': 'radio-songs',
    'digital': 'digital-song-sales',
    'streaming': 'streaming-songs',
    'global200': 'top-global-200-songs',
    'globalexus': 'top-global-excl-us-songs',
}


def candidates(key, label):
    if key in KNOWN:
        yield KNOWN[key]
    base = (label.lower()
            .replace('&', 'and').replace('/', '-').replace('.', '')
            .replace(' ', '-'))
    yield base
    yield f'{base}-songs'
    yield f'hot-{base}-songs'


def rows_for(session, slug):
    url = f'https://www.billboard.com/charts/year-end/{PROBE_YEAR}/{slug}/'
    try:
        r = session.get(url, timeout=25)
    except requests.RequestException:
        return 0
    if r.status_code != 200:
        return 0
    soup = BeautifulSoup(r.text, 'html.parser')
    return len(soup.find_all('div', class_='o-chart-results-list-row-container'))


def main():
    import app
    session = requests.Session()
    session.headers.update(HEADERS)
    found = {}
    for key, meta in app.CHARTS.items():
        hit = None
        for slug in candidates(key, meta['label']):
            n = rows_for(session, slug)
            print(f'  {key}: {slug} -> {n} rows', flush=True)
            if n >= 10:
                hit = slug
                break
        found[key] = hit
        print(f'{key}: {hit or "NO YEAR-END EDITION"}', flush=True)
    OUT.write_text(json.dumps(found, indent=2) + '\n')
    have = sum(1 for v in found.values() if v)
    print(f'\n{have} of {len(found)} charts have a year-end edition')
    print(f'wrote {OUT}')


if __name__ == '__main__':
    main()
```

- [ ] **Step 2: Run it**

Run: `python3 scripts/discover_yearend_slugs.py`
Expected: one line per chart, then a summary. Takes a few minutes; each probe is a full page fetch.

- [ ] **Step 3: Sanity-check the map by hand**

Run: `cat scripts/yearend_slugs.json`

Confirm `top100` is `hot-100-songs`. For any chart that came back `null`, open `https://www.billboard.com/charts/year-end/2024/` in a browser and check the printed list of year-end charts before accepting it as genuinely absent. If you find the real slug there, add it to `KNOWN` and re-run.

- [ ] **Step 4: Commit**

```bash
git add scripts/discover_yearend_slugs.py scripts/yearend_slugs.json
git commit -m "Map each chart to its year-end slug"
```

---

### Task 2: The fabrication guard

The core of the feature. Billboard answers any year, clamping a missing year **forward** to the next year it holds, with no year marker anywhere on the page to catch it. The only signal is that a fabricated year's ranking is byte-identical to a real year's.

**Files:**
- Create: `scripts/yearend_guard.py`
- Test: `tests/test_yearend_guard.py`

**Interfaces:**
- Produces:
  - `ranking_signature(rows) -> str | None` — rows are dicts with `Rank`, `Song`, `Artist`. Returns `None` for an empty list.
  - `real_years(year_sigs) -> list[int]` — takes `{year: signature}`, returns the genuine years, ascending.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_yearend_guard.py`:

```python
"""The year-end fabrication guard.

Billboard serves any year you ask for. A year it has no chart for is answered
with the next year it does have, at HTTP 200 with a full row count and no year
stated anywhere on the page. Observed on hot-100-songs: 1958-1969 all return
the 1970 chart, and 1991-2005 all return the 2006 chart.

So a run of consecutive years sharing one ranking signature is one real year
(the latest) plus its clamped copies.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))

from yearend_guard import ranking_signature, real_years


def rows(*titles):
    return [{'Rank': i + 1, 'Song': t, 'Artist': f'Artist {t}'}
            for i, t in enumerate(titles)]


def test_signature_is_stable_for_identical_rankings():
    assert ranking_signature(rows('a', 'b')) == ranking_signature(rows('a', 'b'))


def test_signature_differs_when_order_differs():
    assert ranking_signature(rows('a', 'b')) != ranking_signature(rows('b', 'a'))


def test_signature_of_empty_is_none():
    assert ranking_signature([]) is None


def test_forward_clamp_keeps_only_the_latest_year():
    # 1998, 1999, 2000 all serve 2001's chart.
    sigs = {1998: 'X', 1999: 'X', 2000: 'X', 2001: 'X'}
    assert real_years(sigs) == [2001]


def test_distinct_years_all_survive():
    sigs = {2020: 'A', 2021: 'B', 2022: 'C'}
    assert real_years(sigs) == [2020, 2021, 2022]


def test_fabricated_run_between_two_real_runs():
    # The observed hot-100-songs shape: real 1989-1990, fabricated 1991-2005
    # all serving 2006, then real 2007.
    sigs = {1989: 'P', 1990: 'Q'}
    sigs.update({y: 'R' for y in range(1991, 2007)})
    sigs[2007] = 'S'
    assert real_years(sigs) == [1989, 1990, 2006, 2007]


def test_non_consecutive_years_with_equal_signatures_both_survive():
    # A gap year means these are not one run, so neither can be a clamp of
    # the other. Equal signatures here would be a source oddity, not proof.
    sigs = {2010: 'A', 2012: 'A'}
    assert real_years(sigs) == [2010, 2012]


def test_years_with_no_signature_are_dropped():
    sigs = {2019: None, 2020: 'A'}
    assert real_years(sigs) == [2020]


def test_empty_input():
    assert real_years({}) == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_yearend_guard.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'yearend_guard'`

- [ ] **Step 3: Write the implementation**

Create `scripts/yearend_guard.py`:

```python
"""Tell a real year-end chart from one Billboard fabricated.

The weekly scraper reads the page's own "Week of ..." heading and rejects any
response whose served week differs from the requested one. Year-end pages
carry no equivalent: no redirect, no heading, and the canonical link strips
the year entirely. So the year cannot be verified from a single response, and
the only signal left is comparison between years.

Billboard clamps a missing year FORWARD to the next year it holds, so a run of
consecutive years sharing one ranking is one real year at the end plus its
copies. Keep the latest, drop the rest.
"""
from __future__ import annotations

import hashlib


def ranking_signature(rows) -> str | None:
    """Hash a year's full (rank, song, artist) ordering."""
    if not rows:
        return None
    parts = [f"{r.get('Rank')}|{r.get('Song')}|{r.get('Artist')}" for r in rows]
    return hashlib.sha1('\n'.join(parts).encode()).hexdigest()


def real_years(year_sigs: dict[int, str | None]) -> list[int]:
    """Genuine years, ascending, from a {year: signature} map.

    A year survives unless the NEXT year is consecutive and carries the same
    signature, which means this year is that year's clamped copy.
    """
    years = sorted(y for y, s in year_sigs.items() if s is not None)
    keep = []
    for i, year in enumerate(years):
        nxt = years[i + 1] if i + 1 < len(years) else None
        clamped = (nxt is not None
                   and nxt == year + 1
                   and year_sigs[nxt] == year_sigs[year])
        if not clamped:
            keep.append(year)
    return keep
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/test_yearend_guard.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/yearend_guard.py tests/test_yearend_guard.py
git commit -m "Add year-end fabrication guard

Billboard clamps a missing year forward to the next year it holds, at 200
with a full row count and no year anywhere on the page. Only cross-year
ranking comparison catches it: in a run of consecutive years sharing one
signature, only the latest is genuine."
```

---

### Task 3: Year-end scraper

**Files:**
- Create: `scripts/backfill_yearend.py`
- Test: `tests/test_backfill_yearend.py`

Deliberately not an extension of `scripts/backfill_chart.py`: that script's guard compares a week to its chronological predecessor, which is the wrong rule here, and it has an open bug on sparse re-runs that this must not inherit.

**Interfaces:**
- Consumes: `ranking_signature`, `real_years` from Task 2; `scripts/yearend_slugs.json` from Task 1.
- Produces:
  - `parse_yearend(html) -> list[dict]` with keys `Rank`, `Song`, `Artist`, `Image URL`
  - `fetch_yearend(slug, year, session=None, timeout=25) -> list[dict]`
  - `scrape_chart(chart_key, slug, years, fetch=fetch_yearend, session=None) -> tuple[list[dict], list[tuple[int, int]]]` returning rows (with `Chart` and `Year` added) and a list of `(dropped_year, duplicate_of_year)` pairs.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_backfill_yearend.py`:

```python
"""The scraper's parse and its use of the guard, with no network."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))

from backfill_yearend import parse_yearend, scrape_chart

ROW = '''
<div class="o-chart-results-list-row-container">
  <span class="c-label">{rank}</span>
  <h3 class="c-title">{song}</h3>
  <span class="a-no-trucate">{artist}</span>
  <img class="c-lazy-image__img" data-lazy-src="https://img/{rank}.jpg">
</div>
'''


def page(*triples):
    return '<html><body>' + ''.join(
        ROW.format(rank=i + 1, song=s, artist=a)
        for i, (s, a) in enumerate(triples)) + '</body></html>'


def test_parse_reads_every_field():
    rows = parse_yearend(page(('Lose Control', 'Teddy Swims')))
    assert rows == [{'Rank': 1, 'Song': 'Lose Control',
                     'Artist': 'Teddy Swims', 'Image URL': 'https://img/1.jpg'}]


def test_parse_keeps_chart_order():
    rows = parse_yearend(page(('A', 'X'), ('B', 'Y')))
    assert [r['Rank'] for r in rows] == [1, 2]
    assert [r['Song'] for r in rows] == ['A', 'B']


def test_parse_empty_page():
    assert parse_yearend('<html><body></body></html>') == []


def test_scrape_drops_forward_clamped_years():
    # 1998-2000 all answer with 2001's chart, which is what Billboard does.
    real = {2001: page(('New', 'Now')), 1997: page(('Old', 'Then'))}

    def fake_fetch(slug, year, session=None, timeout=25):
        if year >= 1998:
            return parse_yearend(real[2001])
        return parse_yearend(real[1997])

    rows, dropped = scrape_chart('top100', 'hot-100-songs',
                                 range(1997, 2002), fetch=fake_fetch)
    assert sorted({r['Year'] for r in rows}) == [1997, 2001]
    assert dropped == [(1998, 2001), (1999, 2001), (2000, 2001)]


def test_scrape_stamps_chart_and_year():
    def fake_fetch(slug, year, session=None, timeout=25):
        return [{'Rank': 1, 'Song': f'S{year}', 'Artist': 'A',
                 'Image URL': ''}]

    rows, dropped = scrape_chart('bubbling', 'bubbling-under-songs',
                                 [2023, 2024], fetch=fake_fetch)
    assert dropped == []
    assert {(r['Chart'], r['Year']) for r in rows} == {
        ('bubbling', 2023), ('bubbling', 2024)}


def test_scrape_survives_a_failing_year():
    def fake_fetch(slug, year, session=None, timeout=25):
        if year == 2023:
            raise RuntimeError('boom')
        return [{'Rank': 1, 'Song': f'S{year}', 'Artist': 'A', 'Image URL': ''}]

    rows, dropped = scrape_chart('top100', 'hot-100-songs',
                                 [2023, 2024], fetch=fake_fetch)
    assert sorted({r['Year'] for r in rows}) == [2024]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_backfill_yearend.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'backfill_yearend'`

- [ ] **Step 3: Write the implementation**

Create `scripts/backfill_yearend.py`:

```python
"""Scrape Billboard year-end charts into data/yearend.csv.

Every year of every chart is fetched even though many are discarded: the
fabrication guard judges a year by comparing it with its neighbours, so it
cannot short-circuit on the first bad year. A fabricated run can also sit
between two real ones (hot-100-songs is real 1970-1990, fabricated 1991-2005,
real 2006-2025), so an early exit would lose the older block entirely.

Usage:
    python3 scripts/backfill_yearend.py              # every chart
    python3 scripts/backfill_yearend.py top100       # one chart
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from yearend_guard import ranking_signature, real_years

ROOT = Path(__file__).resolve().parent.parent
SLUGS = Path(__file__).resolve().parent / 'yearend_slugs.json'
OUT = ROOT / 'data' / 'yearend.csv'
COLUMNS = ['Chart', 'Year', 'Rank', 'Song', 'Artist', 'Image URL']

FIRST_YEAR = 1958
LAST_YEAR = 2025

HEADERS = {'User-Agent': ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                          'AppleWebKit/537.36')}


def parse_yearend(html: str) -> list[dict]:
    """Chart rows from a year-end page, in chart order."""
    soup = BeautifulSoup(html, 'html.parser')
    rows = []
    for item in soup.find_all('div', class_='o-chart-results-list-row-container'):
        rank_el = item.find('span', class_='c-label')
        title_el = item.find('h3', class_='c-title')
        if not rank_el or not title_el:
            continue
        try:
            rank = int(rank_el.get_text(strip=True))
        except ValueError:
            continue
        artist_el = item.find('span', class_='a-no-trucate')
        artist = (' '.join(artist_el.get_text(' ', strip=True).split())
                  if artist_el else 'Unknown')
        img = item.find('img', class_='c-lazy-image__img')
        src = (img.get('data-lazy-src') or img.get('src') or '') if img else ''
        rows.append({'Rank': rank, 'Song': title_el.get_text(strip=True),
                     'Artist': artist, 'Image URL': src})
    return rows


def fetch_yearend(slug: str, year: int, session=None, timeout: int = 25) -> list[dict]:
    url = f'https://www.billboard.com/charts/year-end/{year}/{slug}/'
    sess = session or requests.Session()
    if session is None:
        sess.headers.update(HEADERS)
    r = sess.get(url, timeout=timeout)
    r.raise_for_status()
    return parse_yearend(r.text)


def scrape_chart(chart_key, slug, years, fetch=fetch_yearend, session=None):
    """Rows for every genuine year of one chart, plus the years dropped.

    Returns (rows, dropped) where dropped is a list of (year, duplicate_of).
    """
    by_year, sigs = {}, {}
    for year in years:
        try:
            rows = fetch(slug, year, session=session)
        except Exception as exc:                      # noqa: BLE001
            print(f'    {year}: failed ({type(exc).__name__})', flush=True)
            continue
        by_year[year] = rows
        sigs[year] = ranking_signature(rows)
        print(f'    {year}: {len(rows)} rows', flush=True)
        time.sleep(0.5)

    keep = set(real_years(sigs))
    dropped = []
    for year in sorted(y for y in sigs if sigs[y] is not None):
        if year in keep:
            continue
        dupe = next((k for k in sorted(keep) if k > year
                     and sigs[k] == sigs[year]), None)
        dropped.append((year, dupe))

    out = []
    for year in sorted(keep):
        for row in by_year[year]:
            out.append(dict(row, Chart=chart_key, Year=year))
    return out, dropped


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    slugs = json.loads(SLUGS.read_text())
    wanted = argv or [k for k, v in slugs.items() if v]

    session = requests.Session()
    session.headers.update(HEADERS)
    frames = []
    if OUT.exists():
        frames.append(pd.read_csv(OUT))

    for key in wanted:
        slug = slugs.get(key)
        if not slug:
            print(f'{key}: no year-end edition, skipping', flush=True)
            continue
        print(f'{key} ({slug}):', flush=True)
        rows, dropped = scrape_chart(key, slug,
                                     range(FIRST_YEAR, LAST_YEAR + 1),
                                     session=session)
        years = sorted({r['Year'] for r in rows})
        print(f'  kept {len(years)} years, {len(rows)} rows', flush=True)
        if years:
            print(f'  range: {years[0]}-{years[-1]}', flush=True)
        for year, dupe in dropped:
            print(f'  dropped {year}: duplicate of {dupe}', flush=True)
        if rows:
            frames.append(pd.DataFrame(rows))
        # Checkpoint after every chart, so an interrupted run keeps its work.
        if frames:
            df = pd.concat(frames, ignore_index=True)
            df = df.drop_duplicates(subset=['Chart', 'Year', 'Rank'], keep='last')
            df = df.sort_values(['Chart', 'Year', 'Rank'])
            df[COLUMNS].to_csv(OUT, index=False)
            frames = [df]
    print(f'wrote {OUT}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/test_backfill_yearend.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/backfill_yearend.py tests/test_backfill_yearend.py
git commit -m "Add year-end scraper with the fabrication guard wired in"
```

---

### Task 4: Run the scrape

**Files:**
- Create: `data/yearend.csv`
- Create: `docs/HANDOFF-year-end.md`

This is a long network run: roughly 68 years times the number of charts with a year-end edition, at about 1.5 MB per page. Budget an hour or more and run it in one sitting.

- [ ] **Step 1: Scrape the Hot 100 alone first**

Run: `python3 scripts/backfill_yearend.py top100`

Expected, matching the sweep the spec records:
```
  kept 41 years, ~4000 rows
  range: 1970-2025
  dropped 1958: duplicate of 1970
  ...
  dropped 2005: duplicate of 2006
```

**If the kept range is not 1970-1990 plus 2006-2025, stop and investigate before scraping anything else.** That range is the known-good result; a different one means the parse or the guard changed behaviour.

- [ ] **Step 2: Verify the known #1s**

Run:
```bash
python3 -c "
import pandas as pd
df = pd.read_csv('data/yearend.csv')
t = df[(df.Chart=='top100') & (df.Rank==1)].set_index('Year')['Song']
for y, expect in [(1970,'Bridge Over Troubled Water'),(1980,'Magic'),(1990,'Hold On'),(2006,'Bad Day'),(2020,'Blinding Lights'),(2025,'Die With A Smile')]:
    got = t.get(y)
    print(('OK  ' if got == expect else 'BAD '), y, repr(got))
assert not any(y in t.index for y in range(1991, 2006)), 'fabricated years present'
print('no fabricated years in CSV')
"
```
Expected: six `OK` lines and `no fabricated years in CSV`.

- [ ] **Step 3: Scrape the rest**

Run: `python3 scripts/backfill_yearend.py 2>&1 | tee /tmp/yearend-run.log`

- [ ] **Step 4: Record the result per chart**

Run:
```bash
python3 -c "
import pandas as pd
df = pd.read_csv('data/yearend.csv')
for k, g in df.groupby('Chart'):
    ys = sorted(g.Year.unique())
    print(f'{k:22s} {len(ys):3d} years  {ys[0]}-{ys[-1]}  {len(g):6d} rows')
print('total rows', len(df))
"
```

Write `docs/HANDOFF-year-end.md` capturing, in prose: the real year range per chart, every dropped year with the year it duplicated (from the log), and the guard rule. A future session must be able to tell a real gap from a scrape failure without re-deriving any of it. Follow the tone of `docs/HANDOFF-adult-rnb.md`.

- [ ] **Step 5: Commit**

```bash
git add data/yearend.csv docs/HANDOFF-year-end.md
git commit -m "Add year-end chart data for every chart with an edition"
```

---

### Task 5: Load year-end data in app.py

**Files:**
- Modify: `app.py`, immediately after the `CHART_ARTISTS` block that ends near line 258, before `def available_charts()`
- Test: `tests/test_yearend_app.py`

**Interfaces:**
- Produces:
  - `YEAREND_DATA: dict[str, pd.DataFrame]` keyed by chart key, each sorted by `Year` then `Rank`
  - `YEAREND_YEARS: dict[str, list[int]]` keyed by chart key, years descending
  - `_load_yearend() -> tuple[dict, dict]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_yearend_app.py`:

```python
"""Year-end data loads, and only genuine years reach it."""
import pytest


@pytest.fixture(scope='session')
def mod():
    import app
    return app


def test_yearend_dicts_exist(mod):
    assert isinstance(mod.YEAREND_DATA, dict)
    assert isinstance(mod.YEAREND_YEARS, dict)


def test_every_yearend_chart_is_a_registered_chart(mod):
    assert set(mod.YEAREND_DATA) <= set(mod.CHARTS)


def test_years_are_descending_and_unique(mod):
    for key, years in mod.YEAREND_YEARS.items():
        assert years == sorted(set(years), reverse=True), key


def test_years_match_the_frame(mod):
    for key, df in mod.YEAREND_DATA.items():
        assert set(df['Year']) == set(mod.YEAREND_YEARS[key]), key


def test_hot100_has_no_fabricated_years(mod):
    if 'top100' not in mod.YEAREND_YEARS:
        pytest.skip('year-end data not loaded')
    years = set(mod.YEAREND_YEARS['top100'])
    assert not (years & set(range(1991, 2006))), 'fabricated years present'
    assert not (years & set(range(1958, 1970))), 'fabricated years present'
    assert 2006 in years and 1970 in years
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_yearend_app.py -v`
Expected: FAIL, `AttributeError: module 'app' has no attribute 'YEAREND_DATA'`

- [ ] **Step 3: Add the loader**

Insert into `app.py` after the `ALL_ARTISTS` assignment and before `def available_charts()`:

```python
# ── Year-end charts ─────────────────────────────────────────────────────────
# One combined CSV rather than the per-chart files the weekly charts use: the
# whole year-end dataset is smaller than one weekly chart and every row has the
# same shape, so 20 more globals would buy nothing.
#
# Only genuine years are in the file. Billboard answers any year, clamping a
# missing one forward to the next year it holds, and the page states no year at
# all — see scripts/yearend_guard.py and docs/HANDOFF-year-end.md.
def _load_yearend():
    path = DATA_DIR / 'yearend.csv'
    if not path.exists():
        print('yearend.csv not found. Year-end views will be unavailable.')
        return {}, {}
    df = pd.read_csv(path, low_memory=False)
    df['Year'] = pd.to_numeric(df['Year'], errors='coerce')
    df['Rank'] = pd.to_numeric(df['Rank'], errors='coerce')
    df = df.dropna(subset=['Year', 'Rank'])
    df['Year'] = df['Year'].astype(int)
    df['Rank'] = df['Rank'].astype(int)

    data, years = {}, {}
    for key, group in df.groupby('Chart'):
        if key not in CHARTS:
            continue
        group = group.sort_values(['Year', 'Rank'])
        data[key] = group
        years[key] = sorted(group['Year'].unique().tolist(), reverse=True)
    print(f'Loaded {len(df)} year-end records across {len(data)} charts')
    return data, years


YEAREND_DATA, YEAREND_YEARS = _load_yearend()
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/test_yearend_app.py -v`
Expected: 5 passed

- [ ] **Step 5: Confirm nothing else broke**

Run: `python3 -m pytest tests/ -q`
Expected: all pass, including the existing route and versus tests.

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_yearend_app.py
git commit -m "Load year-end chart data at startup"
```

---

### Task 6: Year-end route and renderer

One insertion point at the top of `_song_chart_page` gives all 20 chart routes the view, including the loop-registered ones and `albums200`, with no new routes and no registry change.

**Files:**
- Modify: `app.py:1477` (top of `_song_chart_page`) and add `_yearend_chart_page` directly above it
- Test: `tests/test_yearend_routes.py`

**Interfaces:**
- Consumes: `YEAREND_DATA`, `YEAREND_YEARS` from Task 5.
- Produces: `_yearend_chart_page(chart_key)` returning a rendered response or a redirect.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_yearend_routes.py`:

```python
"""The ?view=yearend view on the existing chart routes."""
import pytest


@pytest.fixture(scope='session')
def client():
    import app
    return app.app.test_client()


@pytest.fixture(scope='session')
def mod():
    import app
    return app


def test_yearend_view_renders(client, mod):
    if 'top100' not in mod.YEAREND_YEARS:
        pytest.skip('year-end data not loaded')
    r = client.get('/top100?view=yearend')
    assert r.status_code == 200


def test_defaults_to_newest_real_year(client, mod):
    if 'top100' not in mod.YEAREND_YEARS:
        pytest.skip('year-end data not loaded')
    newest = mod.YEAREND_YEARS['top100'][0]
    r = client.get('/top100?view=yearend')
    assert str(newest).encode() in r.data


def test_specific_year_renders(client, mod):
    if 'top100' not in mod.YEAREND_YEARS:
        pytest.skip('year-end data not loaded')
    r = client.get('/top100?view=yearend&year=2020')
    assert r.status_code == 200
    assert b'Blinding Lights' in r.data


def test_fabricated_year_redirects(client, mod):
    """2000 is a year Billboard fabricates. It must never render."""
    if 'top100' not in mod.YEAREND_YEARS:
        pytest.skip('year-end data not loaded')
    r = client.get('/top100?view=yearend&year=2000')
    assert r.status_code == 302


def test_malformed_year_does_not_500(client, mod):
    if 'top100' not in mod.YEAREND_YEARS:
        pytest.skip('year-end data not loaded')
    for bad in ('abc', '', '2020.5', '-1', '99999'):
        r = client.get(f'/top100?view=yearend&year={bad}')
        assert r.status_code in (200, 302), bad


def test_weekly_view_is_unchanged(client):
    r = client.get('/top100')
    assert r.status_code == 200
    assert b'Weeks' in r.data


def test_chart_without_yearend_redirects(client, mod):
    missing = [k for k in mod.CHARTS if k not in mod.YEAREND_YEARS]
    if not missing:
        pytest.skip('every chart has year-end data')
    r = client.get(f'/{missing[0]}?view=yearend')
    assert r.status_code == 302
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_yearend_routes.py -v`
Expected: FAIL. `?view=yearend` is ignored today, so the fabricated-year and redirect tests fail with 200.

- [ ] **Step 3: Add the renderer and the delegation**

Insert directly above `def _song_chart_page(...)` in `app.py`:

```python
def _yearend_chart_page(chart_key):
    """Year-end view of a chart.

    Year-end rows have no Last Week, Peak Position or Weeks on Chart, so none
    of the weekly badges, filters or history apply — the template hides them
    under mode='yearend'.

    A year not in YEAREND_YEARS is one Billboard fabricates, so it redirects
    rather than rendering: a shared link must not be able to produce a page of
    invented history.
    """
    years = YEAREND_YEARS.get(chart_key)
    df = YEAREND_DATA.get(chart_key)
    if not years or df is None:
        flash(f"{CHARTS[chart_key]['label']} has no year-end chart", 'error')
        return redirect(url_for(chart_key))

    raw = request.args.get('year')
    selected_year = years[0]
    if raw:
        try:
            asked = int(raw)
        except ValueError:
            flash('Invalid year', 'error')
            return redirect(url_for(chart_key, view='yearend'))
        if asked not in years:
            flash(f'Billboard publishes no {asked} year-end chart for '
                  f"{CHARTS[chart_key]['label']}", 'error')
            return redirect(url_for(chart_key, view='yearend'))
        selected_year = asked

    rows = df[df['Year'] == selected_year].sort_values('Rank')
    chart_songs = [{
        'rank': int(r['Rank']),
        'song': str(r['Song']).strip() if pd.notna(r['Song']) else '',
        'artist': str(r['Artist']).strip() if pd.notna(r['Artist']) else '',
        'image_url': str(r['Image URL']) if pd.notna(r['Image URL']) else '',
        'tags': [],
    } for _, r in rows.iterrows()]

    return render_template(
        'chart.html',
        mode='yearend',
        yearend_years=years,
        selected_year=selected_year,
        chart_songs=chart_songs,
        available_dates=[],
        selected_date=None,
        grower_min=1,
        chart=CHARTS.get(chart_key, {}),
        chart_key=chart_key,
    )
```

Then make `_song_chart_page` delegate. Change its opening lines from:

```python
def _song_chart_page(source_df, available_dates, endpoint, template):
    """Shared weekly song-chart page renderer (Hot 100 and the global charts)."""
    # Get the selected date from query params (default to latest)
    selected_date = request.args.get('date', None)
```

to:

```python
def _song_chart_page(source_df, available_dates, endpoint, template):
    """Shared weekly song-chart page renderer (Hot 100 and the global charts)."""
    # Every chart route funnels through here, so the year-end view is picked up
    # for all of them from this one branch: no new routes, no registry change.
    if request.args.get('view') == 'yearend':
        return _yearend_chart_page(endpoint)

    # Get the selected date from query params (default to latest)
    selected_date = request.args.get('date', None)
```

Finally, `_song_chart_page`'s existing `render_template` call (near line 1620) must tell the template which mode it is in **and** whether this chart has a year-end edition. Without the second one the Weekly/Year-End toggle could never appear on a weekly page, so there would be no way to reach the new view. Add both keyword arguments alongside `chart_key=endpoint`:

```python
        mode='weekly',
        yearend_years=YEAREND_YEARS.get(endpoint, []),
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/test_yearend_routes.py -v`
Expected: 7 passed (some may skip if a chart lacks year-end data)

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_yearend_routes.py
git commit -m "Serve the year-end view from every chart route

One branch at the top of the shared renderer covers all 20 routes. A year
Billboard fabricates redirects instead of rendering, so a shared link cannot
produce a page of invented history."
```

---

### Task 7: Year-end mode in chart.html

**Files:**
- Modify: `templates/chart.html`

`chart.html` already has a `yearSelect` element that filters the week list by year. **Do not reuse that id.** The year-end picker is a different control; name it `yearEndSelect`.

- [ ] **Step 1: Add the view toggle**

Above the `.chart-filters` block (near line 331), add:

```html
{% if yearend_years is defined and yearend_years %}
<div class="view-toggle" role="group" aria-label="Chart view">
  <a class="filter-btn" href="{{ url_for(chart_key) }}"
     aria-pressed="{{ 'false' if mode == 'yearend' else 'true' }}">Weekly</a>
  <a class="filter-btn" href="{{ url_for(chart_key, view='yearend') }}"
     aria-pressed="{{ 'true' if mode == 'yearend' else 'false' }}">Year-End</a>
</div>
{% endif %}
```

The toggle only appears when the chart has year-end data, so a chart without an edition shows no dead control. `.filter-btn` is reused deliberately: it already carries the site's pill styling, including the `aria-pressed` active state.

- [ ] **Step 2: Gate the weekly-only controls**

Wrap the week picker (the `<select id="yearSelect">` block and the week `<select>` near lines 318-325), the `.chart-filters` block (lines 331-337) and the prev/next week buttons in:

```html
{% if mode != 'yearend' %}
  ... existing markup unchanged ...
{% endif %}
```

- [ ] **Step 3: Add the year picker**

Directly after the toggle, add:

```html
{% if mode == 'yearend' %}
<div class="chart-controls">
  <label for="yearEndSelect">Year</label>
  <select id="yearEndSelect"
          onchange="location.href='{{ url_for(chart_key, view='yearend') }}&year=' + this.value">
    {% for y in yearend_years %}
    <option value="{{ y }}" {% if y == selected_year %}selected{% endif %}>{{ y }}</option>
    {% endfor %}
  </select>
</div>
<p class="page-meta">
  Billboard's year-end archive is not continuous. Years missing from this list
  are years it does not publish, not years this site failed to collect.
</p>
{% endif %}
```

- [ ] **Step 4: Gate the row columns**

In the row markup, wrap the Last Week, Peak and Weeks cells in `{% if mode != 'yearend' %} ... {% endif %}`. Do the same for the change badge. Rank, artwork, song and artist stay in both modes.

Also gate the page heading date: replace `<span class="page-date">{{ selected_date }}</span>` with

```html
<span class="page-date">{% if mode == 'yearend' %}{{ selected_year }}{% else %}{{ selected_date }}{% endif %}</span>
```

- [ ] **Step 5: Gate the weekly JavaScript**

The scripts near line 468 read `allDates` and `selectedDate` and wire `filterWeeks`, the row filters and the song-history modal. Wrap that whole block in `{% if mode != 'yearend' %} ... {% endif %}`. In year-end mode `available_dates` is `[]`, so leaving it in would run filters against an empty week list.

Do not add a base `opacity: 0` rule to any new element. All animations are disabled site-wide, so anything starting transparent stays invisible.

- [ ] **Step 6: Check both modes render**

Run: `python3 app.py` and open:
- `http://localhost:5001/top100` — unchanged: week picker, filters, badges, working modal
- `http://localhost:5001/top100?view=yearend` — year picker 2025 down to 1970 with the 1991-2005 gap, no Last Week/Peak/Weeks columns, no filter pills
- `http://localhost:5001/top100?view=yearend&year=1970` — "Bridge Over Troubled Water" at #1
- `http://localhost:5001/top100?view=yearend&year=2000` — redirects with a flash, renders no chart

- [ ] **Step 7: Run the full suite**

Run: `python3 -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add templates/chart.html
git commit -m "Add the year-end view to the shared chart template"
```

---

### Task 8: Verify and deploy

- [ ] **Step 1: Check every chart's year-end view**

Run:
```bash
python3 -c "
import app
c = app.app.test_client()
for k in app.CHARTS:
    r = c.get(f'/{k}?view=yearend')
    has = 'yes' if k in app.YEAREND_YEARS else 'no '
    print(f'{k:22s} data={has} status={r.status_code}')
"
```
Expected: every chart with data returns 200; charts without return 302. No 500 anywhere.

- [ ] **Step 2: Confirm the weekly pages are untouched**

Run: `python3 -m pytest tests/test_routes.py tests/test_versus.py tests/test_artist_report.py -q`
Expected: all pass.

- [ ] **Step 3: Push**

```bash
git pull --rebase
git push
```

- [ ] **Step 4: Deploy**

**Ask before running this.** Deploys need explicit confirmation.

```bash
railway up --detach --service billboard-chart-archive
```

Note `.dockerignore` history: an untracked local `.dockerignore` once silently kept two CSVs out of production while git looked clean. `railway up` uploads the local directory and honours it, so check the file does not exclude `data/yearend.csv` before deploying.

- [ ] **Step 5: Verify live**

Open `https://billboard-chart-archive-production.up.railway.app/top100?view=yearend` and confirm 2025 renders, then that `&year=2000` redirects rather than showing a chart.

---

## Notes for the implementer

**The one thing that must not regress:** no fabricated year may ever reach the CSV or a rendered page. This project has twice come close to shipping invented chart history, once at 1,760 weeks. If a test in Task 2 or a check in Task 4 fails, stop and investigate rather than adjusting the expectation.

**Why the scraper fetches years it throws away:** the guard judges a year by its neighbours, and a fabricated run can sit between two real ones. An early exit on the first bad year would silently lose the entire pre-1991 block.

**Why year-end is not in the artist report:** year-end ranks and weekly ranks are not comparable on one axis. Keeping them apart is deliberate, not an oversight.
