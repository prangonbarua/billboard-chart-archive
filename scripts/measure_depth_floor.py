#!/usr/bin/env python3
"""Measure a chart's MINIMUM historical depth, which is its backfill floor.

fast_billboard_scraper.py rejects any week shallower than its floor for that
chart, defaulting to 20. The default is right for the live weekly path and
wrong for a backfill: charts that ran shallow in an earlier era get every one
of those weeks rejected, and rejected SILENTLY — the log says "Incomplete
chart: 15/20 rows" the same way it does for a Billboard markup break, the run
exits 0, and the CSV looks finished while missing years. Latin Pop Airplay
serves ONE row a week at its 1994 launch; Dance Singles Sales lost six years
to exactly this.

The registry depth is the chart's CURRENT depth and cannot stand in for the
floor, because depth moves in both directions over a chart's life (Dance
Airplay ran 40, then 25, then 40 again). So this samples eras across the
chart's real span and takes the minimum.

Count rows with the scraper's own parser. Counting 'o-chart-results-list-row'
in raw HTML reports exactly double, because that string appears twice per rank
— a floor set from that number rejects every week of the chart.

    python3 scripts/measure_depth_floor.py plan.json [samples]

Reads {slug: {first_week, depth, ...}} and writes a `floor` into each entry.
"""

import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fast_billboard_scraper import scrape_billboard_chart

# Weeks either side of a sampled date to retry before giving up on it. A single
# date can come back empty for reasons that say nothing about the chart's depth
# (a one-off Billboard error, a week it never published), and treating that as
# depth 0 would set a floor of 0 and admit anything.
NUDGE_WEEKS = (0, 1, -1, 2)


def depth_at(slug, date):
    """Row count served for a date, or None if nothing usable came back."""
    for offset in NUDGE_WEEKS:
        d = (datetime.strptime(date, '%Y-%m-%d')
             + timedelta(weeks=offset)).strftime('%Y-%m-%d')
        try:
            # min_rows=1 disables the very gate being measured. Without it a
            # chart serving 15 rows against the default floor of 20 comes back
            # None and reads as "no depth", which is how the floor would end up
            # set to the number that rejects the whole chart.
            rows = scrape_billboard_chart(slug, date=d, min_rows=1)
        except Exception as exc:
            print(f'  {slug} {d}: error {exc}')
            rows = None
        if rows:
            return len(rows), d
        time.sleep(1)
    return None, None


def sample_dates(first_week, samples):
    """Evenly spaced dates from launch to now, launch included."""
    start = datetime.strptime(first_week, '%Y-%m-%d')
    end = datetime.now()
    span = (end - start).days
    if span <= 0:
        return [first_week]
    step = span // max(samples - 1, 1)
    out = [(start + timedelta(days=step * i)).strftime('%Y-%m-%d')
           for i in range(samples)]
    return out


def main():
    plan_path = Path(sys.argv[1])
    samples = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    plan = json.loads(plan_path.read_text())

    for slug, spec in sorted(plan.items()):
        if not spec.get('first_week'):
            print(f'{slug:44} skipped (no measured first week)')
            continue
        seen = {}
        for date in sample_dates(spec['first_week'], samples):
            n, served = depth_at(slug, date)
            if n:
                seen[served] = n
            time.sleep(1)
        if not seen:
            print(f'{slug:44} NO DEPTH MEASURED — left at registry depth')
            spec['floor'] = spec['depth']
            continue
        # The floor has to hold for the current depth too, which the samples
        # may miss if the newest era is deeper than every date sampled.
        floor = min(min(seen.values()), spec['depth'])
        spec['floor'] = floor
        spec['depth_samples'] = seen
        flag = '  <- below default 20' if floor < 20 else ''
        print(f'{slug:44} floor={floor:<4} samples={seen}{flag}')

    plan_path.write_text(json.dumps(plan, indent=1))
    print(f'\nwrote floors into {plan_path}')


if __name__ == '__main__':
    main()
