"""Scrape Billboard year-end charts into data/yearend.csv.

Every year of every chart is fetched even though many are discarded: the
fabrication guard judges a year by comparing it with its neighbours, so it
cannot short-circuit on the first bad year. A fabricated run can also sit
between two real ones (hot-100-songs is real 1970-1990, fabricated 1991-2005,
real 2006-2025), so an early exit would lose the older block entirely.

Each chart's weekly page is fetched once first. A slug with no year-end
edition is answered with that page for every year asked, at full depth and
HTTP 200, so without it a chart that has no year-end chart at all yields one
arbitrary week stored as a year of history.

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


def is_weekly_url(url: str) -> bool:
    """Whether a settled URL is a weekly chart rather than a year-end one.

    A year-end-only slug has no weekly page, and asking for one redirects to
    the LATEST year-end chart: /charts/hot-100-songs/ settles at
    /charts/year-end/hot-100-songs/. Taking that as the weekly reference would
    drop the most recent year of every such chart as a fall-through, which is
    the exact opposite of the intended guard. A slug with no weekly page also
    cannot fall through to one, so there is nothing to compare against.
    """
    return '/year-end/' not in url


def fetch_weekly(slug: str, session=None, timeout: int = 25) -> list[dict]:
    """The chart's own weekly page, used only as a fall-through reference."""
    url = f'https://www.billboard.com/charts/{slug}/'
    sess = session or requests.Session()
    if session is None:
        sess.headers.update(HEADERS)
    try:
        r = sess.get(url, timeout=timeout)
    except requests.RequestException:
        return []
    if r.status_code != 200 or not is_weekly_url(r.url):
        return []
    return parse_yearend(r.text)


def scrape_chart(chart_key, slug, years, fetch=fetch_yearend, session=None,
                 weekly_rows=None):
    """Rows for every genuine year of one chart, plus the years dropped.

    Returns (rows, dropped) where dropped is a list of (year, duplicate_of).
    """
    if weekly_rows is None:
        weekly_rows = fetch_weekly(slug, session=session)
    weekly_sig = ranking_signature(weekly_rows)

    by_year, sigs = {}, {}
    for year in years:
        try:
            rows = fetch(slug, year, session=session)
        except Exception as exc:                      # noqa: BLE001
            print(f'    {year}: failed ({type(exc).__name__})', flush=True)
            continue
        by_year[year] = rows
        sigs[year] = ranking_signature(rows)
        note = ' (weekly chart)' if sigs[year] == weekly_sig else ''
        print(f'    {year}: {len(rows)} rows{note}', flush=True)
        time.sleep(0.5)

    keep = set(real_years(sigs, weekly_sig=weekly_sig))
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
