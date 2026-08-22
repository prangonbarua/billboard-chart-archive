"""Cross-chart title index: where else did this song or album chart?

This replaces `_crossover_run`, which answered the same question across exactly
one hardcoded pair (Bubbling Under <-> Hot 100). The generalization is to every
weekly chart in the registry.

WHY AN INDEX AND NOT A SCAN. Measured 2026-08-21 over the real 6,413,280 rows:
generalizing the old per-request scan to every chart costs 0.94s per lookup,
which is a regression on a modal that is currently fast. A dict of tuples looks
up in 0.8us but costs ~100-150 MB live. This frame answers in 1.5ms —
imperceptible inside a fetch — for a fraction of that memory.

AS BUILT it is 543,400 rows, 63 MB, and 8.4s at import. The 63 MB is more than
the 33 MB the prototype measured, and the difference is entirely the two display
columns added later: `display` costs ~18 MB and `credit` ~8 MB over the ~26 MB
MultiIndex. They are not decoration — the index key is casefolded and
credit-stripped, so without them there is nothing showable to put in a search
box. Dropping either to save memory means printing 'the kid laroi' at the user.

Pure functions: data in, data out, no Flask and no module globals, so the index
can be built and asserted against without booting the app.
"""
import logging

import pandas as pd

import versus

log = logging.getLogger(__name__)

REQUIRED_COLUMNS = ('Song', 'Artist', 'Rank', 'Date')

# An artist chart ranks acts, not titles, so it has nothing to join on.
INDEXABLE_KINDS = ('song', 'album')


def _primary_artist_col(credits):
    """primary_artist over a whole credit column, mapped over UNIQUE credits.

    Same approach as app._primary_artist_col and for the same reason: 6.4M rows
    resolve to a few tens of thousands of distinct credits, so mapping per
    unique keeps the build fast without a second copy of the credit-splitting
    rules. versus.primary_artist stays the single definition.

    na_action='ignore' is load-bearing rather than tidy. Song and Artist load as
    CATEGORY columns (app.py:124), and pandas calls a Categorical mapper with
    np.nan whenever the column has NAs. Adult Contemporary has 20 blank-artist
    rows, so without this the whole build raises.
    """
    stripped = credits.astype(str).str.strip()
    lookup = {c: versus.primary_artist(c) for c in stripped.dropna().unique()}
    return stripped.map(lookup, na_action='ignore')


def build(chart_data, chart_dt, charts_meta):
    """One row per (title, artist, chart), indexed by (title, artist).

    Built from the frames already in memory rather than re-read from disk, so
    the marginal cost at import is the groupby alone.
    """
    parts = []
    for key, meta in charts_meta.items():
        if meta.get('kind') not in INDEXABLE_KINDS:
            continue

        df, _dates = chart_data.get(key, (None, None))
        if df is None or not len(df):
            continue

        missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            # Logged, never silent. A chart that quietly stops being indexed
            # shrinks coverage invisibly, which is the same class of bug as the
            # row-floor truncations this project has already shipped once.
            log.warning('chart_index: skipping %r, missing columns %s',
                        key, ', '.join(missing))
            continue

        dates = chart_dt.get(key)
        if dates is None:
            log.warning('chart_index: skipping %r, no parsed dates', key)
            continue

        title = df['Song'].astype(str).str.strip()
        rows = pd.DataFrame({
            # The join key is casefolded on BOTH fields. Scraped casing drifts
            # week to week ('The Kid LAROI' vs 'The Kid Laroi' — the 2026-07-01
            # bug) and an exact-key join returns nothing, which is
            # indistinguishable from a song that never charted elsewhere.
            # Folding it into the index means no call site can forget.
            'title': title.str.casefold(),
            # The display spelling, kept so the autocomplete does not offer
            # 'sicko mode'. Category because 246k distinct titles over 548k rows
            # stores the strings once.
            'display': title,
            # primary_artist, not primary_credit: primary_artist splits on
            # commas and is the GROUPING key, which is what a join needs.
            # It casefolds and drops featured acts ('The Kid LAROI & Justin
            # Bieber' -> 'the kid laroi'), so it is a key and NEVER a label.
            'artist': _primary_artist_col(df['Artist']),
            # The credit as billed, kept because the key above is unshowable.
            # A search box offering 'the kid laroi' would look broken.
            'credit': df['Artist'].astype(str).str.strip(),
            'rank': pd.to_numeric(df['Rank'], errors='coerce'),
            'date': dates.values,
        }).dropna(subset=['title', 'artist', 'rank', 'date'])

        if rows.empty:
            continue

        grouped = rows.groupby(['title', 'artist'], sort=False).agg(
            display=('display', 'first'),
            credit=('credit', 'first'),
            peak=('rank', 'min'),
            # nunique, not size: a chart that serves a duplicate row for one
            # week must not count that week twice.
            weeks=('date', 'nunique'),
            debut=('date', 'min'),
        ).reset_index()
        grouped['chart'] = key
        grouped['label'] = meta.get('label', key)
        grouped['kind'] = meta['kind']
        parts.append(grouped)

    if not parts:
        empty = pd.DataFrame(columns=['title', 'artist', 'display', 'credit',
                                      'peak', 'weeks', 'debut', 'chart',
                                      'label', 'kind'])
        return empty.set_index(['title', 'artist'])

    index = pd.concat(parts, ignore_index=True)
    for column in ('chart', 'label', 'kind', 'display', 'credit'):
        index[column] = index[column].astype('category')
    index['peak'] = index['peak'].astype('int16')
    index['weeks'] = index['weeks'].astype('int16')

    # SORTED, not incidentally ordered. .loc against an unsorted MultiIndex
    # falls back to a scan, which quietly hands back the 0.94s this whole module
    # exists to avoid. tests/test_chart_index.py pins this.
    return index.set_index(['title', 'artist']).sort_index()


def lookup(index, title, artist, kind, exclude_chart=None, origin_debut=None):
    """Every other chart of the same kind this title reached.

    An empty list means it charted nowhere else. It does NOT mean the lookup
    failed — callers must keep those two apart, which is the whole reason the
    API returns a list rather than raising or returning None.
    """
    if index is None or not len(index):
        return []

    key = (str(title).strip().casefold(), versus.primary_artist(artist))
    try:
        rows = index.loc[[key]]
    except KeyError:
        return []

    # Kind-matched. A song called '1989' is not evidence about the album 1989,
    # so a cross-kind title match is a coincidence rather than a fact.
    rows = rows[rows['kind'] == kind]
    if exclude_chart is not None:
        rows = rows[rows['chart'] != exclude_chart]
    if rows.empty:
        return []

    rows = rows.sort_values(['peak', 'weeks'], ascending=[True, False])

    has_origin = origin_debut is not None and pd.notna(origin_debut)
    return [
        {
            'chart': str(row.chart),
            'label': str(row.label),
            'debut': row.debut.strftime('%Y-%m-%d'),
            'peak': int(row.peak),
            'weeks': int(row.weeks),
            # Whether that run began after this one — the difference between
            # "reached the Hot 100" and "was already there". None, not False,
            # when the origin run has no debut to compare against: unknown and
            # "no, it was already there" are different answers.
            'later': bool(row.debut > origin_debut) if has_origin else None,
        }
        for row in rows.itertuples()
    ]


def title_pool(index, kind, prefix='', limit=50):
    """Display titles of the given kind starting with prefix, for autocomplete.

    Mirrors /api/artists, which serves a precomputed sorted pool.
    """
    if index is None or not len(index):
        return []

    rows = index[index['kind'] == kind]
    if prefix:
        needle = str(prefix).strip().casefold()
        rows = rows[rows.index.get_level_values('title').str.startswith(needle)]
    if rows.empty:
        return []

    titles = rows['display'].astype(str).unique()
    return sorted(titles)[:limit]


def suggest(index, kind, prefix='', limit=20):
    """Title+artist pairs for the search box.

    title_pool returns bare titles, which is enough to complete a text field but
    NOT enough to run a lookup: the index is keyed on (title, artist), and two
    different acts share a title often enough that guessing is wrong. 'Hold On'
    is Justin Bieber's and Wilson Phillips'. So the box offers the pair.

    Ranked by how many charts the pair reached, so the well-known one is first.
    """
    if index is None or not len(index):
        return []

    rows = index[index['kind'] == kind]
    if prefix:
        needle = str(prefix).strip().casefold()
        rows = rows[rows.index.get_level_values('title').str.startswith(needle)]
    if rows.empty:
        return []

    counts = rows.groupby(level=['title', 'artist'], observed=True).agg(
        display=('display', 'first'), credit=('credit', 'first'),
        charts=('chart', 'size'))
    counts = counts.sort_values('charts', ascending=False)

    # 'credit' is what to show, 'artist' is what to query with. Keeping both on
    # the suggestion is what stops a caller displaying the casefolded key.
    return [
        {'title': str(row.display), 'credit': str(row.credit),
         'artist': str(artist), 'charts': int(row.charts)}
        for (_title, artist), row in zip(counts.index, counts.itertuples(index=False))
    ][:limit]
