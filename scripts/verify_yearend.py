"""Check every stored year-end year against that chart's own weekly data.

`yearend_guard` compares years with each other, so it can only catch a
fabricated year whose original is also kept: equal signatures collapse to the
latest. That leaves one hole. When Billboard files a list under a year whose
original was never stored, nothing matches it and it survives every structural
check. latin_songs 1996 held a 2006 list this way and looked ordinary.

The test that does not depend on duplicates: a genuine year-end for year Y is
compiled from year Y's weekly charts, so its titles must appear in that year's
weekly data. Disagreement is only meaningful when the weekly CSV actually
covers the year, so a year with fewer than MIN_WEEKS scraped is reported as
untestable rather than failed.

Run after any year-end backfill. Anything it fails belongs in
`backfill_yearend.FABRICATED`, so a later run does not restore it.

    python3 scripts/verify_yearend.py
"""
from __future__ import annotations

import collections
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
YEAREND = ROOT / 'data' / 'yearend.csv'

MIN_WEEKS = 20
MIN_OVERLAP = 60
# The overlap bar is scaled by how much of the year the weekly CSV holds, so a
# year is only judged on weeks that exist. top100 1958 is the case: the Hot 100
# began on 1958-08-09, so 31 of that year's weeks were never published, and its
# year-end chart is largely built from songs no Hot 100 week can confirm. It
# scores 49% against a flat 60% bar while matching 1958 four times better than
# any other year, so the flat bar fails a chart that is demonstrably genuine.
# Scaling does not let a wrong year through: a misfiled list scores near zero.
FULL_YEAR_WEEKS = 52

# Chart key -> the weekly CSV it is compiled from. Charts absent here are not
# checked: artist100 and albums200 rank artists and albums, so their year-end
# titles are not song titles and the comparison is meaningless.
CSV_FOR = {
    'top100': 'hot100.csv', 'global200': 'global200.csv',
    'globalexus': 'globalexus.csv', 'radio': 'radio.csv',
    'digital': 'digital_songs.csv', 'streaming': 'streaming_songs.csv',
    'pop_airplay': 'pop_airplay.csv',
    'adult_contemporary': 'adult_contemporary.csv',
    'adult_pop': 'adult_pop_airplay.csv',
    'rhythmic': 'rhythmic_airplay.csv',
    'country_airplay': 'country_airplay.csv',
    'alternative': 'alternative_airplay.csv',
    'rnb_hiphop': 'rnb_hiphop_airplay.csv',
    'dance_airplay': 'dance_airplay.csv',
    'adult_rnb': 'adult_rnb_airplay.csv',
    'dance_sales': 'dance_singles_sales.csv',
    'canadian_hot100': 'canadian_hot100.csv',
    'dance_electronic': 'dance_electronic_songs.csv',
    'gospel': 'gospel_songs.csv',
    'christian': 'christian_songs.csv',
    'country_songs': 'country_songs.csv',
    'rock_songs': 'rock_songs.csv',
    'latin_songs': 'latin_songs.csv',
}

# Years with too little weekly coverage to test, triaged and accepted. Each is
# a year the year-end exists for but the weekly archive does not reach, which
# is ordinary: Billboard's weekly archive starts later than its year-end one
# for several charts.
#   dance_electronic 2013 - chart launched January 2013, weekly archive starts
#     2014-03-22. Content is era-correct ("Harlem Shake", "Get Lucky") and
#     differs from 2014, so the year is genuine.
#   dance_sales 2007-2013, alternative 1988 - pre-existing and accepted here
#     to get a clean baseline, but NOT actually triaged. The chart ended in
#     2007, so its 2008-2013 year-ends deserve the same content check the
#     Latin years got before anyone relies on them.
# rock_songs 1978 and 2005 are deliberately absent: they were removed as
# fabricated copies of 2009, so if they reappear this must fail, not excuse it.
UNTESTABLE_OK = {
    ('dance_electronic', 2013),
    ('alternative', 1988),
    *(('dance_sales', y) for y in range(2007, 2014)),
}


_cache: dict[str, tuple] = {}


def titles_by_year(name):
    """{'YYYY': {song titles}}, {'YYYY': {dates}} for a weekly CSV.

    Cached per chart. country_songs.csv alone is 240k rows and is consulted
    once for each of 56 stored years.
    """
    if name not in _cache:
        songs = collections.defaultdict(set)
        weeks = collections.defaultdict(set)
        with open(ROOT / 'data' / name, newline='', encoding='utf-8') as fh:
            for row in csv.DictReader(fh):
                year = row['Date'][:4]
                songs[year].add(row['Song'].strip().lower())
                weeks[year].add(row['Date'])
        _cache[name] = (songs, weeks)
    return _cache[name]


def main():
    stored = collections.defaultdict(set)
    with open(YEAREND, newline='', encoding='utf-8') as fh:
        for row in csv.DictReader(fh):
            stored[(row['Chart'], int(row['Year']))].add(
                row['Song'].strip().lower())

    failures, untested = [], []
    for (chart, year), ye_titles in sorted(stored.items()):
        name = CSV_FOR.get(chart)
        if not name:
            continue
        songs, weeks = titles_by_year(name)
        nweeks = len(weeks.get(str(year), ()))
        if nweeks < MIN_WEEKS:
            if (chart, year) not in UNTESTABLE_OK:
                untested.append((chart, year, nweeks))
            continue
        have = songs.get(str(year), set())
        pct = 100 * len(ye_titles & have) // max(1, len(ye_titles))
        bar = MIN_OVERLAP * min(1.0, nweeks / FULL_YEAR_WEEKS)
        if pct < bar:
            failures.append((chart, year, nweeks, pct, bar))

    for chart, year, nweeks, pct, bar in failures:
        print(f'FAIL {chart} {year}: only {pct}% of its titles appear in the '
              f'{year} weekly data ({nweeks} weeks scraped, needed {bar:.0f}%)')
    for chart, year, nweeks in untested:
        print(f'WARN {chart} {year}: {nweeks} weeks of weekly data, cannot be '
              f'checked. Triage it and add it to UNTESTABLE_OK.')

    checked = len(stored) - len(untested)
    print(f'\n{checked} year-end years checked, {len(failures)} failed, '
          f'{len(untested)} untriaged')
    return 1 if failures or untested else 0


if __name__ == '__main__':
    sys.exit(main())
