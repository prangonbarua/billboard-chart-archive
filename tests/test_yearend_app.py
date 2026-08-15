"""Year-end data loads, and only genuine years reach it."""
import pytest


@pytest.fixture(scope='session')
def mod():
    import app
    return app


def test_yearend_dicts_exist(mod):
    assert isinstance(mod.YEAREND_DATA, dict)
    assert isinstance(mod.YEAREND_YEARS, dict)


def test_every_yearend_chart_is_a_registered_chart(mod):
    assert set(mod.YEAREND_DATA) <= set(mod.CHARTS)


def test_years_are_descending_and_unique(mod):
    for key, years in mod.YEAREND_YEARS.items():
        assert years == sorted(set(years), reverse=True), key


def test_years_match_the_frame(mod):
    for key, df in mod.YEAREND_DATA.items():
        assert set(df['Year']) == set(mod.YEAREND_YEARS[key]), key


def test_hot100_has_no_fabricated_years(mod):
    """No stored Hot 100 year may repeat another year's ranking.

    This used to assert that 1958-1969 and 1991-2005 were ABSENT. billboard.com
    answers those URLs with 1970's and 2006's rankings, so the guard dropped
    them and the chart began at 1970. They are now filled from Wikipedia's
    transcription of the printed charts, each verified against that year's own
    weekly Hot 100 data before being stored -- see
    scripts/backfill_yearend_wikipedia.py.

    So their absence is no longer the invariant; it was only ever a proxy for
    one. What still has to hold is what that absence protected against: a
    clamped copy IS a year that repeats another year's ranking, and two
    orderings of a hundred songs do not coincide by accident. Asserting that
    directly keeps the protection and no longer forbids the real years.
    """
    if 'top100' not in mod.YEAREND_YEARS:
        pytest.skip('year-end data not loaded')
    years = set(mod.YEAREND_YEARS['top100'])
    # Not a hardcoded end year: next year's chart must not fail this.
    assert min(years) == 1958, 'Hot 100 year-end should start at 1958'
    assert years == set(range(min(years), max(years) + 1)), 'year-end has gaps'

    seen = {}
    for year, rows in mod.YEAREND_DATA['top100'].groupby('Year'):
        rows = rows.sort_values('Rank')
        sig = tuple(zip(rows['Rank'], rows['Song'], rows['Artist']))
        assert sig not in seen, f'{year} repeats {seen[sig]}: clamped copy'
        seen[sig] = year


def test_no_chart_without_an_edition_has_data(mod):
    """The charts Billboard publishes no year-end edition for.

    Each is answered with its current weekly chart rather than a 404, so a
    row here would be one arbitrary week stored as a year of history.

    rnb_hiphop was on this list and has been removed: it does have a year-end
    edition, at r-and-b-hip-hop-airplay-songs. The slug is unreachable from the
    chart's label because '&' expands to 'and', giving 'randb' where Billboard
    writes 'r-and-b', and the earlier check gave up after two other candidates.
    """
    for key in ('heatseekers', 'bubbling', 'rnb_songs', 'uk_songs',
                'top_album_sales', 'japan_hot100'):
        assert key not in mod.YEAREND_DATA, key
