"""Fill the Hot 100 year-end years billboard.com does not hold.

billboard.com answers /charts/year-end/<year>/hot-100-songs/ for every year,
but 1958-1969 all serve 1970's ranking and 1991-2005 all serve 2006's:
Billboard clamps a missing year forward, at HTTP 200 and full depth, with no
year stated anywhere on the page. scripts/yearend_guard.py drops those copies,
which is why the site's Hot 100 year-end ran 1970-1990 and 2006-2025 only.

Billboard did publish those 27 charts. They are simply not online under that
slug, so this reads Wikipedia's transcription of them instead.

Nothing is trusted on arrival. A year is kept only if most of its titles also
appear in that year's own weekly Hot 100 data (data/hot100.csv) -- the same
test scripts/verify_yearend.py applies to the scraped years, and the one thing
a transcription of the wrong year cannot pass. That check is what makes a
second source safe to mix into the same file: it does not care where a row
came from, only that the year agrees with the weekly history already stored.

Two shapes in the Wikipedia tables will corrupt the rows if parsed naively:

  - The artist cell is merged with `rowspan` when the same act holds
    consecutive positions, so 1995 #3 "Creep" has NO artist cell of its own --
    it belongs to the TLC cell above it. Reading cells positionally shifts
    every artist below the merge up a row.
  - Titles are quoted, and a double A-side is two quoted titles joined by a
    slash ('" All I Have to Do Is Dream " / " Claudette "'). Splitting on the
    slash breaks titles that contain one, so the quoted spans are read instead
    and the first is taken -- which is also the side the weekly data lists.

    python3 scripts/backfill_yearend_wikipedia.py          # every gap year
    python3 scripts/backfill_yearend_wikipedia.py 1965     # one year
"""
from __future__ import annotations

import csv
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
YEAREND = ROOT / 'data' / 'yearend.csv'
WEEKLY = ROOT / 'data' / 'hot100.csv'
COLUMNS = ['Chart', 'Year', 'Rank', 'Song', 'Artist', 'Image URL']

CHART_KEY = 'top100'
FIRST_YEAR = 1958
LAST_YEAR = 2025

# Share of a year's titles that must appear in that year's weekly Hot 100 for
# the year to be kept. Not 100%: a year-end chart is compiled from a chart week
# window that laps into the neighbouring year, and Wikipedia's title spelling
# differs from Billboard's often enough to lose a few on any normalisation.
# 60% matches verify_yearend.MIN_OVERLAP, and a wrong year scores near zero --
# latin_songs 1996 held a 2006 list and matched none of 1996's titles.
MIN_OVERLAP = 0.60
# Below this the weekly CSV does not cover the year well enough to judge it.
MIN_WEEKS = 20
# Weeks in a full chart year, used to scale the bar by how much of the year the
# weekly CSV actually holds. 1958 is the case that needs it: the Hot 100 began
# on 1958-08-09, so 31 of that year's weeks never existed, and its year-end
# chart is largely compiled from songs no Hot 100 week can confirm. Demanding
# 60% there would reject a genuine chart for missing weeks nobody has. A wrong
# year is still caught -- it scores near zero, not near the scaled bar.
FULL_YEAR_WEEKS = 52

HEADERS = {'User-Agent': 'billboard-chart-archive/1.0 (chart history research)'}
PAGE = 'https://en.wikipedia.org/wiki/Billboard_Year-End_Hot_100_singles_of_{}'


def cell_text(cell) -> str:
    """Visible text of a cell, without footnote markers."""
    for sup in cell.find_all('sup'):
        sup.decompose()
    return cell.get_text(' ', strip=True)


def table_grid(table) -> list[list[str]]:
    """Rows of a wikitable with rowspan/colspan expanded into real cells.

    A merged cell is repeated into every row and column it covers, so row N
    always holds row N's artist even when the cell was written once above it.
    """
    grid: list[list[str]] = []
    carried: dict[int, list] = {}          # column -> [text, rows still to fill]
    for tr in table.find_all('tr'):
        cells = tr.find_all(['td', 'th'])
        if not cells:
            continue
        row: dict[int, str] = {}
        for col in sorted(carried):
            text, left = carried[col]
            row[col] = text
            carried[col][1] = left - 1
        carried = {c: v for c, v in carried.items() if v[1] > 0}

        col = 0
        for cell in cells:
            while col in row:
                col += 1
            text = cell_text(cell)
            try:
                span_r = max(1, int(cell.get('rowspan', 1)))
                span_c = max(1, int(cell.get('colspan', 1)))
            except ValueError:
                span_r = span_c = 1
            for offset in range(span_c):
                row[col + offset] = text
                if span_r > 1:
                    carried[col + offset] = [text, span_r - 1]
            col += span_c
        grid.append([row.get(i, '') for i in range(max(row) + 1)] if row else [])
    return grid


QUOTED = re.compile(r'["“”‘’]\s*(.+?)\s*["“”‘’]')


def clean_title(raw: str) -> str:
    """The first quoted title in a cell.

    Reads the quoted spans rather than splitting on '/': a double A-side is
    '" A " / " B "', but plenty of single titles contain a slash of their own.
    """
    found = QUOTED.findall(raw)
    if found:
        return found[0].strip()
    return raw.strip().strip('"“”').strip()


def parse_year(year: int, session: requests.Session) -> list[dict]:
    """(Rank, Song, Artist) rows for one year, in chart order."""
    resp = session.get(PAGE.format(year), headers=HEADERS, timeout=45)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'html.parser')
    table = soup.find('table', class_='wikitable')
    if table is None:
        raise LookupError(f'{year}: no wikitable on the page')

    rows = []
    for cells in table_grid(table):
        if len(cells) < 3 or not cells[0].strip().isdigit():
            continue
        title, artist = clean_title(cells[1]), cells[2].strip()
        if not title or not artist:
            continue
        rows.append({'Chart': CHART_KEY, 'Year': year,
                     'Rank': int(cells[0].strip()), 'Song': title,
                     'Artist': artist, 'Image URL': ''})
    return rows


def normalise(text: str) -> str:
    """Title reduced to comparable letters and digits."""
    return re.sub(r'[^a-z0-9]', '', text.lower())


def weekly_titles() -> tuple[dict[int, set[str]], dict[int, int]]:
    """Normalised Hot 100 titles per year, and how many weeks back each one."""
    per_year: dict[int, set[str]] = {}
    weeks: dict[int, set[str]] = {}
    with WEEKLY.open() as handle:
        for row in csv.DictReader(handle):
            date = row['Date']
            if len(date) < 4 or not date[:4].isdigit():
                continue
            year = int(date[:4])
            per_year.setdefault(year, set()).add(normalise(row['Song']))
            weeks.setdefault(year, set()).add(date)
    titles = {y: t for y, t in per_year.items() if len(weeks[y]) >= MIN_WEEKS}
    return titles, {y: len(weeks[y]) for y in titles}


def best_matching_year(rows, weekly: dict[int, set[str]]) -> tuple[int, float]:
    """The year whose weekly Hot 100 these titles match most closely.

    The check the overlap threshold cannot make on its own. A clamped or
    misfiled list belongs to some OTHER year and says so loudly: Billboard's
    1996 latin_songs page held a 2006 list, which matches 2006 and nothing
    else. A genuine year-end must match its own year better than any other,
    whatever share of the year the weekly data happens to cover.
    """
    titles = [normalise(r['Song']) for r in rows]
    scores = {y: sum(1 for t in titles if t in seen) / len(titles)
              for y, seen in weekly.items()}
    year = max(scores, key=lambda y: scores[y])
    return year, scores[year]


def existing_years() -> set[int]:
    """Years already stored for the Hot 100."""
    if not YEAREND.exists():
        return set()
    with YEAREND.open() as handle:
        return {int(r['Year']) for r in csv.DictReader(handle)
                if r['Chart'] == CHART_KEY and r['Year'].isdigit()}


def main(argv: list[str]) -> int:
    have = existing_years()
    if argv:
        wanted = [int(a) for a in argv]
    else:
        wanted = [y for y in range(FIRST_YEAR, LAST_YEAR + 1) if y not in have]
    if not wanted:
        print('No missing Hot 100 year-end years.')
        return 0

    weekly, covered = weekly_titles()
    print(f'{len(wanted)} year(s) to fetch: {wanted[0]}-{wanted[-1]}')

    session = requests.Session()
    keep: list[dict] = []
    rejected: list[str] = []
    for year in wanted:
        if year in have:
            print(f'  {year}  already stored, skipping')
            continue
        try:
            rows = parse_year(year, session)
        except (requests.RequestException, LookupError) as exc:
            rejected.append(f'{year}: {exc}')
            print(f'  {year}  FAILED  {exc}')
            continue

        titles = weekly.get(year)
        if not titles:
            rejected.append(f'{year}: weekly data too thin to verify')
            print(f'  {year}  REJECTED  no weekly data to check against')
            continue
        hits = sum(1 for r in rows if normalise(r['Song']) in titles)
        share = hits / len(rows) if rows else 0.0
        # Scaled by how much of the year the weekly CSV holds; see
        # FULL_YEAR_WEEKS. A full year is judged at the flat MIN_OVERLAP.
        coverage = min(1.0, covered[year] / FULL_YEAR_WEEKS)
        bar = MIN_OVERLAP * coverage
        if share < bar:
            rejected.append(f'{year}: {share:.0%} of titles in weekly data, '
                            f'needed {bar:.0%}')
            print(f'  {year}  REJECTED  {len(rows)} rows, {share:.0%} overlap '
                  f'(needed {bar:.0%})')
            continue

        owner, best = best_matching_year(rows, weekly)
        if owner != year:
            rejected.append(f'{year}: matches {owner} better '
                            f'({best:.0%} vs {share:.0%}) - not this year')
            print(f'  {year}  REJECTED  looks like {owner} ({best:.0%})')
            continue

        keep.extend(rows)
        note = '' if coverage == 1.0 else f' (bar {bar:.0%}, {covered[year]}wk)'
        print(f'  {year}  {len(rows):3d} rows  {share:.0%} overlap{note}  '
              f'#1 {rows[0]["Song"]} - {rows[0]["Artist"]}')
        time.sleep(1.0)

    if not keep:
        print('\nNothing verified; file unchanged.')
        return 1

    new = YEAREND.exists() is False
    with YEAREND.open('a', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        if new:
            writer.writeheader()
        writer.writerows(keep)

    years = sorted({r['Year'] for r in keep})
    print(f'\nAdded {len(keep)} rows across {len(years)} years to {YEAREND.name}')
    if rejected:
        print(f'Not added ({len(rejected)}):')
        for line in rejected:
            print(f'  {line}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
