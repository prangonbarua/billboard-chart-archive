#!/usr/bin/env python3
"""Backfill one Billboard chart's full history to CSV.

Resumable: reads the existing CSV, fetches only missing weeks, checkpoints every
25 weeks, and reports a fail list at the end. Safe to re-run.

The clamp guard is the important part. Billboard serves any out-of-range date --
before a chart launched, or after its newest week -- by returning the boundary
week's rankings under the date you asked for, with no redirect and no date in the
page. A single response cannot reveal this. So every fetched week is compared
against the adjacent known week and dropped if the full (rank, song, artist)
ordering is identical. Real consecutive chart weeks always differ.

Usage:
  backfill_chart.py <bb-slug> <csv-path> <first-week YYYY-MM-DD> [last-week YYYY-MM-DD]

Pass a last week for a discontinued chart; it defaults to this week.
"""

import hashlib
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from fast_billboard_scraper import scrape_billboard_chart

CHECKPOINT_EVERY = 25
MAX_ATTEMPTS = 3
COLUMNS = ['Date', 'Rank', 'Song', 'Artist', 'Last Week', 'Peak Position', 'Weeks on Chart']


def ranking_signature(rows):
    """Hash a week's full ordering, so clamped repeats can be detected."""
    if rows is None:
        return None
    parts = [f"{r.get('Rank')}|{r.get('Song')}|{r.get('Artist')}" for r in rows]
    return hashlib.sha1('\n'.join(parts).encode()).hexdigest()


def signature_from_frame(df, date):
    week = df[df['Date'] == date]
    if week.empty:
        return None
    week = week.sort_values('Rank')
    parts = [f"{r}|{s}|{a}" for r, s, a in
             zip(week['Rank'], week['Song'], week['Artist'])]
    return hashlib.sha1('\n'.join(parts).encode()).hexdigest()


def saturdays_from(first_week, last_week=None):
    d = datetime.strptime(first_week, '%Y-%m-%d')
    # Discontinued charts stop being published long before today. Without a
    # last week, every date after the final one is still requested, and each is
    # a clamped response that costs a round trip to reject — 1,000+ of them on
    # a chart that ended in 2007.
    stop = (datetime.strptime(last_week, '%Y-%m-%d') if last_week
            else datetime.now() + timedelta(days=6))
    out = []
    while d <= stop:
        out.append(d.strftime('%Y-%m-%d'))
        d += timedelta(days=7)
    return out


def save(df, path):
    df = df.copy()
    df['__d'] = pd.to_datetime(df['Date'], errors='coerce')
    df = (df.drop_duplicates(subset=['Date', 'Rank'])
            .sort_values(['__d', 'Rank'])
            .drop(columns='__d'))
    df.to_csv(path, index=False)
    return df


def main():
    if len(sys.argv) not in (4, 5):
        print(__doc__)
        sys.exit(2)
    slug, csv_path, first_week = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    last_week = sys.argv[4] if len(sys.argv) == 5 else None

    df = pd.read_csv(csv_path, low_memory=False) if csv_path.exists() else pd.DataFrame(columns=COLUMNS)
    have = set(df['Date'].astype(str)) if len(df) else set()

    wanted = saturdays_from(first_week, last_week)
    missing = [w for w in wanted if w not in have]
    print(f'{slug}: {len(wanted)} weeks total, {len(have)} present, {len(missing)} to fetch', flush=True)

    fails, clamped = [], []
    # Signature of the most recent week we accepted, for the clamp comparison.
    prev_sig = signature_from_frame(df, wanted[wanted.index(missing[0]) - 1]) if missing and wanted.index(missing[0]) > 0 else None

    for i, week in enumerate(missing):
        rows = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                rows = scrape_billboard_chart(slug, week)
            except Exception:
                rows = None
            if rows:
                break
            time.sleep(3 * attempt)

        if not rows:
            fails.append(week)
            continue

        sig = ranking_signature(rows)
        if sig is not None and sig == prev_sig:
            # Identical to the previous week: Billboard clamped an out-of-range
            # date. Writing it would fabricate a week that never existed.
            clamped.append(week)
            continue
        prev_sig = sig

        df = pd.concat([df, pd.DataFrame(rows)], ignore_index=True)

        if (i + 1) % CHECKPOINT_EVERY == 0 or i == len(missing) - 1:
            df = save(df, csv_path)
            print(f'  {slug}: {i + 1}/{len(missing)} fetched, '
                  f'{len(fails)} failed, {len(clamped)} clamped', flush=True)

    df = save(df, csv_path)
    print(f'DONE {slug}: {df["Date"].nunique()} weeks, '
          f'{df["Date"].min()} -> {df["Date"].max()}, '
          f'{len(fails)} failed, {len(clamped)} clamped/skipped', flush=True)
    if fails:
        print(f'  failed weeks (first 20): {fails[:20]}', flush=True)
    if clamped:
        print(f'  clamped weeks (first 10): {clamped[:10]}', flush=True)


if __name__ == '__main__':
    main()
