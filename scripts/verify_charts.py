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
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app  # noqa: E402


def check_chart(key, df):
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
    sig = (d.sort_values(['_dt', 'Rank'])
             .groupby('_dt')[['Rank', 'Song']]
             .apply(lambda g: tuple(zip(g['Rank'], g['Song'].astype(str)))))
    clamped = [str(pd.Timestamp(b).date())
               for a, b in zip(sig.index, sig.index[1:])
               if sig.loc[a] == sig.loc[b]]
    if clamped:
        hard.append(f'{len(clamped)} week(s) identical to the previous week '
                    f'(clamped?): {", ".join(clamped[:5])}')

    counts = d.groupby('_dt').size()
    if (counts < 5).any():
        n = int((counts < 5).sum())
        warn.append(f'{n} week(s) with fewer than 5 rows')

    return hard, warn


def main():
    failed = False
    for key in app.CHARTS:
        df, _dates = app.CHART_DATA.get(key, (None, None))
        if df is None or not len(df):
            print(f'SKIP  {key:22} no data loaded')
            continue

        hard, warn = check_chart(key, df)
        weeks = pd.to_datetime(df['Date'], errors='coerce').nunique()
        status = 'FAIL' if hard else 'OK  '
        print(f'{status}  {key:22} {len(df):>7} rows  {weeks:>5} weeks')
        for m in hard:
            print(f'        FAIL: {m}')
            failed = True
        for m in warn:
            print(f'        warn: {m}')

    print('\nRESULT:', 'FAILURES PRESENT' if failed else 'all charts passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
