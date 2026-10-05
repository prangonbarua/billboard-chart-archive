#!/usr/bin/env python3
"""Backfill MediaTraffic's World Single Chart (or World Album Chart) to CSV.

Resumable: reads the existing CSV and skips weeks already stored, so a killed
run picks up where it stopped. Appends one week at a time, in date order when
run forward over years.

No clamp comparison here, unlike backfill_chart.py. That script drops a week
whose ordering is identical to its neighbour because Billboard serves
out-of-range dates as a boundary week under the date you asked for.
MediaTraffic cannot do that — each week is a static file and a missing week
404s — so an identical neighbour would be real data, not an artifact, and
dropping it would delete history. The integrity checks that DO apply live in
the scraper: stated week must match, rank sequence must be a complete 1..N.

Usage:
  backfill_mediatraffic.py <csv-path> [first-year] [last-year] [tracks|albums]

New weeks are appended; existing rows are never rewritten (an earlier version
rewrote the file through pandas, which turned 1 into 1.0 and CRLF into LF, so
refreshes had to run on a copy).
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fast_mediatraffic_scraper import FIRST_ALBUM_YEAR, FIRST_DATED_YEAR, scrape_mediatraffic_week

COLUMNS = ['Date', 'Rank', 'Song', 'Artist', 'Last Week', 'Peak Position', 'Weeks on Chart']


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    csv_path = Path(sys.argv[1])
    chart = sys.argv[4] if len(sys.argv) > 4 else 'tracks'
    first_year = int(sys.argv[2]) if len(sys.argv) > 2 else (
        FIRST_ALBUM_YEAR if chart == 'albums' else FIRST_DATED_YEAR)
    last_year = int(sys.argv[3]) if len(sys.argv) > 3 else 2026

    have, newline = set(), '\r\n'
    if csv_path.exists():
        with open(csv_path, newline='') as f:
            first = f.readline()
            newline = '\r\n' if first.endswith('\r\n') else '\n'
            have = {row['Date'] for row in csv.DictReader(f, fieldnames=COLUMNS)}
    else:
        with open(csv_path, 'w', newline='') as f:
            csv.writer(f, lineterminator=newline).writerow(COLUMNS)

    fetched = missing = ambiguous_total = n_rows = 0
    for year in range(first_year, last_year + 1):
        # Week 53 exists in some years and 404s in the rest, which is the
        # normal signal that the year ended at 52 -- not an error to retry.
        for week in range(1, 54):
            result = scrape_mediatraffic_week(year, week, chart=chart)
            if result is None:
                missing += 1
                continue
            date, week_rows, ambiguous = result
            ambiguous_total += ambiguous
            if date in have:
                continue
            have.add(date)
            # One append per week, in the file's own line ending: existing rows
            # are never rewritten, and a kill leaves whole weeks behind.
            with open(csv_path, 'a', newline='') as f:
                w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator=newline)
                w.writerows(week_rows)
            fetched += 1
            n_rows += len(week_rows)

    print(f'DONE: {fetched} weeks appended ({n_rows} rows), {missing} unavailable, '
          f'{ambiguous_total} ambiguous titles -> {csv_path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
