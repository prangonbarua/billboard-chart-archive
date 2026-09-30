#!/usr/bin/env python3
"""Weekly album units for the Billboard 200, from HITS Daily Double's Top 50.

    fetch_hits_units.py [first-week] [last-week]

Writes data/albums200_units.csv: one row per Billboard 200 entry that HITS
reported, keyed by the Billboard chart date and the Billboard title and artist
exactly as data/billboard200.csv stores them, so the page can join on them.

These are HITS figures, not Billboard's. HITS ranks by its own measure and its
order differs from the Billboard 200's, so every row is labelled Source=HITS.

Measured at source on 2026-09-29:

- Each week is https://www.hitsdailydouble.com/charts/hits-top-50/<Thursday>,
  Thursday being the end of the tracking week. That week is the Billboard 200
  dated nine days later (the Saturday after next). Checked on 37 weeks by
  top-10 overlap against the Billboard chart at +2, +9 and +16 days.
- The archive holds 2026-01-08 onward. Every Thursday of 2023-2025, and
  2026-01-01, serves a page with no chart in it.
- The page HEADING always names the latest week, whatever week was asked for.
  The week comes from "chartDate" in the page data instead.
- The rows are in Next.js flight chunks. The top rows sit in an "items" array
  and the rest as loose objects elsewhere, so every row object is matched
  wherever it is and deduplicated by rank.
- 2026-02-05 is served as an exact copy of 2026-02-12, units and all. Only the
  02-12 copy fits the Billboard chart nine days on (J. Cole's The Fall-Off
  debuted on the Billboard 200 dated 2026-02-21). A copied week is resolved by
  that fit and dropped when the fit cannot tell the two apart; it is never
  stored under both dates.
"""
import csv
import datetime as dt
import json
import re
import sys
import time
import unicodedata
from collections import defaultdict
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'data' / 'albums200_units.csv'
BB200 = ROOT / 'data' / 'billboard200.csv'

BASE = 'https://www.hitsdailydouble.com/charts/hits-top-50'
HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
FIRST_WEEK = '2026-01-08'
OFFSET = dt.timedelta(days=9)

FIELDS = ['Date', 'Song', 'Artist', 'Rank', 'Units', 'Album Sales', 'TEA', 'SEA',
          'Source', 'Source Week', 'Source Rank']

_STR = r'"(?:[^"\\]|\\.)*"'
_ROW = re.compile(
    r'"last_week":(?:null|\d+|"[^"]*"),"last_week_status":(?:null|"[^"]*"),'
    r'(?:"bullet_color":[^,]*,)?"this_week":(\d+),"rank":[^,]*,'
    r'"artist":(' + _STR + r'),"album":(' + _STR + r'),"label":(' + _STR + r'),'
    r'"data":(\{[^{}]*\})')
_CHUNK = re.compile(r'self\.__next_f\.push\(\[1,(".*?")\]\)', re.S)


def parse_page(html):
    """(chartDate, rows) from one HITS page. rows are ranked 1..N or empty."""
    blob = ''.join(json.loads(c) for c in _CHUNK.findall(html))
    m = re.search(r'"chartDate":"(\d{4}-\d\d-\d\d)"', blob)
    by_rank = {}
    for r in _ROW.finditer(blob):
        rank = int(r.group(1))
        by_rank.setdefault(rank, {
            'rank': rank,
            'artist': json.loads(r.group(2)),
            'album': json.loads(r.group(3)),
            'data': json.loads(r.group(5)),
        })
    rows = [by_rank[k] for k in sorted(by_rank)]
    # A hole in the rank sequence means a row the pattern missed: refuse the
    # week rather than store a chart with a gap in it.
    if [r['rank'] for r in rows] != list(range(1, len(rows) + 1)):
        return (m.group(1) if m else None), []
    return (m.group(1) if m else None), rows


def fetch_week(week, session=requests):
    r = session.get(f'{BASE}/{week}', headers=HEADERS, timeout=30)
    if r.status_code != 200:
        return None
    served, rows = parse_page(r.text)
    if served != week or not rows:
        return None
    return rows


def number(s):
    s = str(s or '').replace(',', '').strip()
    return int(s) if s.isdigit() else ''


def norm(s):
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode()
    s = s.casefold().replace('&', ' and ')
    return re.sub(r'[^a-z0-9]', '', s)


_TAG = re.compile(r'\((?:ep|soundtrack|original[^)]*soundtrack|mixtape)\)', re.I)


def title_key(s):
    """Title with Billboard's format tags and vol./pt. spellings folded away."""
    s = _TAG.sub(' ', str(s))
    s = re.sub(r'\bvol(?:ume)?\b\.?', ' volume ', s, flags=re.I)
    s = re.sub(r'\b(?:pt|part)\b\.?', ' part ', s, flags=re.I)
    return norm(s)


def lead_artist(s):
    """First credited act, so 'X & Y' and 'X feat. Y' match HITS's 'X'."""
    return norm(re.split(r'\s+(?:&|feat\.?|featuring|with|x|and)\s+|,\s*',
                         str(s), maxsplit=1, flags=re.I)[0])


def load_billboard(path=BB200):
    """date -> [(rank, song, artist)] for the Billboard 200."""
    out = defaultdict(list)
    with open(path, newline='') as fh:
        for r in csv.DictReader(fh):
            if r['Date'][:10] >= '2026':
                out[r['Date'][:10]].append((int(float(r['Rank'])), r['Song'], r['Artist']))
    return out


def fit(rows, chart):
    """How many of HITS's top 10 are in that Billboard chart's top 20."""
    top = {norm(song) for rank, song, _ in chart if rank <= 20}
    return sum(norm(r['album']) in top for r in rows[:10])


def signature(rows):
    return [(r['artist'], r['album'], r['data'].get('Activity')) for r in rows]


def drop_copied_weeks(weeks, billboard):
    """Resolve any week served as an exact copy of its neighbour.

    Keeps the copy whose Billboard fit is strictly better and drops the other;
    drops both if the fit ties, since then nothing says which date is real.
    Returns (kept weeks, list of (week, reason) dropped).
    """
    order = sorted(weeks)
    dropped = {}
    for a, b in zip(order, order[1:]):
        if signature(weeks[a]) != signature(weeks[b]):
            continue
        fa = fit(weeks[a], billboard.get(_bb_date(a), []))
        fb = fit(weeks[b], billboard.get(_bb_date(b), []))
        if fa > fb:
            dropped[b] = f'copy of {a} (fit {fb} < {fa})'
        elif fb > fa:
            dropped[a] = f'copy of {b} (fit {fa} < {fb})'
        else:
            dropped[a] = dropped[b] = f'{a} and {b} identical, fit tied at {fa}'
    return {w: r for w, r in weeks.items() if w not in dropped}, sorted(dropped.items())


def _bb_date(week):
    return (dt.date.fromisoformat(week) + OFFSET).isoformat()


def match(rows, chart):
    """Pair each HITS row with its Billboard 200 row that week.

    In order, each tried only if the one before found nothing:
    1. title and lead artist, after folding Billboard's (EP)/(Soundtrack) tags
       and vol./pt. spellings;
    2. title alone, when exactly one Billboard entry carries it;
    3. same lead artist, one title containing the other ('Curtain Call' /
       'Curtain Call: The Hits'), when exactly one of that artist's entries
       fits.
    Soundtracks are swapped first: HITS files them as artist=<title>,
    album='SOUNDTRACK', where Billboard has song=<title>, artist='Soundtrack'.
    A Billboard entry is used at most once, so two albums never share units.
    Returns (matched [(hits_row, (rank, song, artist))], unmatched hits rows).
    """
    by_both, by_title, by_artist = {}, defaultdict(list), defaultdict(list)
    for entry in chart:
        _, song, artist = entry
        by_both[(title_key(song), lead_artist(artist))] = entry
        by_title[title_key(song)].append(entry)
        by_artist[lead_artist(artist)].append(entry)
    matched, unmatched, used = [], [], set()
    for r in rows:
        title, artist = r['album'], r['artist']
        if norm(title) == 'soundtrack':
            title, artist = artist, 'Soundtrack'
        t, a = title_key(title), lead_artist(artist)
        entry = by_both.get((t, a))
        if entry is None and len(by_title.get(t, [])) == 1:
            entry = by_title[t][0]
        if entry is None and t:
            fits = [e for e in by_artist.get(a, [])
                    if t in title_key(e[1]) or title_key(e[1]) in t]
            if len(fits) == 1:
                entry = fits[0]
        if entry is None or entry in used:
            unmatched.append(r)
            continue
        used.add(entry)
        matched.append((r, entry))
    return matched, unmatched


def thursdays(first, last):
    d = dt.date.fromisoformat(first)
    while d.isoformat() <= last:
        yield d.isoformat()
        d += dt.timedelta(days=7)


def main(argv):
    first = argv[0] if argv else FIRST_WEEK
    today = dt.date.today()
    last = argv[1] if len(argv) > 1 else (today - dt.timedelta(days=(today.weekday() - 3) % 7)).isoformat()

    billboard = load_billboard()
    weeks, missing = {}, []
    session = requests.Session()
    for week in thursdays(first, last):
        rows = fetch_week(week, session)
        if rows:
            weeks[week] = rows
        else:
            missing.append(week)
        print(f'{week}: {len(rows) if rows else 0} rows', flush=True)
        time.sleep(1)

    weeks, dropped = drop_copied_weeks(weeks, billboard)

    out, unmatched, pending = [], 0, []
    for week in sorted(weeks):
        chart = billboard.get(_bb_date(week))
        if not chart:
            pending.append(week)   # Billboard has not published that chart yet
            continue
        pairs, missed = match(weeks[week], chart)
        unmatched += len(missed)
        for r, (rank, song, artist) in pairs:
            d = r['data']
            out.append({'Date': _bb_date(week), 'Song': song, 'Artist': artist, 'Rank': rank,
                        'Units': number(d.get('Activity')), 'Album Sales': number(d.get('Albums')),
                        'TEA': number(d.get('TEA')), 'SEA': number(d.get('SEA')),
                        'Source': 'HITS', 'Source Week': week, 'Source Rank': r['rank']})

    out.sort(key=lambda r: (r['Date'], r['Rank']))
    with open(OUT, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out)

    print(f'\n{len(out)} rows over {len({r["Date"] for r in out})} Billboard weeks -> {OUT}')
    print(f'unmatched HITS rows: {unmatched}')
    print(f'no chart served: {missing}')
    print(f'dropped copies: {dropped}')
    print(f'Billboard chart not out yet: {pending}')


if __name__ == '__main__':
    main(sys.argv[1:])
