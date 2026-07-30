#!/usr/bin/env python3
"""Find a Billboard chart's true first week.

Billboard serves dates from before a chart launched by returning that chart's
earliest week under whatever date you asked for, with no redirect and no date
anywhere in the page. A single response therefore cannot tell you whether the
date you asked for is real.

The one usable signal is content: every pre-launch date returns an identical
ranking. So the true first week is the LATEST date whose ranking still matches
a date known to predate the chart. Binary search finds it in ~11 requests
instead of scanning thousands of weeks.
"""

import hashlib
import sys
import time
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                         'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'}

# A date every chart here comfortably postdates, used to capture the clamp value.
PREHISTORY = '1950-01-07'
# A date every chart here comfortably predates, used as the search ceiling.
MODERN = '2024-06-01'


def signature(slug, date, session, retries=3):
    """Hash of the week's full (rank, song, artist) ordering, or None."""
    url = f'https://www.billboard.com/charts/{slug}/{date}/'
    for attempt in range(1, retries + 1):
        try:
            r = session.get(url, headers=HEADERS, timeout=20)
            soup = BeautifulSoup(r.text, 'html.parser')
            rows = soup.find_all('div', class_='o-chart-results-list-row-container')
            if not rows:
                return None, 0
            parts = []
            for row in rows:
                cells = [c.get_text(strip=True) for c in row.find_all('li')]
                parts.append('|'.join(cells[:4]))
            blob = '\n'.join(parts)
            return hashlib.sha1(blob.encode()).hexdigest(), len(rows)
        except requests.RequestException:
            time.sleep(2 * attempt)
    return None, 0


def saturdays(start, end):
    d = datetime.strptime(start, '%Y-%m-%d')
    d += timedelta(days=(5 - d.weekday()) % 7)   # advance to Saturday
    stop = datetime.strptime(end, '%Y-%m-%d')
    out = []
    while d <= stop:
        out.append(d.strftime('%Y-%m-%d'))
        d += timedelta(days=7)
    return out


def find_start(slug, session):
    weeks = saturdays(PREHISTORY, MODERN)
    clamp, depth0 = signature(slug, weeks[0], session)
    if clamp is None:
        return None, 'no data at prehistory date; chart may not serve archives'

    modern_sig, _ = signature(slug, weeks[-1], session)
    if modern_sig == clamp:
        return None, 'modern week matches clamp; cannot bracket'

    # Invariant: weeks[lo] is clamped, weeks[hi] is not.
    lo, hi = 0, len(weeks) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        sig, _ = signature(slug, weeks[mid], session)
        if sig == clamp or sig is None:
            lo = mid
        else:
            hi = mid
        time.sleep(1)

    # weeks[lo] is the last week still showing the clamp ranking, i.e. the
    # chart's real first week.
    return weeks[lo], f'{depth0} rows at launch'


def main():
    slugs = sys.argv[1:] or ['adult-contemporary', 'alternative-airplay',
                             'country-airplay', 'rhythmic-40', 'adult-pop-songs']
    session = requests.Session()
    print(f'{"chart":24} {"first week":12} note')
    print('-' * 70)
    for slug in slugs:
        start, note = find_start(slug, session)
        print(f'{slug:24} {start or "-":12} {note}')


if __name__ == '__main__':
    main()
