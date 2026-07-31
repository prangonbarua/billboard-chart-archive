"""Unit tests for versus stat computation. Must never import app — these run
against synthetic frames in milliseconds."""
import pandas as pd
import pytest

import versus


def frame(records):
    """records: (date, rank, song, artist) tuples."""
    df = pd.DataFrame(records, columns=['Date', 'Rank', 'Song', 'Artist'])
    df['Date'] = pd.to_datetime(df['Date'])
    return df


def test_primary_artist_strips_featured_credits():
    assert versus.primary_artist('Weezer Featuring Best Coast') == 'weezer'
    assert versus.primary_artist('  Drake  ') == 'drake'
    assert versus.primary_artist('Future & Metro Boomin') == 'future'


def test_peak_comes_from_rank_history_not_a_column():
    # The stored Peak Position column is corrupt repo-wide; a frame carrying a
    # lying column must not influence the result.
    df = frame([
        ('2024-01-06', 40, 'Song A', 'X'),
        ('2024-01-13', 12, 'Song A', 'X'),
        ('2024-01-20', 25, 'Song A', 'X'),
    ])
    df['Peak Position'] = 1
    stats = versus.compute_artist_stats(df)
    assert stats['best_peak'] == 12


def test_credit_drift_keys_as_one_song():
    df = frame([
        ('2024-01-06', 10, 'Hit', 'X'),
        ('2024-01-13', 8, 'Hit', 'X Featuring Y'),
        ('2024-01-20', 9, 'Hit', 'X'),
    ])
    stats = versus.compute_artist_stats(df)
    assert stats['entries'] == 1
    assert stats['total_weeks_charted'] == 3


def test_duplicate_scrape_rows_do_not_inflate_counts():
    df = frame([
        ('2024-01-06', 1, 'Hit', 'X'),
        ('2024-01-06', 1, 'Hit', 'X'),   # duplicate scrape row
        ('2024-01-13', 1, 'Hit', 'X'),
    ])
    stats = versus.compute_artist_stats(df)
    assert stats['weeks_at_1'] == 2
    assert stats['total_weeks_charted'] == 2


def test_number_ones_counts_songs_not_weeks():
    df = frame([
        ('2024-01-06', 1, 'Hit A', 'X'),
        ('2024-01-13', 1, 'Hit A', 'X'),
        ('2024-01-20', 1, 'Hit A', 'X'),
        ('2024-01-27', 1, 'Hit B', 'X'),
    ])
    stats = versus.compute_artist_stats(df)
    assert stats['number_ones'] == 2
    assert stats['weeks_at_1'] == 4


def test_top_tiers_count_distinct_songs_by_peak():
    df = frame([
        ('2024-01-06', 5, 'Hit A', 'X'),
        ('2024-01-13', 3, 'Hit A', 'X'),
        ('2024-01-06', 30, 'Hit B', 'X'),
        ('2024-01-06', 80, 'Hit C', 'X'),
    ])
    stats = versus.compute_artist_stats(df)
    assert stats['top_10s'] == 1
    assert stats['top_40s'] == 2
    assert stats['entries'] == 3


def test_biggest_hit_breaks_peak_ties_by_weeks():
    # Both peak at 2, in different weeks — two songs cannot share one
    # (Date, Rank) slot on a real chart. The longer run wins the tie.
    # Names are deliberate: 'Zenith' sorts AFTER 'Alpha', so groupby's
    # alphabetical order puts the loser first. Only the weeks tie-break
    # can promote the winner, which is what this test exists to check.
    df = frame([
        ('2024-01-06', 2, 'Alpha', 'X'),
        ('2024-01-13', 2, 'Zenith', 'X'),
        ('2024-01-20', 4, 'Zenith', 'X'),
        ('2024-01-27', 6, 'Zenith', 'X'),
    ])
    assert versus.compute_artist_stats(df)['biggest_hit'] == 'Zenith'


def test_timeline_is_best_rank_per_week_ascending():
    df = frame([
        ('2024-01-13', 20, 'Hit A', 'X'),
        ('2024-01-13', 4, 'Hit B', 'X'),
        ('2024-01-06', 9, 'Hit A', 'X'),
    ])
    assert versus.compute_artist_stats(df)['timeline'] == [
        {'date': '2024-01-06', 'rank': 9},
        {'date': '2024-01-13', 'rank': 4},
    ]


def test_unknown_artist_returns_null_stats_not_an_error():
    stats = versus.compute_artist_stats(frame([]))
    assert stats['entries'] == 0
    assert stats['best_peak'] is None
    assert stats['timeline'] == []


def test_unrankable_rows_are_dropped():
    df = frame([
        ('2024-01-06', '-', 'Hit', 'X'),
        ('2024-01-13', 7, 'Hit', 'X'),
    ])
    stats = versus.compute_artist_stats(df)
    assert stats['best_peak'] == 7
    assert stats['total_weeks_charted'] == 1


def test_artist_kind_has_no_song_level_stats():
    df = frame([
        ('2024-01-06', 3, 'X', 'X'),
        ('2024-01-13', 2, 'X', 'X'),
    ])
    stats = versus.compute_artist_stats(df, kind='artist')
    assert stats['entries'] is None
    assert stats['biggest_hit'] is None
    assert stats['best_peak'] == 2
    assert stats['total_weeks_charted'] == 2


def test_artist_kind_nulls_distinct_song_counts():
    """top_10s, top_40s, and number_ones are all built by counting or
    filtering the per-song grouping. On an artist chart, Song == Artist for
    this artist's own filtered rows, so that grouping collapses to exactly
    one group every time — under kind='song' these are genuine counts, but
    under kind='artist' they would just be a boolean (0 or 1) dressed as a
    number, and must be nulled instead of displayed as if they counted
    distinct songs."""
    df = frame([
        ('2024-01-06', 1, 'X', 'X'),
        ('2024-01-13', 5, 'X', 'X'),
    ])

    # Sanity check: under kind='song' (the normal case) these are real counts.
    song_stats = versus.compute_artist_stats(df, kind='song')
    assert song_stats['top_10s'] == 1
    assert song_stats['top_40s'] == 1
    assert song_stats['number_ones'] == 1

    artist_stats = versus.compute_artist_stats(df, kind='artist')
    assert artist_stats['top_10s'] is None
    assert artist_stats['top_40s'] is None
    assert artist_stats['number_ones'] is None
    # Stats that remain meaningful for an artist chart must stay real numbers.
    assert artist_stats['weeks_at_1'] == 1
    assert artist_stats['best_peak'] == 1
    assert artist_stats['total_weeks_charted'] == 2


def test_display_name_uses_modal_capitalization():
    df = frame([
        ('2024-01-06', 5, 'Hit', 'The Kid LAROI'),
        ('2024-01-13', 5, 'Hit', 'The Kid LAROI'),
        ('2024-01-20', 5, 'Hit', 'The Kid Laroi'),
    ])
    assert versus.display_name(df, 'the kid laroi') == 'The Kid LAROI'


def test_display_name_falls_back_to_the_query():
    assert versus.display_name(frame([]), 'nobody') == 'nobody'
