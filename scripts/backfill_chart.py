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

# Billboard has not always dated every chart on a Saturday. country-songs and
# r-b-hip-hop-songs were dated MONDAY from their 1958-10-20 launch through
# 1961-12-25, and Saturday from 1962-01-06 onward. Measured against
# billboard.com on 2026-08-10, boundary included: 1961-12-25 serves itself,
# and the next real week is 1962-01-06, twelve days later.
#
# Walking Saturdays across the Monday era does not fail loudly. Billboard
# clamps each date that never existed to a nearby real week, the scraper's
# served-week guard rejects the mismatch, and 166 weeks land in the fail list
# looking like network trouble — while the Monday weeks they stand for are
# never requested at all. `find_chart_start.py` has the same blind spot, which
# is why it reported these two launching on Saturday 1958-10-18.
#
# Each segment is (first week, last week or None for "run to the end"); the
# weekday is taken from the segment's own start date and stepped by 7 days.
CHART_CALENDARS = {
    'country-songs':     [('1958-10-20', '1961-12-25'), ('1962-01-06', None)],
    'r-b-hip-hop-songs': [('1958-10-20', '1961-12-25'), ('1962-01-06', None)],
}

# Weeks Billboard never published, as (first, last) inclusive. The R&B chart
# was suspended after 1963-11-23 and resumed 1965-01-30 — 61 weeks that all
# clamp forward to 1965-01-30 and cost a wasted round trip each.
CHART_GAPS = {
    'r-b-hip-hop-songs': [('1963-11-24', '1965-01-29')],
}


def ranking_signature(rows):
    """Hash a week's full ordering, so clamped repeats can be detected."""
    if rows is None:
        return None
    parts = [f"{r.get('Rank')}|{r.get('Song')}|{r.get('Artist')}" for r in rows]
    return hashlib.sha1('\n'.join(parts).encode()).hexdigest()


def signatures_from_frame(df):
    """date -> ranking signature, for every week already in the frame."""
    if df.empty:
        return {}
    out = {}
    for date, week in df.sort_values('Rank').groupby('Date', sort=False):
        parts = [f"{r}|{s}|{a}" for r, s, a in
                 zip(week['Rank'], week['Song'], week['Artist'])]
        out[str(date)] = hashlib.sha1('\n'.join(parts).encode()).hexdigest()
    return out


def chart_weeks(slug, first_week, last_week=None):
    """Every date this chart was actually published, in order.

    Defaults to stepping 7 days from `first_week`, keeping whatever weekday
    that date falls on. Charts in CHART_CALENDARS changed weekday partway
    through and use their measured segments instead; CHART_GAPS weeks are
    dropped because Billboard never published them.
    """
    # Discontinued charts stop being published long before today. Without a
    # last week, every date after the final one is still requested, and each is
    # a clamped response that costs a round trip to reject — 1,000+ of them on
    # a chart that ended in 2007.
    stop = (datetime.strptime(last_week, '%Y-%m-%d') if last_week
            else datetime.now() + timedelta(days=6))
    begin = datetime.strptime(first_week, '%Y-%m-%d')
    segments = CHART_CALENDARS.get(slug) or [(first_week, None)]

    out = []
    for seg_start, seg_end in segments:
        d = datetime.strptime(seg_start, '%Y-%m-%d')
        seg_stop = min(stop, datetime.strptime(seg_end, '%Y-%m-%d')) if seg_end else stop
        while d <= seg_stop:
            # `first_week` still bounds the run, so a calendared chart can be
            # backfilled from a later date without hand-editing the segments.
            if d >= begin:
                out.append(d.strftime('%Y-%m-%d'))
            d += timedelta(days=7)

    for gap_start, gap_end in CHART_GAPS.get(slug, []):
        out = [w for w in out if not gap_start <= w <= gap_end]
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

    wanted = chart_weeks(slug, first_week, last_week)
    missing = [w for w in wanted if w not in have]
    print(f'{slug}: {len(wanted)} weeks total, {len(have)} present, {len(missing)} to fetch', flush=True)

    fails, clamped = [], []
    # A week is clamped when its ranking repeats the week immediately before it
    # in `wanted`. That predecessor has to be looked up per week rather than
    # carried in a rolling variable: on a re-run the missing weeks are
    # scattered, so a rolling signature would compare each one against whatever
    # week happened to be written last and wave the fabrications through.
    sigs = signatures_from_frame(df)
    position = {w: i for i, w in enumerate(wanted)}

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
        idx = position[week]
        prev_sig = sigs.get(wanted[idx - 1]) if idx > 0 else None
        if sig is not None and prev_sig is not None and sig == prev_sig:
            # Identical to the previous week: Billboard clamped an out-of-range
            # date. Writing it would fabricate a week that never existed.
            clamped.append(week)
            continue
        sigs[week] = sig

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
