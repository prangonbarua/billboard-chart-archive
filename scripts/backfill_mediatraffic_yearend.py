#!/usr/bin/env python3
"""Append MediaTraffic's year-end top 40s to data/yearend.csv.

Two lists, each filed under the weekly chart it summarises:

    world_singles               tracks-YYYY.htm (singles-2003.htm for 2003)
    world_albums_mediatraffic   albums-YYYY.htm

Measured 2026-10-04: tracks 2003-2025 and albums 2003-2025, a full 1..40 every
year. The album year-end starts a year before the weekly album archive does
(albums-week01-2003 is a 404), so world_albums_mediatraffic 2003 has a year-end
list but no weekly chart to check it against.

Resumable and idempotent: a (chart, year) already in yearend.csv is skipped.
Run scripts/verify_yearend.py afterwards.

    python3 scripts/backfill_mediatraffic_yearend.py [first-year] [last-year]
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fast_mediatraffic_scraper import scrape_mediatraffic_yearend

YEAREND = Path(__file__).resolve().parent.parent / 'data' / 'yearend.csv'
COLUMNS = ['Chart', 'Year', 'Rank', 'Song', 'Artist', 'Image URL']
LISTS = {'world_singles': 'tracks', 'world_albums_mediatraffic': 'albums'}


def main(argv):
    first = int(argv[1]) if len(argv) > 1 else 2003
    last = int(argv[2]) if len(argv) > 2 else 2025
    with YEAREND.open(newline='') as f:
        have = {(r['Chart'], r['Year']) for r in csv.DictReader(f)}
    added = 0
    for key, chart in LISTS.items():
        for year in range(first, last + 1):
            if (key, str(year)) in have:
                continue
            page = 'singles' if chart == 'tracks' and year == 2003 else chart
            rows = scrape_mediatraffic_yearend(year, page)
            if rows is None:
                print(f'  {key} {year}: unavailable')
                continue
            with YEAREND.open('a', newline='') as f:
                csv.DictWriter(f, fieldnames=COLUMNS).writerows(
                    {'Chart': key, 'Year': year, 'Rank': rank, 'Song': song, 'Artist': artist, 'Image URL': ''}
                    for rank, song, artist in rows)
            added += 1
            print(f'  {key} {year}: {len(rows)} rows')
    print(f'DONE: {added} year-end lists appended -> {YEAREND}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
