"""Pure stat computation for the artist-versus feature.

Imports no Flask and nothing from app.py: every function takes a DataFrame of
one artist's rows and returns plain data. That is deliberate — silently wrong
stats are this feature's main risk, and this is the only part of the codebase
that can be unit-tested without loading 1.5M CSV rows.

Credit parsing lives here too — primary_artist() keys songs and
artist_match_mask() selects an artist's rows, and the two must agree, so each
has exactly one definition in the codebase. app.py aliases both. Selection is
by whole credit segment, never substring: 'Tyla' must not pull in
'Tyla Yaweh'.
"""
import re

import pandas as pd

# A credit's primary artist is everything before the first collaboration marker.
_CREDIT_MARKER_RE = r'\s+(?:featuring|feat\.?|with|x|&|\+|duet)\s+.*$'

# What separates one artist from the next inside a credit: a word marker, a
# slash, a comma, or a parenthetical aside. Billboard mixes them freely
# ('Dionne & Friends Featuring Elton John, Gladys Knight And Stevie Wonder').
_CREDIT_DELIM = (r'(?:\s+(?:featuring|feat\.?|with|x|&|\+|duet|and)\s+'
                 r'|\s*[/(),]\s*)')

# Billboard credits a leader's backing group as its own act ('The Elton John
# Band', whose 'Lucy In The Sky With Diamonds' is an Elton John #1). Anchored
# at both ends so this cannot degrade into prefix matching.
_BACKING_BAND_RE = re.compile(r'^the\s+(.+?)\s+band$')


_PRIMARY_CREDIT_RE = re.compile(_CREDIT_MARKER_RE, re.I)


def primary_credit(name):
    """The credit's leading artist, keeping the scraped capitalization:
    'David Guetta & Bebe Rexha' -> 'David Guetta'."""
    return _PRIMARY_CREDIT_RE.sub('', str(name).strip()).strip()


def primary_artist(name):
    """Normalize an artist credit to its primary artist so week-to-week credit
    drift ('Weezer' vs 'Weezer Featuring Best Coast') keys the same."""
    return primary_credit(name).casefold()


def credit_query(artist_name):
    """Pattern matching a credit that names this artist.

    The name has to sit between credit delimiters — the start or end of the
    credit, or a marker — rather than merely appear in it. Splitting the
    credit instead cannot be made exact, because ' x ' is both a collaboration
    marker and part of 'Lil Nas X'; asking about boundaries lets both
    'Lil Nas X' and 'Elton John' match 'Lil Nas X Featuring Elton John'.
    """
    q = re.escape(str(artist_name).strip().casefold())
    return re.compile(f'(?:^|{_CREDIT_DELIM}){q}(?:{_CREDIT_DELIM}|$)')


def credit_names(credit, pattern):
    """Whether one credit names the artist `pattern` was built for."""
    text = str(credit).casefold().strip()
    if pattern.search(text):
        return True
    band = _BACKING_BAND_RE.match(text)
    return bool(band and pattern.search(band.group(1)))


def artist_match_mask(artist_series, artist_name):
    """Boolean mask: rows whose credit names artist_name as a whole artist.
    'Tyla' matches 'Tyla Featuring Zara Larsson' but NOT 'Tyla Yaweh'
    (substring matching wrongly pulled in similarly-named artists)."""
    if not str(artist_name).strip():
        return pd.Series(False, index=artist_series.index)
    pattern = credit_query(artist_name)
    # Tested per unique credit, not per row: 1.5M rows, ~30k credits.
    matching = {a for a in artist_series.dropna().unique()
                if credit_names(a, pattern)}
    return artist_series.isin(matching)


def dedupe_weeks(rows):
    """One row per (Date, Rank). Duplicate scrape rows otherwise inflate every
    week and entry total. A chart position is unique per date, so (Date,
    Rank) alone identifies one week's entry — matches the dedup key used
    repo-wide by update_from_billboard.py, backfill_chart.py,
    fast_billboard_scraper.py, and sync_data_from_scraper.py."""
    return rows.drop_duplicates(subset=['Date', 'Rank'])


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

# Stats that are not real counts on an artist chart — see the note in
# compute_artist_stats. Nulled whether or not the artist matched any rows, so
# an unmatched artist's column cannot read 0 beside a matched artist's dash.
_ARTIST_KIND_NULLS = ('entries', 'biggest_hit', 'number_ones',
                      'top_10s', 'top_40s')


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
        empty = dict(EMPTY_STATS)
        if kind == 'artist':
            empty.update(dict.fromkeys(_ARTIST_KIND_NULLS))
        return empty

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

    # One row per chart week: the entry that reached this artist's best rank
    # that week. Ties break on whichever row idxmin returns first, which is
    # stable for a given frame and only matters when two songs share a rank.
    _best = r.loc[r.groupby('Date')['Rank'].idxmin()].sort_values('Date')

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
        # idxmin, not min: the timeline carries the song that produced each
        # week's best rank. Aggregating with min() threw the title away, which
        # left the CSV export with a column of bare numbers and no way to tell
        # which song charted.
        'timeline': [
            {'date': d.strftime('%Y-%m-%d'), 'rank': int(rank),
             'song': str(song).strip()}
            for d, rank, song in zip(_best['Date'], _best['Rank'], _best['Song'])
        ],
    }

    if kind == 'artist':
        # On an artist chart, Song == Artist for the overwhelming majority of
        # rows, so grouping by (song, primary_artist) collapses this artist's
        # own filtered rows into exactly one group every time. Any stat built
        # by counting or filtering that per-song grouping is therefore not a
        # real count — it is a boolean in disguise (0 or 1, never more) and
        # must be nulled rather than shown as a number. number_ones has the
        # same defect: it was already special-cased away from per_song, but
        # int((r['Rank'] == 1).any()) is still only ever 0 or 1, and it adds
        # no information over best_peak (which is not nulled) — so it is
        # nulled too rather than displayed as if it counted distinct #1 songs.
        stats.update(dict.fromkeys(_ARTIST_KIND_NULLS))

    return stats


def display_name(rows, query):
    """The artist's modal capitalization in the data. Scraped casing drifts
    week to week ('The Kid LAROI' vs 'The Kid Laroi'); show the common one.

    The mode is taken over the leading artist of each credit, not the whole
    credit. Whole credits would label anyone whose longest-running hit is a
    collaboration with their collaborator's name too — David Guetta spent more
    weeks as 'David Guetta & Bebe Rexha' than under any other credit, and
    that string is not his name.
    """
    if rows is None or rows.empty:
        return query
    target = primary_artist(query)
    credits = rows['Artist'].astype(str)
    leads = credits[credits.map(primary_artist) == target].map(primary_credit)
    if leads.empty:
        return query
    return str(leads.mode().iloc[0]).strip()
