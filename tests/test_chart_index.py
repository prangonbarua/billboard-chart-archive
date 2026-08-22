"""Tests for the cross-chart title index.

Most of these run on small synthetic frames so the assertion is readable and
the whole file stays fast. The characterization test at the bottom is the
exception: it builds against the real Bubbling Under and Hot 100 CSVs and
holds the generalized lookup to what _crossover_run returned before it was
deleted. That test is what made deleting it safe.
"""
import json
import logging
import pathlib

import pandas as pd
import pytest

import chart_index

FIXTURES = pathlib.Path(__file__).parent / 'fixtures'
DATA = pathlib.Path(__file__).parent.parent / 'data'


def make_chart(rows, kind='song', label=None):
    """(frame, dt, meta) for one synthetic chart. rows are (song, artist, rank, date)."""
    df = pd.DataFrame(rows, columns=['Song', 'Artist', 'Rank', 'Date'])
    return df, pd.to_datetime(df['Date'], errors='coerce'), kind, label


def build(**charts):
    """build() over keyword-named synthetic charts."""
    chart_data, chart_dt, meta = {}, {}, {}
    for key, (df, dt, kind, label) in charts.items():
        chart_data[key] = (df, None)
        chart_dt[key] = dt
        meta[key] = dict(label=label or key.title(), group='Songs', depth=100, kind=kind)
    return chart_index.build(chart_data, chart_dt, meta)


# ── The join ────────────────────────────────────────────────────────────────

def test_casing_drift_across_charts_still_joins():
    """The 2026-07-01 bug. Scraped casing drifts week to week, and an exact-key
    join returns nothing — which looks identical to a song that never charted
    elsewhere. Both fields are casefolded into the key so it cannot recur."""
    idx = build(
        top100=make_chart([('STAY', 'The Kid LAROI & Justin Bieber', 1, '2021-07-10')]),
        radio=make_chart([('Stay', 'The Kid Laroi & Justin Bieber', 4, '2021-08-14')]),
    )
    got = chart_index.lookup(idx, 'stay', 'The Kid LAROI & Justin Bieber',
                             kind='song', exclude_chart='top100')
    assert [r['chart'] for r in got] == ['radio']


def test_title_is_matched_after_stripping_whitespace():
    idx = build(
        top100=make_chart([('Flowers', 'Miley Cyrus', 1, '2023-01-28')]),
        radio=make_chart([('  Flowers  ', 'Miley Cyrus', 2, '2023-02-04')]),
    )
    got = chart_index.lookup(idx, 'Flowers', 'Miley Cyrus',
                             kind='song', exclude_chart='top100')
    assert [r['chart'] for r in got] == ['radio']


def test_credit_change_mid_run_still_matches_on_primary_artist():
    """primary_artist is the grouping key, so a featured credit added later
    does not split one song into two."""
    idx = build(
        top100=make_chart([('Borderline', 'Tame Impala', 20, '2019-04-20')]),
        radio=make_chart([('Borderline', 'Tame Impala & JENNIE', 30, '2019-06-01')]),
    )
    got = chart_index.lookup(idx, 'Borderline', 'Tame Impala',
                             kind='song', exclude_chart='top100')
    assert [r['chart'] for r in got] == ['radio']


def test_different_artist_same_title_is_not_a_match():
    idx = build(
        top100=make_chart([('Hold On', 'Justin Bieber', 20, '2021-03-06')]),
        radio=make_chart([('Hold On', 'Wilson Phillips', 1, '1990-06-09')]),
    )
    got = chart_index.lookup(idx, 'Hold On', 'Justin Bieber',
                             kind='song', exclude_chart='top100')
    assert got == []


# ── Kind matching ───────────────────────────────────────────────────────────

def test_song_lookup_returns_no_album_charts():
    """A song called '1989' is not evidence about the album 1989."""
    idx = build(
        top100=make_chart([('1989', 'Taylor Swift', 5, '2014-11-01')], kind='song'),
        albums200=make_chart([('1989', 'Taylor Swift', 1, '2014-11-08')], kind='album'),
    )
    got = chart_index.lookup(idx, '1989', 'Taylor Swift',
                             kind='song', exclude_chart='top100')
    assert got == []


def test_album_lookup_returns_no_song_charts():
    idx = build(
        albums200=make_chart([('1989', 'Taylor Swift', 1, '2014-11-08')], kind='album'),
        top_album_sales=make_chart([('1989', 'Taylor Swift', 2, '2014-11-15')], kind='album'),
        top100=make_chart([('1989', 'Taylor Swift', 5, '2014-11-01')], kind='song'),
    )
    got = chart_index.lookup(idx, '1989', 'Taylor Swift',
                             kind='album', exclude_chart='albums200')
    assert [r['chart'] for r in got] == ['top_album_sales']


def test_artist_kind_charts_are_never_indexed():
    """An artist chart carries no title to match on."""
    idx = build(
        top100=make_chart([('Flowers', 'Miley Cyrus', 1, '2023-01-28')], kind='song'),
        artist100=make_chart([('Miley Cyrus', 'Miley Cyrus', 1, '2023-01-28')], kind='artist'),
    )
    assert 'artist100' not in set(idx['chart'].astype(str))


# ── Result shape ────────────────────────────────────────────────────────────

def test_origin_chart_is_excluded_from_its_own_results():
    idx = build(
        top100=make_chart([('Flowers', 'Miley Cyrus', 1, '2023-01-28')]),
        radio=make_chart([('Flowers', 'Miley Cyrus', 2, '2023-02-04')]),
    )
    got = chart_index.lookup(idx, 'Flowers', 'Miley Cyrus',
                             kind='song', exclude_chart='top100')
    assert [r['chart'] for r in got] == ['radio']


def test_peak_weeks_and_debut_come_from_the_whole_run():
    idx = build(
        top100=make_chart([('Flowers', 'Miley Cyrus', 50, '2023-01-28')]),
        radio=make_chart([
            ('Flowers', 'Miley Cyrus', 9, '2023-02-04'),
            ('Flowers', 'Miley Cyrus', 3, '2023-02-11'),
            ('Flowers', 'Miley Cyrus', 7, '2023-02-18'),
        ]),
    )
    row = chart_index.lookup(idx, 'Flowers', 'Miley Cyrus',
                             kind='song', exclude_chart='top100')[0]
    assert row['peak'] == 3
    assert row['weeks'] == 3
    assert row['debut'] == '2023-02-04'
    assert row['label'] == 'Radio'


def test_repeated_week_counts_once():
    """weeks is nunique of dates, not a row count."""
    idx = build(
        top100=make_chart([('Flowers', 'Miley Cyrus', 50, '2023-01-28')]),
        radio=make_chart([
            ('Flowers', 'Miley Cyrus', 9, '2023-02-04'),
            ('Flowers', 'Miley Cyrus', 9, '2023-02-04'),
        ]),
    )
    row = chart_index.lookup(idx, 'Flowers', 'Miley Cyrus',
                             kind='song', exclude_chart='top100')[0]
    assert row['weeks'] == 1


def test_results_sort_by_peak_then_by_weeks_descending():
    idx = build(
        top100=make_chart([('Flowers', 'Miley Cyrus', 1, '2023-01-28')]),
        a_chart=make_chart([('Flowers', 'Miley Cyrus', 9, '2023-02-04')]),
        b_chart=make_chart([('Flowers', 'Miley Cyrus', 2, '2023-02-04')]),
        c_chart=make_chart([
            ('Flowers', 'Miley Cyrus', 2, '2023-02-04'),
            ('Flowers', 'Miley Cyrus', 5, '2023-02-11'),
        ]),
    )
    got = chart_index.lookup(idx, 'Flowers', 'Miley Cyrus',
                             kind='song', exclude_chart='top100')
    assert [r['chart'] for r in got] == ['c_chart', 'b_chart', 'a_chart']


def test_later_is_true_when_the_other_run_began_after_this_one():
    idx = build(
        bubbling=make_chart([('Freestyle', 'Lil Baby', 5, '2022-08-01')]),
        top100=make_chart([('Freestyle', 'Lil Baby', 59, '2022-09-24')]),
    )
    row = chart_index.lookup(idx, 'Freestyle', 'Lil Baby', kind='song',
                             exclude_chart='bubbling',
                             origin_debut=pd.Timestamp('2022-08-01'))[0]
    assert row['later'] is True


def test_later_is_false_when_the_other_run_began_first():
    idx = build(
        bubbling=make_chart([('Freestyle', 'Lil Baby', 5, '2022-10-01')]),
        top100=make_chart([('Freestyle', 'Lil Baby', 59, '2022-09-24')]),
    )
    row = chart_index.lookup(idx, 'Freestyle', 'Lil Baby', kind='song',
                             exclude_chart='bubbling',
                             origin_debut=pd.Timestamp('2022-10-01'))[0]
    assert row['later'] is False


def test_later_is_none_when_the_origin_run_has_no_debut():
    idx = build(
        bubbling=make_chart([('Freestyle', 'Lil Baby', 5, '2022-10-01')]),
        top100=make_chart([('Freestyle', 'Lil Baby', 59, '2022-09-24')]),
    )
    row = chart_index.lookup(idx, 'Freestyle', 'Lil Baby', kind='song',
                             exclude_chart='bubbling', origin_debut=None)[0]
    assert row['later'] is None


def test_a_miss_returns_an_empty_list_not_an_error():
    idx = build(top100=make_chart([('Flowers', 'Miley Cyrus', 1, '2023-01-28')]))
    assert chart_index.lookup(idx, 'Not A Song', 'Nobody', kind='song') == []


# ── Build robustness ────────────────────────────────────────────────────────

def test_chart_missing_required_columns_is_logged_not_silently_dropped(caplog):
    """A silent skip shrinks coverage invisibly — the same class of bug as the
    row-floor truncations this project has already been bitten by."""
    broken = pd.DataFrame({'Song': ['Flowers'], 'Artist': ['Miley Cyrus']})
    chart_data = {
        'top100': (pd.DataFrame([('Flowers', 'Miley Cyrus', 1, '2023-01-28')],
                                columns=['Song', 'Artist', 'Rank', 'Date']), None),
        'broken': (broken, None),
    }
    chart_dt = {'top100': pd.to_datetime(chart_data['top100'][0]['Date'])}
    meta = {k: dict(label=k, group='Songs', depth=100, kind='song') for k in chart_data}

    with caplog.at_level(logging.WARNING):
        idx = chart_index.build(chart_data, chart_dt, meta)

    assert 'broken' in caplog.text
    assert 'broken' not in set(idx['chart'].astype(str))


def test_blank_artist_rows_do_not_raise():
    """Adult Contemporary has 20 blank-artist rows. Without na_action='ignore'
    a primary_artist that assumes a string raises for the whole build."""
    df = pd.DataFrame([
        ('Flowers', 'Miley Cyrus', 1, '2023-01-28'),
        ('Some Song', None, 2, '2023-01-28'),
    ], columns=['Song', 'Artist', 'Rank', 'Date'])
    chart_data = {'ac': (df, None)}
    chart_dt = {'ac': pd.to_datetime(df['Date'])}
    meta = {'ac': dict(label='AC', group='Songs', depth=100, kind='song')}

    idx = chart_index.build(chart_data, chart_dt, meta)
    assert len(idx) >= 1


def test_rows_without_a_usable_rank_or_date_are_dropped():
    df = pd.DataFrame([
        ('Flowers', 'Miley Cyrus', 1, '2023-01-28'),
        ('Flowers', 'Miley Cyrus', None, '2023-02-04'),
        ('Flowers', 'Miley Cyrus', 3, 'not a date'),
    ], columns=['Song', 'Artist', 'Rank', 'Date'])
    chart_data = {'top100': (df, None), 'radio': (df.copy(), None)}
    chart_dt = {k: pd.to_datetime(v[0]['Date'], errors='coerce')
                for k, v in chart_data.items()}
    meta = {k: dict(label=k, group='Songs', depth=100, kind='song') for k in chart_data}

    idx = chart_index.build(chart_data, chart_dt, meta)
    row = chart_index.lookup(idx, 'Flowers', 'Miley Cyrus',
                             kind='song', exclude_chart='top100')[0]
    assert row['weeks'] == 1


def test_index_is_sorted_so_lookup_does_not_fall_back_to_a_scan():
    """An unsorted MultiIndex makes .loc scan, which silently hands back the
    0.94s this index exists to avoid."""
    idx = build(
        top100=make_chart([('Zebra', 'B Artist', 1, '2023-01-28')]),
        radio=make_chart([('Apple', 'A Artist', 1, '2023-01-28')]),
    )
    assert idx.index.is_monotonic_increasing


# ── Autocomplete pool ───────────────────────────────────────────────────────

def test_title_pool_filters_by_prefix_and_kind():
    idx = build(
        top100=make_chart([('Flowers', 'Miley Cyrus', 1, '2023-01-28')], kind='song'),
        radio=make_chart([('Flowdown', 'Someone', 1, '2023-01-28')], kind='song'),
        albums200=make_chart([('Flowerboy', 'Tyler', 1, '2017-08-05')], kind='album'),
    )
    assert chart_index.title_pool(idx, kind='song', prefix='flow') == ['Flowdown', 'Flowers']
    assert chart_index.title_pool(idx, kind='album', prefix='flow') == ['Flowerboy']


def test_title_pool_returns_display_casing_not_the_casefolded_key():
    idx = build(top100=make_chart([('SICKO MODE', 'Travis Scott', 1, '2018-09-01')]))
    assert chart_index.title_pool(idx, kind='song', prefix='sicko') == ['SICKO MODE']


def test_suggest_returns_title_and_artist_pairs():
    """A title alone cannot drive the lookup, which is keyed on (title, artist).
    The search box has to offer the pair or the user has to guess the artist."""
    idx = build(
        top100=make_chart([('Hold On', 'Justin Bieber', 20, '2021-03-06')]),
        radio=make_chart([('Hold On', 'Wilson Phillips', 1, '1990-06-09')]),
    )
    got = chart_index.suggest(idx, kind='song', prefix='hold')
    assert sorted((s['title'], s['credit']) for s in got) == [
        ('Hold On', 'Justin Bieber'), ('Hold On', 'Wilson Phillips')]


def test_suggest_separates_the_credit_to_show_from_the_key_to_query():
    """primary_artist casefolds and drops featured acts, so it is a grouping key
    and never a label — a box offering 'the kid laroi' would look broken."""
    idx = build(top100=make_chart(
        [('Stay', 'The Kid LAROI & Justin Bieber', 1, '2021-07-10')]))
    got = chart_index.suggest(idx, kind='song', prefix='stay')[0]
    assert got['credit'] == 'The Kid LAROI & Justin Bieber'
    assert got['artist'] == 'the kid laroi'
    # And the key it hands back must actually resolve.
    assert chart_index.lookup(idx, got['title'], got['artist'], kind='song')


def test_suggest_ranks_by_how_many_charts_the_title_reached():
    idx = build(
        top100=make_chart([('Flow A', 'One Hit', 1, '2023-01-28')]),
        radio=make_chart([('Flow B', 'Many Charts', 1, '2023-01-28')]),
        digital=make_chart([('Flow B', 'Many Charts', 1, '2023-02-04')]),
    )
    got = chart_index.suggest(idx, kind='song', prefix='flow')
    assert got[0]['credit'] == 'Many Charts'
    assert got[0]['charts'] == 2


def test_suggest_is_kind_matched():
    idx = build(
        top100=make_chart([('Nineteen', 'A', 1, '2023-01-28')], kind='song'),
        albums200=make_chart([('Nineteen', 'B', 1, '2023-01-28')], kind='album'),
    )
    assert [s['credit'] for s in chart_index.suggest(idx, kind='album', prefix='nine')] == ['B']


def test_title_pool_respects_its_limit():
    rows = [(f'Song {i}', 'Artist', 1, '2023-01-28') for i in range(30)]
    idx = build(top100=make_chart(rows))
    assert len(chart_index.title_pool(idx, kind='song', prefix='song', limit=10)) == 10


# ── Characterization against the shipped Bubbling Under <-> Hot 100 pair ────

@pytest.fixture(scope='session')
def real_pair_index():
    """The index over the two charts _crossover_run used to join, built from
    the real CSVs rather than the app, so this stays a couple of seconds."""
    chart_data, chart_dt, meta = {}, {}, {}
    # Verbatim from the registry (app.py:352, app.py:384) — the baseline was
    # captured through it, so a paraphrase here fails as a false regression.
    labels = {'bubbling': 'Bubbling Under Hot 100', 'top100': 'The Hot 100™'}
    for key, csv in (('bubbling', 'bubbling_under.csv'), ('top100', 'hot100.csv')):
        path = DATA / csv
        if not path.exists():
            pytest.skip(f'{csv} not present')
        # Same dtype as app.py:124 loads the Hot 100 with. Category columns are
        # why na_action='ignore' is load-bearing — pandas calls a Categorical
        # mapper with np.nan whenever the column has NAs. Reading these as plain
        # object here would make the test miss the path the app actually takes.
        df = pd.read_csv(path, low_memory=False,
                         dtype={'Artist': 'category', 'Song': 'category'})
        chart_data[key] = (df, None)
        chart_dt[key] = pd.to_datetime(df['Date'], errors='coerce')
        meta[key] = dict(label=labels[key], group='Songs', depth=100, kind='song')
    return chart_index.build(chart_data, chart_dt, meta)


def test_generalized_lookup_reproduces_the_old_crossover_exactly(real_pair_index):
    """Captured from _crossover_run before it was deleted. 24 real crossovers
    and 10 real misses; every one must come back unchanged."""
    baseline = json.loads((FIXTURES / 'crossover_baseline.json').read_text())
    assert baseline, 'fixture is empty'

    mismatches = []
    for case in baseline:
        debut = pd.Timestamp(case['debut']) if case['debut'] else None
        got = chart_index.lookup(real_pair_index, case['song'], case['artist'],
                                 kind='song', exclude_chart=case['origin'],
                                 origin_debut=debut)
        want = case['expected']
        if want is None:
            if got:
                mismatches.append((case['song'], case['artist'], 'expected no crossover', got))
        else:
            if [want] != got:
                mismatches.append((case['song'], case['artist'], want, got))

    assert not mismatches, f'{len(mismatches)} regressions: {mismatches[:3]}'
