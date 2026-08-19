#!/usr/bin/env python3
"""Backfill MediaTraffic's World Single Chart to CSV.

Resumable: reads the existing CSV and skips weeks already stored, so a killed
run picks up where it stopped. Checkpoints every 25 weeks.

No clamp comparison here, unlike backfill_chart.py. That script drops a week
whose ordering is identical to its neighbour because Billboard serves
out-of-range dates as a boundary week under the date you asked for.
MediaTraffic cannot do that — each week is a static file and a missing week
404s — so an identical neighbour would be real data, not an artifact, and
dropping it would delete history. The integrity checks that DO apply live in
the scraper: stated week must match, rank sequence must be a complete 1..N.

Usage:
  backfill_mediatraffic.py <csv-path> [first-year] [last-year]
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from fast_mediatraffic_scraper import FIRST_DATED_YEAR, scrape_mediatraffic_week

COLUMNS = ['Date', 'Rank', 'Song', 'Artist', 'Last Week', 'Peak Position', 'Weeks on Chart']
CHECKPOINT_EVERY = 25


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    csv_path = Path(sys.argv[1])
    first_year = int(sys.argv[2]) if len(sys.argv) > 2 else FIRST_DATED_YEAR
    last_year = int(sys.argv[3]) if len(sys.argv) > 3 else 2026

    existing = pd.read_csv(csv_path) if csv_path.exists() else pd.DataFrame(columns=COLUMNS)
    have = set(existing['Date'].astype(str)) if len(existing) else set()
    rows = existing.to_dict('records')

    fetched = missing = ambiguous_total = 0
    for year in range(first_year, last_year + 1):
        # Week 53 exists in some years and 404s in the rest, which is the
        # normal signal that the year ended at 52 — not an error to retry.
        for week in range(1, 54):
            result = scrape_mediatraffic_week(year, week)
            if result is None:
                missing += 1
                continue
            date, week_rows, ambiguous = result
            ambiguous_total += ambiguous
            if date in have:
                continue
            have.add(date)
            rows.extend(week_rows)
            fetched += 1
            if fetched % CHECKPOINT_EVERY == 0:
                pd.DataFrame(rows)[COLUMNS].to_csv(csv_path, index=False)
                print(f'  … checkpoint: {fetched} weeks, {len(rows)} rows')

    out = pd.DataFrame(rows)[COLUMNS].sort_values(['Date', 'Rank'])
    out.to_csv(csv_path, index=False)
    print(f'DONE: {fetched} weeks fetched, {len(out)} rows, {missing} unavailable, '
          f'{ambiguous_total} ambiguous titles -> {csv_path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
