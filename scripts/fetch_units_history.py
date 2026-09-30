#!/usr/bin/env python3
"""Billboard 200 album units before 2026, from two sources.

    fetch_units_history.py download [cache-dir]   # Wayback captures of HITS
    fetch_units_history.py build [cache-dir]      # -> data/albums200_units_history.csv

1. Billboard's own figure for each week's No. 1 album, 1991-05-25 onward, as
   Wikipedia's "List of Billboard 200 number-one albums of <year>" tables cite
   it: pure sales through 2014, album-equivalent units from 2015. Source=Billboard.
   Before Nielsen SoundScan (May 1991) no weekly count exists, so nothing goes
   further back.
2. HITS Daily Double's weekly top 50, 2015-2025, from Internet Archive captures
   of hitsdailydouble.com. HITS's own archive starts at 2026-01-08 (see
   fetch_hits_units.py, which covers 2026 onward). Source=HITS.

billboard.com itself is not read: its robots.txt disallows this tool's agents.

Measured at source on 2026-09-30:

- /sales_plus_streaming (2015-02 .. 2025-01) always shows the latest chart, so
  each Wayback capture is one week's chart as of the capture time. Its "Chart
  Date" is HITS's publication date; the week is read from there, never from
  the capture timestamp.
- Two layouts. 2015-2017 and some 2018 captures carry one total ("SPS Index");
  later ones add Albums / TEA / SEA. The LW and TW cells have their class names
  swapped (class *_tw holds last week), so rank is the row's position, checked
  against the TW value.
- A "Status: Building" capture is a midweek projection, not the final count,
  and is never used.
- /charts/hits-top-50/<date> (2025) is the Next.js page fetch_hits_units.py
  parses; its heading shows the latest week, its "chartDate" the real one.
- The lag from a HITS week to its Billboard 200 chart changed over the years
  (18 days in early 2015, 15 in late 2015, 8-9 later), so each HITS week is
  placed on the Billboard chart its top 10 fits best, among the Saturdays 1-25
  days on, and dropped if that fit is weak or tied.
"""
import csv
import datetime as dt
import difflib
import html as htmlmod
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_hits_units as hits  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'data' / 'albums200_units_history.csv'
BB200 = ROOT / 'data' / 'billboard200.csv'
DEFAULT_CACHE = Path('/tmp/units_history_cache')

CDX = 'https://web.archive.org/cdx/search/cdx'
WAYBACK = 'https://web.archive.org/web/{ts}id_/{url}'
UA = {'User-Agent': 'billboard-chart-archive units backfill (baruaprangon5@gmail.com)'}
WIKI_API = 'https://en.wikipedia.org/w/api.php'

FIELDS = hits.FIELDS
MIN_FIT = 7          # of HITS's top 10 found in the Billboard top 20 that week
MAX_LAG = 25


# ---------------------------------------------------------------- download

def cdx(url, match='exact'):
    r = requests.get(CDX, params={'url': url, 'matchType': match, 'filter': 'statuscode:200',
                                  'fl': 'timestamp,original'}, headers=UA, timeout=300)
    r.raise_for_status()
    return [line.split() for line in r.text.splitlines() if line.strip()]


def captures():
    """(timestamp, url) of every Wayback capture worth reading."""
    out = cdx('hitsdailydouble.com/sales_plus_streaming')
    out += [c for c in cdx('hitsdailydouble.com/charts/hits-top-50') if c[0] < '2026']
    # Dated 2025 pages: the last capture of each date is enough.
    last = {}
    for ts, url in cdx('hitsdailydouble.com/charts/hits-top-50/', 'prefix'):
        m = re.search(r'/hits-top-50/(2025-\d\d-\d\d)$', url)
        if m:
            last[m.group(1)] = max(last.get(m.group(1), (ts, url)), (ts, url))
    return sorted(set(map(tuple, out)) | set(last.values()))


def download(cache):
    """Fetch captures into cache, skipping ones that cannot show a new week.

    /sales_plus_streaming changes once a week, so once a capture shows a
    final chart dated D, captures taken before D + 7 days show the same chart.
    """
    cache.mkdir(parents=True, exist_ok=True)
    todo = captures()
    print(f'{len(todo)} captures listed', flush=True)
    s = requests.Session()
    s.headers.update(UA)
    covered_until = ''
    for i, (ts, url) in enumerate(todo):
        path = cache / f'{ts}.html'
        day = f'{ts[:4]}-{ts[4:6]}-{ts[6:8]}'
        dated = '/hits-top-50/' in url
        if not dated and day < covered_until:
            continue
        if not path.exists():
            for attempt in range(6):
                try:
                    r = s.get(WAYBACK.format(ts=ts, url=url), timeout=120)
                    if r.status_code == 200:
                        path.write_text(f'<!-- {url} -->\n' + r.text)
                        break
                    if r.status_code == 404:
                        break
                except requests.RequestException:
                    pass
                time.sleep(15 * (attempt + 1))
            time.sleep(1.5)
        if path.exists() and not dated:
            week, status, rows = parse_capture(path.read_text())
            if rows and status != 'Building' and plausible(week, ts):
                covered_until = max(covered_until, (dt.date.fromisoformat(week) + dt.timedelta(days=7)).isoformat())
        if i % 25 == 0:
            print(f'{i}/{len(todo)} {ts} covered to {covered_until}', flush=True)


# ---------------------------------------------------------------- HITS pages

_Q = r"""['"]"""
_ROWSPLIT = re.compile(r"<tr class=" + _Q + r"hits_album_chart_header_full_alt[12]" + _Q)


def _cls(seg, pattern):
    m = re.search(r"class=" + _Q + r"hits_album_chart_" + pattern + r"(?: [^'\"]*)?" + _Q + r"[^>]*>(.*?)</(?:td|span)>",
                  seg, re.S)
    return htmlmod.unescape(re.sub(r'<[^>]+>', '', m.group(1))).strip() if m else None


def parse_legacy(page):
    """(chart date, status, rows) from one /sales_plus_streaming capture.

    rows are dicts shaped like fetch_hits_units.parse_page's, ranked 1..N;
    empty when the table does not read as a clean 1..N sequence.
    """
    m = re.search(r"hits_album_chart_date_value" + _Q + r">\s*(\d\d)/(\d\d)/(\d{4})", page)
    if not m:
        return None, None, []
    chart_date = f'{m.group(3)}-{m.group(1)}-{m.group(2)}'
    s = re.search(r"hits_album_chart_version_value" + _Q + r">\s*Status:\s*([A-Za-z]+)", page)
    status = s.group(1).title() if s else ''
    rows = []
    for seg in _ROWSPLIT.split(page)[1:]:
        tw = _cls(seg, r'(?:lw_full_top|full_lw)')          # class names are swapped
        artist = _cls(seg, r'(?:item_top_full_details_artist|item_details_full_artist)')
        title = _cls(seg, r'(?:item_top_dull_details_release|item_details_release)')
        if artist and title is None and ' | ' in artist:     # 2019+: "ARTIST | TITLE"
            artist, title = (p.strip() for p in artist.split(' | ', 1))
        total = _cls(seg, r'item_top_details_full_sales')
        if not (tw and artist and title is not None and total):
            continue
        rows.append({'rank': len(rows) + 1, 'tw': tw, 'artist': artist, 'album': title,
                     'data': {'Activity': total,
                              'Albums': _cls(seg, r'item_top_details_full_sales_albums'),
                              'TEA': _cls(seg, r'item_top_details_full_sales_tea'),
                              'SEA': _cls(seg, r'item_top_details_full_sales_sea')}})
    if any(r['tw'] != str(r['rank']) for r in rows):
        return chart_date, status, []
    return chart_date, status, rows


_REF_ROW = re.compile(
    r'"this_week":(\d+),"rank":[^,]*,"artist":(' + hits._STR + r'),"album":(' + hits._STR + r'),'
    r'"label":' + hits._STR + r',"data":(?:"\$([0-9a-f]+)"|(\{[^{}]*\}))')


def parse_next_refs(page):
    """(chartDate, rows) from a 2025 Next.js page. A row's figures are either
    inline or in a separate flight line ("data":"$3a" -> 3a:{"Activity":...});
    a flight line can start a chunk, so references are looked up with the
    chunks joined on newlines, rows (whose strings can span chunks) without."""
    chunks = [json.loads(c) for c in hits._CHUNK.findall(page)]
    blob = ''.join(chunks)
    m = re.search(r'"chartDate":"(\d{4}-\d\d-\d\d)"', blob)
    refs = dict(re.findall(r'(?:^|\n)([0-9a-f]+):(\{[^\n]*\})', '\n'.join(chunks)))
    by_rank = {}
    for r in _REF_ROW.finditer(blob):
        data = refs.get(r.group(4)) if r.group(4) else r.group(5)
        if data is None:
            continue
        by_rank.setdefault(int(r.group(1)), {'rank': int(r.group(1)), 'artist': json.loads(r.group(2)),
                                             'album': json.loads(r.group(3)), 'data': json.loads(data)})
    rows = [by_rank[k] for k in sorted(by_rank)]
    if [r['rank'] for r in rows] != list(range(1, len(rows) + 1)):
        rows = []
    return (m.group(1) if m else None), rows


def parse_capture(page):
    """(HITS week, status, rows) from any cached capture, any layout."""
    if 'self.__next_f.push' in page:
        week, rows = hits.parse_page(page)
        if not rows:
            week, rows = parse_next_refs(page)
        return week, 'Final', rows
    return parse_legacy(page)


def plausible(week, ts):
    """Whether a capture taken at ts can be trusted to show week's final chart.

    It must be taken 1 to 45 days after the chart date. HITS once dated a
    2018-03-30 chart 03/30/2019. And a capture on the chart date itself can
    show a new week marked Final with a day's counting in it: 01:02 on
    2019-03-29 had Nav's Bad Habits at 28,589, against Billboard's 82,000
    for the full week.
    """
    taken = dt.date(int(ts[:4]), int(ts[4:6]), int(ts[6:8]))
    return bool(week) and taken - dt.timedelta(days=45) <= dt.date.fromisoformat(week) < taken


# ---------------------------------------------------------------- Wikipedia

MONTHS = {m: i for i, m in enumerate(
    'January February March April May June July August September October November December'.split(), 1)}


def _split_cells(line):
    """'| a || b' -> ['a', 'b'], ignoring '||' inside [[ ]] and {{ }}."""
    cells, depth, cur, i = [], 0, '', 0
    while i < len(line):
        two = line[i:i + 2]
        if two in ('[[', '{{'):
            depth += 1; cur += two; i += 2; continue
        if two in (']]', '}}'):
            depth = max(0, depth - 1); cur += two; i += 2; continue
        if two in ('||', '!!') and depth == 0:
            cells.append(cur); cur = ''; i += 2; continue
        cur += line[i]; i += 1
    cells.append(cur)
    return cells


def _cell(raw):
    """(attributes, content) of one wikitext cell."""
    depth = 0
    for i, ch in enumerate(raw):
        if raw[i:i + 2] in ('[[', '{{'):
            depth += 1
        elif raw[i:i + 2] in (']]', '}}'):
            depth -= 1
        elif ch == '|' and depth == 0 and raw[i:i + 2] != '||':
            attrs = raw[:i]
            if '=' in attrs or not attrs.strip():
                return attrs, raw[i + 1:]
            break
    return '', raw


def _plain(s):
    s = re.sub(r'<ref[^>]*/>|<ref.*?</ref>', '', s, flags=re.S)
    s = re.sub(r'\{\{(?:dagger|double-dagger|sup|efn)[^{}]*\}\}', '', s, flags=re.I)
    s = re.sub(r'\{\{Sortname\|([^|}]*)\|([^|}]*)[^}]*\}\}', r'\1 \2', s, flags=re.I)
    s = re.sub(r'\{\{(?:nowrap|sort)\|(?:[^|}]*\|)?([^{}]*)\}\}', r'\1', s, flags=re.I)
    s = re.sub(r'\[\[(?:[^|\]]*\|)?([^\]]*)\]\]', r'\1', s)
    s = re.sub(r"'{2,}|<[^>]+>", '', s)
    return htmlmod.unescape(s).strip()


def _date(s, year):
    s = _plain(re.sub(r'\{\{dts\|([^}]*)\}\}', lambda m: ' '.join(
        p for p in m.group(1).split('|') if '=' not in p), s))
    m = re.search(r'(' + '|'.join(MONTHS) + r')\s+(\d{1,2})', s)
    if not m:
        return None
    y = re.search(r'\b(1[89]\d\d|20\d\d)\b', s)
    return dt.date(int(y.group(1)) if y else year, MONTHS[m.group(1)], int(m.group(2))).isoformat()


def parse_wiki_year(wikitext, year):
    """[(chart date, album, artist, units)] from one year's No. 1 table.

    Rowspans are expanded, so a sales cell spanning weeks it did not measure
    would repeat; only cells spanning exactly one row are taken as figures,
    except that a spanning cell with no number (the pre-SoundScan grey block)
    reads as none.
    """
    out = []
    for table in re.findall(r'\{\|(.*?)\n\|\}', wikitext, re.S):
        head = table.split('\n|-', 1)[0] + '\n' + (table.split('\n|-')[1] if table.count('\n|-') and table.split('\n|-', 1)[0].count('!') < 3 else '')
        cols = [_plain(_cell(c)[1]).lower() for line in head.splitlines() if line.startswith('!')
                for c in _split_cells(line[1:])]
        cols = [c for c in cols if c]
        if not cols or 'issue date' not in cols[0]:
            continue
        try:
            units_col = next(i for i, c in enumerate(cols) if 'sales' in c or 'units' in c)
            album_col = cols.index('album')
            artist_col = next(i for i, c in enumerate(cols) if c.startswith('artist'))
        except (StopIteration, ValueError):
            continue
        carry = {}   # column -> [rows left, content, spanned]
        for row in table.split('\n|-')[1:]:
            lines = [l for l in row.strip().splitlines() if l.startswith(('|', '!'))]
            if not lines or not lines[0].startswith('!'):
                continue
            raw = [c for l in lines for c in _split_cells(l[1:])]
            cells, col, it = [], 0, iter(raw)
            while col < len(cols):
                if col in carry and carry[col][0] > 0:
                    carry[col][0] -= 1
                    cells.append((carry[col][1], carry[col][2]))
                else:
                    try:
                        attrs, content = _cell(next(it))
                    except StopIteration:
                        break
                    m = re.search(r'rowspan\s*=\s*"?(\d+)', attrs)
                    n = int(m.group(1)) if m else 1
                    if n > 1:
                        carry[col] = [n - 1, content, True]
                    cells.append((content, n > 1))
                col += 1
            if len(cells) <= units_col:
                continue
            date = _date(cells[0][0], year)
            content, spanned = cells[units_col]
            num = re.sub(r'[^\d]', '', _plain(content).split('(')[0])
            if not date or not num or spanned:
                continue
            out.append((date, _plain(cells[album_col][0]), _plain(cells[artist_col][0]), int(num)))
    return out


def wiki_year(year, session=requests):
    r = session.get(WIKI_API, headers=UA, timeout=60, params={
        'action': 'parse', 'prop': 'wikitext', 'format': 'json', 'formatversion': 2, 'redirects': 1,
        'page': f'List of Billboard 200 number-one albums of {year}'})
    return r.json().get('parse', {}).get('wikitext', '')



# ---------------------------------------------------------------- build

def load_billboard(first='1991', path=BB200):
    """date -> [(rank, song, artist)] for the Billboard 200 from `first` on."""
    out = defaultdict(list)
    with open(path, newline='') as fh:
        for r in csv.DictReader(fh):
            if r['Date'][:10] >= first:
                out[r['Date'][:10]].append((int(float(r['Rank'])), r['Song'], r['Artist']))
    return out


def official_rows(wiki, billboard):
    """Billboard's No. 1 figures, each pinned to the stored No. 1 that week.

    A figure is kept only when the stored No. 1 agrees with Wikipedia's on
    title or on lead artist; spellings differ ('Now 6' / 'Now That's What I
    Call Music! 6'), albums at No. 1 on the same date do not. Returns
    (rows, [(date, album, reason)] rejected).
    """
    rows, rejected = [], []
    for date, album, artist, units in wiki:
        top = [e for e in billboard.get(date, []) if e[0] == 1]
        if not top:
            rejected.append((date, album, 'no stored chart that date'))
            continue
        _, song, bb_artist = top[0]
        a, b = (hits.title_key(t.replace('$', 's')) for t in (album, song))
        same_title = a == b or (a and b and (a in b or b in a))
        if not same_title and hits.lead_artist(artist.replace('$', 's')) != hits.lead_artist(bb_artist.replace('$', 's')):
            rejected.append((date, album, f'stored No. 1 is {song} by {bb_artist}'))
            continue
        rows.append({'Date': date, 'Song': song, 'Artist': bb_artist, 'Rank': 1, 'Units': units,
                     'Album Sales': '', 'TEA': '', 'SEA': '', 'Source': 'Billboard',
                     'Source Week': date, 'Source Rank': 1})
    return rows, rejected


def hits_weeks(cache):
    """HITS week -> (capture, rows): the latest non-building capture of each week."""
    best = {}
    for path in sorted(cache.glob('*.html')):
        week, status, rows = parse_capture(path.read_text())
        if rows and status != 'Building' and plausible(week, path.stem):
            best[week] = (path.stem, rows)    # sorted by timestamp: later wins
    return best


def fit(rows, chart):
    """(HITS top 10 at the same Billboard rank, HITS top 10 in the Billboard top 20).

    Neighbouring weeks share most of a top 20, so overlap alone ties; exact
    rank agreement separates them, and overlap breaks what it leaves tied.
    """
    at = {hits.norm(song): rank for rank, song, _ in chart if rank <= 20}
    exact = sum(at.get(hits.norm(r['album'])) == r['rank'] for r in rows[:10])
    return exact, hits.fit(rows, chart)


def place(weeks, billboard):
    """HITS week -> Billboard chart date.

    1. Each week goes to the chart its top 10 fits best, among the Billboard
       dates 1..MAX_LAG days on; dropped if that fit is under MIN_FIT or tied.
    2. The lag is constant within an era (11, 15, then 8 days), so a week
       whose lag is a week off from both placed neighbours, while they agree,
       is moved to their lag (2023-03-10 fit Morgan Wallen's second week best
       though it carries his debut). A real era change keeps one neighbour.
    3. The weaker of two weeks landing on one date is dropped.
    Returns ({week: date}, [(week, reason)] dropped).
    """
    dates = sorted(billboard)
    cands, placed, dropped = {}, {}, []

    def lag(week, d):
        return (dt.date.fromisoformat(d) - dt.date.fromisoformat(week)).days

    for week, rows in sorted(weeks.items()):
        lo = (dt.date.fromisoformat(week) + dt.timedelta(days=1)).isoformat()
        hi = (dt.date.fromisoformat(week) + dt.timedelta(days=MAX_LAG)).isoformat()
        fits = sorted(((fit(rows, billboard[d]), d) for d in dates if lo <= d <= hi), reverse=True)
        cands[week] = fits
        if not fits or fits[0][0][1] < MIN_FIT:
            dropped.append((week, f'best fit {fits[0] if fits else None}'))
        elif len(fits) > 1 and fits[1][0] == fits[0][0]:
            dropped.append((week, f'fit tied: {fits[:2]}'))
        else:
            placed[week] = fits[0]

    order = sorted(placed)
    for i, week in enumerate(order[1:-1], 1):
        before, after = lag(order[i - 1], placed[order[i - 1]][1]), lag(order[i + 1], placed[order[i + 1]][1])
        own = lag(week, placed[week][1])
        if abs(before - after) <= 2 and abs(own - before) >= 4:
            near = [(f, d) for f, d in cands[week] if abs(lag(week, d) - before) <= 2]
            if len(near) == 1 and near[0][0][1] >= MIN_FIT:
                placed[week] = near[0]
            else:
                del placed[week]
                dropped.append((week, f'lag {own} against neighbours {before}/{after}'))

    by_date = defaultdict(list)
    for week, (f, d) in placed.items():
        by_date[d].append((f, week))
    out = {}
    for d, cs in by_date.items():
        cs.sort(reverse=True)
        if len(cs) > 1 and cs[0][0] == cs[1][0]:
            dropped += [(w, f'shares {d} with an equal fit') for _, w in cs]
            continue
        out[cs[0][1]] = d
        dropped += [(w, f'{d} fits {cs[0][1]} better') for _, w in cs[1:]]
    return out, sorted(dropped)


_PLACEHOLDER = {'variousartists': 'Various Artists', 'originalbroadwaycast': 'Original Broadway Cast',
                'originalcastrecording': 'Original Cast'}


def _unswap(r):
    """Pre-2019 HITS files compilations and cast albums as artist=<title>,
    album='VARIOUS ARTISTS' / 'ORIGINAL BROADWAY CAST' / 'SOUNDTRACK, SEASON 1'."""
    album = hits.norm(r['album'])
    if album in _PLACEHOLDER:
        return {**r, 'artist': _PLACEHOLDER[album], 'album': r['artist']}
    if album.startswith('soundtrack') and album != 'soundtrack':
        return {**r, 'artist': 'Soundtrack', 'album': f"{r['artist']} {r['album'][len('SOUNDTRACK'):]}"}
    return r


def match(rows, chart):
    """fetch_hits_units.match, then two fallbacks for what it leaves.

    1. Title prefix ('HAMILTON' / 'Hamilton: An American Musical'): the one
       unused chart entry whose title starts with HITS's, or vice versa.
    2. Misspelling ('GLOBALIZATON'): same lead artist, titles at least 0.85
       alike, and no other unused entry of that artist as close.
    Either is taken only when exactly one entry qualifies.
    """
    rows = [_unswap(r) for r in rows]
    pairs, missed = hits.match(rows, chart)
    used = {e for _, e in pairs}
    still = []
    for r in missed:
        t, a = hits.title_key(r['album']), hits.lead_artist(r['artist'])
        free = [e for e in chart if e not in used]
        cands = [e for e in free if len(t) >= 4 and
                 (hits.title_key(e[1]).startswith(t) or (len(hits.title_key(e[1])) >= 4 and t.startswith(hits.title_key(e[1]))))]
        if len(cands) != 1:
            close = [e for e in free if hits.lead_artist(e[2]) == a and
                     difflib.SequenceMatcher(None, t, hits.title_key(e[1])).ratio() >= 0.85]
            if len(close) != 1:
                close = [e for e in free if hits.title_key(e[1]) and
                         difflib.SequenceMatcher(None, t, hits.title_key(e[1])).ratio() >= 0.85 and
                         difflib.SequenceMatcher(None, a, hits.lead_artist(e[2])).ratio() >= 0.85]
            cands = close
        if len(cands) == 1:
            used.add(cands[0])
            pairs.append((r, cands[0]))
        else:
            still.append(r)
    return pairs, still


def drop_copies(weeks):
    """Drop weeks whose rows repeat the week before (HITS served a copy)."""
    order = sorted(weeks)
    bad = {b for a, b in zip(order, order[1:]) if hits.signature(weeks[a]) == hits.signature(weeks[b])}
    bad |= {a for a, b in zip(order, order[1:]) if hits.signature(weeks[a]) == hits.signature(weeks[b])}
    return {w: r for w, r in weeks.items() if w not in bad}, sorted(bad)


def build(cache):
    billboard = load_billboard()
    live = {r['Date'] for r in csv.DictReader(open(hits.OUT, newline=''))} if hits.OUT.exists() else set()

    wiki, s = [], requests.Session()
    for year in range(1991, dt.date.today().year + 1):
        wiki += parse_wiki_year(wiki_year(year, s), year)
        time.sleep(0.5)
    official, rejected = official_rows(wiki, billboard)

    captured = hits_weeks(cache)
    weeks, copies = drop_copies({w: rows for w, (_, rows) in captured.items()})
    placed, dropped = place(weeks, billboard)

    out, unmatched, lags = list(official), 0, defaultdict(int)
    for week, date in sorted(placed.items()):
        if date in live:          # fetch_hits_units.py owns these weeks
            continue
        lags[(dt.date.fromisoformat(date) - dt.date.fromisoformat(week)).days] += 1
        pairs, missed = match(weeks[week], billboard[date])
        unmatched += len(missed)
        for r, (rank, song, artist) in pairs:
            d = r['data']
            out.append({'Date': date, 'Song': song, 'Artist': artist, 'Rank': rank,
                        'Units': hits.number(d.get('Activity')), 'Album Sales': hits.number(d.get('Albums')),
                        'TEA': hits.number(d.get('TEA')), 'SEA': hits.number(d.get('SEA')),
                        'Source': 'HITS', 'Source Week': week, 'Source Rank': r['rank']})

    out.sort(key=lambda r: (r['Date'], r['Rank'], r['Source']))
    with open(OUT, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out)

    n_hits = sum(r['Source'] == 'HITS' for r in out)
    print(f'Billboard No. 1 figures: {len(official)} weeks '
          f'({official[0]["Date"]} .. {official[-1]["Date"]}), rejected {len(rejected)}')
    for r in rejected:
        print('  rejected', *r)
    print(f'HITS: {len(captured)} weeks captured, {len(copies)} copies dropped {copies}, '
          f'{len(dropped)} unplaced, {len(placed)} placed; {n_hits} rows, {unmatched} unmatched')
    for r in dropped:
        print('  unplaced', *r)
    print('HITS lag (days: weeks):', dict(sorted(lags.items())))
    print(f'-> {OUT}')



if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    cache = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_CACHE
    if cmd == 'download':
        download(cache)
    elif cmd == 'build':
        build(cache)
    else:
        sys.exit(__doc__)
