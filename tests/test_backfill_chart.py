"""Regression tests for the backfill clamp guard.

Billboard answers an out-of-range date by re-serving the nearest published
week under the date you asked for. The guard catches that by comparing each
fetched week's ranking against the week before it. These tests pin the
comparison to the *chronological* predecessor, which is what makes the guard
survive a re-run over a partly-filled CSV.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import backfill_chart

WEEKS = ['2000-01-01', '2000-01-08', '2000-01-15',
         '2000-01-22', '2000-01-29', '2000-02-05']

# Billboard published a chart only on these dates. The other two are dates it
# answers by re-serving the previous published week.
PUBLISHED = ['2000-01-01', '2000-01-15', '2000-01-22', '2000-02-05']


def rows_for(week):
    """A ranking unique to each published week."""
    n = WEEKS.index(week)
    return [{'Date': week, 'Rank': r, 'Song': f'Song {n}-{r}',
             'Artist': f'Artist {n}-{r}', 'Last Week': '-',
             'Peak Position': r, 'Weeks on Chart': 1} for r in (1, 2, 3)]


def fake_billboard(slug, week):
    """Stand-in for scrape_billboard_chart, reproducing Billboard's clamping."""
    if week in PUBLISHED:
        return rows_for(week)
    served = max(p for p in PUBLISHED if p < week)
    # Clamped: the previous week's ranking, stamped with the date we asked for.
    return [dict(r, Date=week) for r in rows_for(served)]


@pytest.fixture
def run_backfill(tmp_path, monkeypatch):
    csv_path = tmp_path / 'chart.csv'

    def run(present_weeks):
        if present_weeks:
            rows = [r for w in present_weeks for r in rows_for(w)]
            pd.DataFrame(rows).to_csv(csv_path, index=False)
        monkeypatch.setattr(backfill_chart, 'scrape_billboard_chart', fake_billboard)
        monkeypatch.setattr(backfill_chart.time, 'sleep', lambda *_: None)
        monkeypatch.setattr(sys, 'argv',
                            ['backfill_chart.py', 'some-slug', str(csv_path),
                             WEEKS[0], WEEKS[-1]])
        backfill_chart.main()
        return pd.read_csv(csv_path)

    return run


def signatures(df):
    """date -> (rank, song, artist) tuple, for adjacent-week comparison."""
    ordered = df.sort_values(['Date', 'Rank'])
    return {d: tuple(zip(w['Rank'], w['Song'], w['Artist']))
            for d, w in ordered.groupby('Date')}


def test_contiguous_backfill_skips_every_unpublished_week(run_backfill):
    """A first pass over an empty CSV writes only the published weeks."""
    df = run_backfill([])
    assert sorted(df['Date'].unique()) == PUBLISHED


def test_rerun_over_partial_csv_does_not_fabricate_weeks(run_backfill):
    """Re-running to retry stragglers must still reject clamped responses.

    The missing weeks are non-contiguous: 2000-01-08 follows a present week,
    2000-01-29 follows a different one. A guard that tracks a single rolling
    signature compares 2000-01-29 against the wrong week and writes it.
    """
    df = run_backfill(PUBLISHED)
    assert '2000-01-29' not in set(df['Date']), \
        'clamped week was fabricated on re-run'
    assert sorted(df['Date'].unique()) == PUBLISHED


def test_no_adjacent_week_repeats_a_ranking(run_backfill):
    """The invariant the guard exists to protect."""
    df = run_backfill(PUBLISHED)
    sigs = signatures(df)
    dates = sorted(sigs)
    twins = [(a, b) for a, b in zip(dates, dates[1:]) if sigs[a] == sigs[b]]
    assert twins == [], f'adjacent weeks share a ranking: {twins}'
