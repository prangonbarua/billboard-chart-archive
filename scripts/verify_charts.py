#!/usr/bin/env python3
"""Data-integrity checks across every loaded chart. Run from the repo root:

    python3 scripts/verify_charts.py

Row counts are checked for plausibility only, never against the registry's
`depth`: these charts changed depth over their lifetimes (Adult Contemporary
ran 19-20 rows in 1961 against 30 today), so depth is a display value.

The consecutive-ranking check is the post-hoc guard for clamped weeks. Billboard
serves any out-of-range date by returning the boundary week's rankings under the
requested date, so a fabricated week looks entirely valid on its own. Only an
identical full (rank, song) ordering against the neighbouring week reveals it.
A repeated #1 proves nothing — songs hold #1 for months.

Weeks already triaged and accepted are listed in known_clamped_weeks.json and
reported without failing the run, so this can gate the weekly scrape on new
corruption without the pre-existing findings making it permanently red.
"""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app  # noqa: E402

BASELINE_PATH = Path(__file__).with_name('known_clamped_weeks.json')


def load_baseline():
    if not BASELINE_PATH.exists():
        return {}
    return {k: set(v) for k, v in json.loads(BASELINE_PATH.read_text()).items()
            if not k.startswith('_')}


def check_chart(key, df, known=frozenset()):
    """Return (hard_failures, warnings) for one chart."""
    hard, warn = [], []

    dt = pd.to_datetime(df['Date'], errors='coerce')
    if dt.isna().any():
        hard.append(f'{int(dt.isna().sum())} unparseable dates')

    d = df.assign(_dt=dt).dropna(subset=['_dt'])

    dupes = d.duplicated(subset=['_dt', 'Rank']).sum()
    if dupes:
        hard.append(f'{int(dupes)} duplicate (Date, Rank) rows')

    weeks = sorted(d['_dt'].unique())

    # Gaps. Reported, not fatal: several charts have genuine publication gaps
    # and a hand-filled seam week, and those are known rather than corrupt.
    gaps = []
    for a, b in zip(weeks, weeks[1:]):
        delta = (pd.Timestamp(b) - pd.Timestamp(a)).days
        if delta != 7:
            gaps.append((pd.Timestamp(a).date(), pd.Timestamp(b).date(), delta))
    if gaps:
        shown = ', '.join(f'{a}->{b} ({n}d)' for a, b, n in gaps[:5])
        warn.append(f'{len(gaps)} non-weekly steps: {shown}'
                    + (' ...' if len(gaps) > 5 else ''))

    # Clamped-week detection.
    # Columns are selected before .apply so this works on both the pinned
    # pandas 2.1.4 and newer versions, where passing the grouping column
    # through warns and needs include_groups=False (2.2+ only).
    # Titles are normalized before comparing: casing and whitespace drift
    # between scrapes ('Ordinary' vs 'ordinary ') would otherwise let a
    # clamped week slip through as merely similar. False negatives only —
    # normalizing can never invent a match between two different orderings.
    sig = (d.sort_values(['_dt', 'Rank'])
             .groupby('_dt')[['Rank', 'Song']]
             .apply(lambda g: tuple(zip(
                 g['Rank'], g['Song'].astype(str).str.strip().str.casefold()))))
    clamped = [str(pd.Timestamp(b).date())
               for a, b in zip(sig.index, sig.index[1:])
               if sig.loc[a] == sig.loc[b]]
    new = [w for w in clamped if w not in known]
    if new:
        hard.append(f'{len(new)} NEW week(s) identical to the previous week '
                    f'(clamped?): {", ".join(new)}')
    accepted = [w for w in clamped if w in known]
    if accepted:
        warn.append(f'{len(accepted)} known clamped week(s), see '
                    f'{BASELINE_PATH.name}: {", ".join(accepted[:5])}'
                    + (' ...' if len(accepted) > 5 else ''))

    counts = d.groupby('_dt').size()
    if (counts < 5).any():
        n = int((counts < 5).sum())
        warn.append(f'{n} week(s) with fewer than 5 rows')

    return hard, warn


def main():
    failed = False
    baseline = load_baseline()
    stale = {k: sorted(v) for k, v in baseline.items() if k not in app.CHARTS}
    for key in app.CHARTS:
        df, _dates = app.CHART_DATA.get(key, (None, None))
        if df is None or not len(df):
            print(f'SKIP  {key:22} no data loaded')
            continue

        hard, warn = check_chart(key, df, baseline.get(key, frozenset()))
        weeks = pd.to_datetime(df['Date'], errors='coerce').nunique()
        status = 'FAIL' if hard else 'OK  '
        print(f'{status}  {key:22} {len(df):>7} rows  {weeks:>5} weeks')
        for m in hard:
            print(f'        FAIL: {m}')
            failed = True
        for m in warn:
            print(f'        warn: {m}')

    if stale:
        print(f'\nnote: {BASELINE_PATH.name} lists charts that do not exist: '
              f'{", ".join(sorted(stale))}')

    print('\nRESULT:', 'NEW FAILURES PRESENT' if failed
          else 'no new failures (see warnings for accepted findings)')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
