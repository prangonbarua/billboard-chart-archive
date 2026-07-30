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
    df = frame([
        ('2024-01-06', 2, 'Short', 'X'),
        ('2024-01-06', 2, 'Long', 'X'),
        ('2024-01-13', 4, 'Long', 'X'),
        ('2024-01-20', 6, 'Long', 'X'),
    ])
    assert versus.compute_artist_stats(df)['biggest_hit'] == 'Long'


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


def test_display_name_uses_modal_capitalization():
    df = frame([
        ('2024-01-06', 5, 'Hit', 'The Kid LAROI'),
        ('2024-01-13', 5, 'Hit', 'The Kid LAROI'),
        ('2024-01-20', 5, 'Hit', 'The Kid Laroi'),
    ])
    assert versus.display_name(df, 'the kid laroi') == 'The Kid LAROI'


def test_display_name_falls_back_to_the_query():
    assert versus.display_name(frame([]), 'nobody') == 'nobody'
