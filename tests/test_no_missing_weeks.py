"""A chart CSV must not skip a Billboard week or invent one.

Both failure modes are invisible to a row count, which is what let them sit in
the data for years. They are visible in one number the scraper already stores:
a song's weeks-on-chart. Across two consecutive published weeks, every song
that stayed on the chart advances by exactly one. So the modal delta over the
songs two weeks share is the number of chart weeks that actually elapsed
between them, measured from the data instead of from the calendar.

    modal delta == 1   the weeks are adjacent, as stored
    modal delta >= 2   at least one published week is MISSING between them
    modal delta == 0   the later week DUPLICATES the earlier one

Comparing that against the calendar distance splits the results in two, and the
distinction is what decides whether data is wrong or merely absent:

    days / 7 == elapsed   an honest hole. The archive lacks those weeks but
                          every date it does store is truthful.
    days / 7 != elapsed   a DATE DEFECT. The stored dates are lying about
                          which week the rows belong to.

Only the second kind corrupts existing rows, and it is the kind repaired here.

Three defects fixed, all at a New Year boundary:

- hot100 2018-01-06 held Billboard's 2018-01-03 chart. Billboard published a
  Hot 100 dated Wednesday 2018-01-03 between 2017-12-30 and 2018-01-06, and the
  weekly backfill walks in 7-day steps, so it could never request that date.
  Every song lost a week and the real 2018-01-06 debuts looked like 2018-01-13
  debuts. Confirmed genuine by "Perfect" running 16 -> 17 -> 18 -> 19 across the
  four weeks.
- canadian_hot100 and japan_hot100 were missing the same 2018-01-03 chart,
  though their 2018-01-06 was correctly dated.
- hot100 1961-12-30 was a week Billboard never published, duplicated from
  1962-01-06. Deleted, not replaced: this archive is Saturday-dated for its
  whole history while Billboard used Monday dates in that era, so the real
  1961-12-25 chart is already present as 1961-12-23.

The calendar cannot catch any of these -- every bad week sits exactly 7 days
from its neighbour. Only weeks-on-chart continuity can.

`fixtures/known_week_gaps.json` records the anomalies still outstanding across
the rest of the archive so this suite fails when a NEW one appears rather than
drowning in the backlog. It is a ratchet: the numbers may fall, never rise.
See HANDOFF.md for what is left.
"""
import csv
import json
from collections import defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'data'
BASELINE = json.loads((Path(__file__).parent / 'fixtures' / 'known_week_gaps.json').read_text())

# Charts repaired here. These must stay perfectly continuous, so they are held
# to the real invariant rather than to the baseline.
REPAIRED = ['hot100.csv', 'canadian_hot100.csv']

# Below this many shared songs the mode is not a reliable signal -- the early
# Hot 100 turned over hard, and a chart's first weeks share almost nothing.
MIN_SHARED = 10


def weeks_on_chart(row):
    """The scraper writes this column under either name depending on its era."""
    raw = (row.get('Weeks in Charts') or row.get('Weeks on Chart') or '').strip()
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def by_week(path):
    weeks = defaultdict(dict)
    with open(path, newline='') as fh:
        for row in csv.DictReader(fh):
            got = weeks_on_chart(row)
            if got is not None:
                weeks[row['Date'][:10]][(row['Song'], row['Artist'])] = got
    return weeks


def anomalies(path):
    """(earlier, later, elapsed) for every pair that did not advance one week."""
    weeks = by_week(path)
    out = []
    for earlier, later in zip(sorted(weeks), sorted(weeks)[1:]):
        shared = set(weeks[earlier]) & set(weeks[later])
        if len(shared) < MIN_SHARED:
            continue
        deltas = [weeks[later][k] - weeks[earlier][k] for k in shared]
        elapsed = max(set(deltas), key=deltas.count)
        if elapsed != 1:
            out.append((earlier, later, elapsed))
    return out


def date_defects(path):
    """Anomalies where the stored dates disagree with the weeks that elapsed."""
    from datetime import date
    out = []
    for earlier, later, elapsed in anomalies(path):
        days = (date.fromisoformat(later) - date.fromisoformat(earlier)).days
        if days / 7 != elapsed:
            out.append((earlier, later, elapsed, days))
    return out


@pytest.mark.parametrize('name', REPAIRED)
def test_repaired_charts_are_continuous(name):
    found = anomalies(DATA / name)
    assert not found, '\n'.join(
        f'{a} -> {b}: songs advanced {d} weeks '
        f'({"duplicate week" if d == 0 else "missing week between them"})'
        for a, b, d in found
    )


def test_japan_hot100_has_no_date_defect():
    """Its five 14-day holes are honest; only the 2018 mislabelling was a defect."""
    assert not date_defects(DATA / 'japan_hot100.csv')


def test_the_repaired_boundary_weeks_are_correct():
    """Pins the exact weeks, so a re-backfill cannot quietly undo the repair."""
    weeks = by_week(DATA / 'hot100.csv')
    assert '2018-01-03' in weeks, 'Billboard published a Hot 100 dated 2018-01-03'
    assert '1961-12-30' not in weeks, 'Billboard never published a chart dated 1961-12-30'
    # The tell for the original mislabelling: 01-03 and 01-06 are different
    # charts, and the one stored under 01-06 must be the later of the two.
    perfect = ('Perfect', 'Ed Sheeran')
    assert weeks['2018-01-03'][perfect] == 17
    assert weeks['2018-01-06'][perfect] == 18
    # 1961-12-23 is this archive's Saturday label for Billboard's 1961-12-25.
    lion = ('The Lion Sleeps Tonight', 'The Tokens')
    assert weeks['1961-12-23'][lion] == 7
    assert weeks['1962-01-06'][lion] == 8


@pytest.mark.parametrize('name', sorted(p.name for p in DATA.glob('*.csv')))
def test_no_chart_gains_a_new_gap(name):
    """A ratchet over the outstanding backlog: counts may fall, never rise."""
    found = len(anomalies(DATA / name))
    allowed = BASELINE.get(name, 0)
    assert found <= allowed, (
        f'{name}: {found} discontinuities, baseline allows {allowed}. '
        'A new week was skipped or duplicated.'
    )
