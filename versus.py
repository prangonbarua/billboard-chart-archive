"""Pure stat computation for the artist-versus feature.

Imports no Flask and nothing from app.py: every function takes a DataFrame of
one artist's rows and returns plain data. That is deliberate — silently wrong
stats are this feature's main risk, and this is the only part of the codebase
that can be unit-tested without loading 1.5M CSV rows.

Callers are responsible for selecting the artist's rows with
app.artist_match_mask(); substring matching pulls 'Tyla Yaweh' into a search
for 'Tyla'.
"""
import re

import pandas as pd

# A credit's primary artist is everything before the first collaboration marker.
_CREDIT_MARKER_RE = r'\s+(?:featuring|feat\.?|with|x|&|\+|duet)\s+.*$'


def primary_artist(name):
    """Normalize an artist credit to its primary artist so week-to-week credit
    drift ('Weezer' vs 'Weezer Featuring Best Coast') keys the same."""
    return re.sub(_CREDIT_MARKER_RE, '', str(name).strip().casefold())


def dedupe_weeks(rows):
    """One row per (Date, Rank, Song). Duplicate scrape rows otherwise inflate
    every week and entry total.

    Song is part of the key, not just (Date, Rank): a chart position is
    unique per date in real data, so a true duplicate scrape row always
    matches on Song too. Keying on (Date, Rank) alone would silently drop
    one of two distinct songs if they ever appeared to share a date/rank
    (e.g. a data-quality glitch), corrupting that song's computed peak
    instead of merely removing a redundant row.
    """
    r = rows.copy()
    song_key = r['Song'].astype(str)
    return rows.loc[~pd.concat([r['Date'], r['Rank'], song_key], axis=1).duplicated()]


EMPTY_STATS = {
    'entries': 0,
    'number_ones': 0,
    'weeks_at_1': 0,
    'top_10s': 0,
    'top_40s': 0,
    'best_peak': None,
    'total_weeks_charted': 0,
    'first_entry': None,
    'last_entry': None,
    'biggest_hit': None,
    'timeline': [],
}


def _clean(rows):
    """Drop rows that cannot be ranked or dated, then dedupe."""
    if rows is None or rows.empty:
        return None
    r = rows.copy()
    r['Rank'] = pd.to_numeric(r['Rank'], errors='coerce')
    r = r.dropna(subset=['Rank', 'Date'])
    if r.empty:
        return None
    return dedupe_weeks(r)


def compute_artist_stats(rows, kind='song'):
    """Stats for one artist on one chart.

    `kind` comes from the CHARTS registry. On an artist chart the entries are
    artists rather than songs, so song-level counts are meaningless and are
    returned as None instead of a misleading number.
    """
    r = _clean(rows)
    if r is None:
        return dict(EMPTY_STATS)

    # Peak always from the Rank history — the stored Peak Position column is
    # corrupt across this repo's pre-2025 data.
    per_song = (
        r.assign(_key=[
            (s, primary_artist(a))
            for s, a in zip(r['Song'].astype(str).str.strip().str.casefold(),
                            r['Artist'].astype(str))
        ])
        .groupby('_key')
        .agg(peak=('Rank', 'min'), weeks=('Rank', 'size'), title=('Song', 'first'))
    )

    best = per_song.sort_values(['peak', 'weeks'], ascending=[True, False])

    stats = {
        'entries': int(len(per_song)),
        'number_ones': int((per_song['peak'] == 1).sum()),
        'weeks_at_1': int((r['Rank'] == 1).sum()),
        'top_10s': int((per_song['peak'] <= 10).sum()),
        'top_40s': int((per_song['peak'] <= 40).sum()),
        'best_peak': int(per_song['peak'].min()),
        'total_weeks_charted': int(r['Date'].nunique()),
        'first_entry': r['Date'].min().strftime('%Y-%m-%d'),
        'last_entry': r['Date'].max().strftime('%Y-%m-%d'),
        'biggest_hit': str(best.iloc[0]['title']).strip(),
        'timeline': [
            {'date': d.strftime('%Y-%m-%d'), 'rank': int(v)}
            for d, v in r.groupby('Date')['Rank'].min().sort_index().items()
        ],
    }

    if kind == 'artist':
        stats['entries'] = None
        stats['biggest_hit'] = None
        stats['number_ones'] = int((r['Rank'] == 1).any())

    return stats


def display_name(rows, query):
    """The artist's modal capitalization in the data. Scraped casing drifts
    week to week ('The Kid LAROI' vs 'The Kid Laroi'); show the common one."""
    if rows is None or rows.empty:
        return query
    target = primary_artist(query)
    credits = rows['Artist'].astype(str)
    exact = credits[credits.map(primary_artist) == target]
    if exact.empty:
        return query
    return str(exact.mode().iloc[0]).strip()
