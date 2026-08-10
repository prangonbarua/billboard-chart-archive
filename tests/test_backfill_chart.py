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


# ── Week generation ─────────────────────────────────────────────────────────
# Charts are not all Saturday-dated for their whole lives. Asking for a weekday
# a chart never used is not a loud failure: Billboard clamps to a nearby real
# week and the served-week guard rejects it, so the era is quietly never
# fetched. These pin the measured calendars.

def weekdays(weeks):
    from datetime import datetime
    return {datetime.strptime(w, '%Y-%m-%d').strftime('%a') for w in weeks}


def test_uncalendared_chart_keeps_its_first_weeks_weekday():
    weeks = backfill_chart.chart_weeks('gospel-songs', '2005-03-19', '2005-04-16')
    assert weeks == ['2005-03-19', '2005-03-26', '2005-04-02',
                     '2005-04-09', '2005-04-16']


def test_country_switches_from_monday_to_saturday_dating():
    """Measured: last Monday week 1961-12-25, first Saturday week 1962-01-06."""
    weeks = backfill_chart.chart_weeks('country-songs', '1958-10-20', '1962-01-13')
    assert weeks[0] == '1958-10-20'
    assert weekdays(weeks) == {'Mon', 'Sat'}
    boundary = weeks[weeks.index('1961-12-25'):]
    assert boundary == ['1961-12-25', '1962-01-06', '1962-01-13'], \
        'the 12-day gap across the dating change was not reproduced'


def test_rnb_hiatus_weeks_are_never_requested():
    """Suspended after 1963-11-23, resumed 1965-01-30. All 61 weeks clamp."""
    weeks = backfill_chart.chart_weeks('r-b-hip-hop-songs', '1958-10-20', '1965-02-06')
    assert '1963-11-23' in weeks and '1965-01-30' in weeks
    assert [w for w in weeks if '1963-11-23' < w < '1965-01-30'] == []


def test_first_week_argument_still_bounds_a_calendared_chart():
    weeks = backfill_chart.chart_weeks('country-songs', '1962-01-06', '1962-01-20')
    assert weeks == ['1962-01-06', '1962-01-13', '1962-01-20']
