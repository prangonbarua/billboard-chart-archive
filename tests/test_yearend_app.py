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
    if 'top100' not in mod.YEAREND_YEARS:
        pytest.skip('year-end data not loaded')
    years = set(mod.YEAREND_YEARS['top100'])
    assert not (years & set(range(1991, 2006))), 'fabricated years present'
    assert not (years & set(range(1958, 1970))), 'fabricated years present'
    assert 2006 in years and 1970 in years


def test_no_chart_without_an_edition_has_data(mod):
    """The three charts Billboard publishes no year-end edition for.

    Each is answered with its current weekly chart rather than a 404, so a
    row here would be one arbitrary week stored as a year of history.
    """
    for key in ('rnb_hiphop', 'heatseekers', 'bubbling'):
        assert key not in mod.YEAREND_DATA, key
