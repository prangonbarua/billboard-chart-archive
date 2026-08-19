#!/usr/bin/env python3
"""Scrape one week of MediaTraffic's World Single Chart.

This is the first non-Billboard source in the project, so none of the
Billboard scraper's assumptions carry over. What changes, measured at source
on 2026-08-19:

  * HTTPS does not work at all. www.mediatraffic.de answers on port 80 only;
    every https:// request fails to connect. So this fetches over plaintext.

  * There is no date parameter, and therefore no clamp. Billboard serves an
    out-of-range date by returning a boundary week's rankings under the date
    you asked for, which a single response cannot reveal — the whole reason
    fast_billboard_scraper.py compares the served-week heading. MediaTraffic
    publishes each week as its own static file and returns a real HTTP 404 for
    a week that does not exist (verified: tracks-week99-2004 and
    tracks-week01-1899 both 404). The failure mode this project fears most is
    absent here by construction.

  * The rank is an IMAGE, not text. Each row's first cell is <img src="NN.jpg">
    and that number is the position. The text beside it reads "A / B", which is
    NOT this week's rank — mistaking it for one makes the page look like it
    lists songs out of order and silently mis-ranks every row. A is LAST week's
    rank and B the week before. Proved by chaining two consecutive weeks:
    in week14-1992 every row's A equals that same song's rank in week13-1992.
    Debut rows carry a new.JPG badge and no A at all, which is why the rank
    cannot be read from the text and why it cannot be inferred from row order
    either — it comes from the image and nowhere else.

  * Only the 2004-onward `tracks-week` pages state their own date ("week 01 /
    2010 - January 9"). The older `week` pages give a year and a week number
    and nothing else, so their dates would have to be derived from a
    week-numbering convention this file has not measured. Deriving them would
    be inventing dates for 2505 weeks, so this scraper covers the dated era
    only and refuses the rest rather than guessing.

Peak Position is not published anywhere on the page. It is left blank: app.py
computes debut and peak from the chart history itself (the 2026-07-29 fix), so
a blank here is honest and costs nothing downstream.
"""

import re
import time
from datetime import datetime

import requests

BASE = 'http://www.mediatraffic.de'
# The dated era. week01-2004 is the first tracks-week page the archive lists.
FIRST_DATED_YEAR = 2004

HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; chart-archive/1.0)'}

# "week 01 / 2010 - January 9". The month/day is the chart date; the year comes
# from the week label beside it.
_DATELINE = re.compile(
    r'week\s*(\d{1,2})\s*/\s*(\d{4})\s*-\s*([A-Z][a-z]+)\s+(\d{1,2})', re.I)
_ROW = re.compile(r'<tr[^>]*>(.*?)</tr>', re.S | re.I)
_CELL = re.compile(r'<t[dh][^>]*>(.*?)</t[dh]>', re.S | re.I)
_RANK_IMG = re.compile(r'src="(\d{1,3})\.jpg"', re.I)
_LASTWEEK = re.compile(r'^\s*(\d+|-)\s*/\s*(\d+|-)')
_WEEKS_ON = re.compile(r'week\s*(\d+)', re.I)


def _text(fragment):
    """Tag-stripped, entity-decoded, whitespace-collapsed cell text."""
    import html as _html
    return re.sub(r'\s+', ' ', _html.unescape(re.sub(r'<[^>]+>', ' ', fragment))).strip()


_BOLD = re.compile(r'<(b|strong)[^>]*>(.*?)</\1>', re.S | re.I)


def _title_block(cell):
    """The bold run holding 'Song - Artist'.

    Two era-specific traps, both of which produce a row that parses to
    nonsense rather than failing outright. The 2004 pages bold the title with
    <strong> and the 2010 pages with <b>, so matching only one silently drops
    every row of the other era — which surfaces as a hole in the rank sequence,
    since the ranks themselves still parse. And the 2010 pages wrap a
    platina.gif award icon in its OWN <strong>, so taking the first bold run
    blindly returns an image and no title. Hence: first bold run whose text
    actually contains the ' - ' separator.

    The label follows the title after a <br> inside the same cell, so cut
    there — otherwise it lands in the artist field.
    """
    for _tag, inner in _BOLD.findall(cell):
        head = re.split(r'<br\s*/?>', inner, maxsplit=1, flags=re.I)[0]
        text = _text(head)
        if ' - ' in text:
            return text
    return _text(re.split(r'<br\s*/?>', cell, maxsplit=1, flags=re.I)[0])


def _split_title(strong_text):
    """'Song - Artist' -> (song, artist).

    The <strong> block holds exactly the title and the credit; the label sits
    after it and is dropped by the caller. Splitting on the FIRST ' - ' is
    right for every row sampled, but a song title containing ' - ' would split
    in the wrong place, so the caller counts ambiguous rows rather than
    pretending the split is always safe.
    """
    parts = strong_text.split(' - ', 1)
    if len(parts) != 2:
        return None, None
    return parts[0].strip(), parts[1].strip()


def scrape_mediatraffic_week(year, week, session=None, timeout=30):
    """One week of the World Single Chart, or None.

    Returns (date, rows, ambiguous_titles). `rows` are dicts in the project's
    CSV shape. None means the week is genuinely unavailable — a 404, a page
    whose stated week is not the one asked for, or a rank sequence with a hole
    in it. Every one of those is a refusal, never a partial chart.
    """
    if year < FIRST_DATED_YEAR:
        raise ValueError(
            f'{year} predates the dated era: only {FIRST_DATED_YEAR}+ tracks-week '
            'pages state their own date, and deriving the rest would invent them')

    url = f'{BASE}/tracks-week{week:02d}-{year}.htm'
    get = (session or requests).get
    print(f'  📥 MediaTraffic {year} week {week:02d}...', end=' ', flush=True)
    try:
        r = get(url, headers=HEADERS, timeout=timeout)
    except requests.RequestException as e:
        print(f'✗ Network error: {e}')
        return None

    if r.status_code == 404:
        print('✗ no such week (404)')
        return None
    if r.status_code != 200:
        print(f'✗ HTTP {r.status_code}')
        return None

    html_text = r.content.decode('iso-8859-1', errors='replace')

    m = _DATELINE.search(html_text)
    if not m:
        print('✗ no date line — refusing to guess the week')
        return None
    got_week, got_year, month, day = int(m.group(1)), int(m.group(2)), m.group(3), int(m.group(4))
    # The page states its own week. This is the one guard that survives from the
    # Billboard scraper, and it is cheap, so keep it even though a static file
    # cannot clamp: it catches a mislinked or recycled page.
    if (got_week, got_year) != (week, year):
        print(f'✗ page says week {got_week}/{got_year}, not {week}/{year} — skipping')
        return None
    # The week LABEL's year is not always the date's year. "week 53 / 2004 -
    # January 1" is 2005-01-01: the last week of a chart year is dated into the
    # next calendar year. Stamping the label year instead puts that week nearly
    # twelve months early, which shows up as a chart whose weeks are 1-2 days
    # apart and land on three different weekdays. Symmetrically, a week-1 page
    # dated in December belongs to the previous year.
    date_year = got_year
    if got_week >= 52 and month.lower() == 'january':
        date_year += 1
    elif got_week <= 1 and month.lower() == 'december':
        date_year -= 1
    try:
        date = datetime.strptime(f'{month} {day} {date_year}', '%B %d %Y').strftime('%Y-%m-%d')
    except ValueError:
        print(f'✗ unparseable date "{month} {day}"')
        return None

    rows, ambiguous = [], 0
    for frag in _ROW.findall(html_text):
        cells = _CELL.findall(frag)
        if len(cells) < 3:
            continue
        rank_m = _RANK_IMG.search(cells[0])
        if not rank_m:
            continue

        meta = _text(cells[1])
        lw_m = _LASTWEEK.match(meta)
        last_week = lw_m.group(1) if lw_m and lw_m.group(1) != '-' else ''
        weeks_m = _WEEKS_ON.search(meta)

        title_text = _title_block(cells[2])
        song, artist = _split_title(title_text)
        if not song or not artist:
            continue
        if title_text.count(' - ') > 1:
            ambiguous += 1

        rows.append({
            'Date': date,
            'Rank': int(rank_m.group(1)),
            'Song': song,
            'Artist': artist,
            'Last Week': last_week,
            # Not published by MediaTraffic; app.py derives peak from history.
            'Peak Position': '',
            'Weeks on Chart': int(weeks_m.group(1)) if weeks_m else '',
        })

    if not rows:
        print('✗ no rows parsed')
        return None

    # The ranks come from sequential images, so a correct parse yields exactly
    # 1..N with no hole and no repeat. A hole means rows were dropped, and a
    # chart missing an interior rank is the silent-truncation failure this
    # project keeps hitting — so refuse the week rather than store it.
    ranks = sorted(r['Rank'] for r in rows)
    if ranks != list(range(1, len(rows) + 1)):
        missing = sorted(set(range(1, max(ranks) + 1)) - set(ranks))
        print(f'✗ rank sequence broken (missing {missing}) — skipping')
        return None

    rows.sort(key=lambda r: r['Rank'])
    print(f'✓ ({len(rows)} tracks, {date})')
    time.sleep(1)  # Be respectful — this is a small site on one host.
    return date, rows, ambiguous
