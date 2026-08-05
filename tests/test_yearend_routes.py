"""The ?view=yearend view on the existing chart routes."""
import re

import pytest


@pytest.fixture(scope='session')
def client():
    import app
    return app.app.test_client()


@pytest.fixture(scope='session')
def mod():
    import app
    return app


def test_yearend_view_renders(client, mod):
    if 'top100' not in mod.YEAREND_YEARS:
        pytest.skip('year-end data not loaded')
    r = client.get('/top100?view=yearend')
    assert r.status_code == 200


def test_defaults_to_newest_real_year(client, mod):
    if 'top100' not in mod.YEAREND_YEARS:
        pytest.skip('year-end data not loaded')
    newest = mod.YEAREND_YEARS['top100'][0]
    r = client.get('/top100?view=yearend')
    assert str(newest).encode() in r.data


def test_specific_year_renders(client, mod):
    if 'top100' not in mod.YEAREND_YEARS:
        pytest.skip('year-end data not loaded')
    r = client.get('/top100?view=yearend&year=2020')
    assert r.status_code == 200
    assert b'Blinding Lights' in r.data


def test_fabricated_year_redirects(client, mod):
    """2000 is a year Billboard fabricates. It must never render."""
    if 'top100' not in mod.YEAREND_YEARS:
        pytest.skip('year-end data not loaded')
    r = client.get('/top100?view=yearend&year=2000')
    assert r.status_code == 302


def test_malformed_year_does_not_500(client, mod):
    if 'top100' not in mod.YEAREND_YEARS:
        pytest.skip('year-end data not loaded')
    for bad in ('abc', '', '2020.5', '-1', '99999'):
        r = client.get(f'/top100?view=yearend&year={bad}')
        assert r.status_code in (200, 302), bad


def test_weekly_view_is_unchanged(client):
    r = client.get('/top100')
    assert r.status_code == 200
    assert b'Weeks' in r.data


def test_nav_lists_only_charts_that_have_a_year_end_edition(client, mod):
    """The nav group is built from YEAREND_YEARS. Building it from CHARTS would
    put links in the nav for the three charts Billboard publishes no year-end
    edition of, each of which only redirects back with an error."""
    if not mod.YEAREND_YEARS:
        pytest.skip('year-end data not loaded')
    body = client.get('/top100').get_data(as_text=True)
    assert '>Year-End</div>' in body
    for key in mod.CHARTS:
        link = f'/{key}?view=yearend'
        if key in mod.YEAREND_YEARS:
            assert link in body, f'{key}: missing from the year-end nav'
        else:
            assert link not in body, f'{key}: has no year-end edition but is linked'


def test_nav_marks_the_year_end_entry_active_not_the_weekly_one(client, mod):
    """Both entries are the same endpoint, so the active state has to come from
    the view, not from request.endpoint alone."""
    if 'top100' not in mod.YEAREND_YEARS:
        pytest.skip('year-end data not loaded')
    body = client.get('/top100?view=yearend').get_data(as_text=True)
    assert re.search(r'href="/top100\?view=yearend"\s+class="active"', body)
    assert not re.search(r'href="/top100"\s+class="active"', body)


def test_chart_without_yearend_redirects(client, mod):
    missing = [k for k in mod.CHARTS if k not in mod.YEAREND_YEARS]
    if not missing:
        pytest.skip('every chart has year-end data')
    r = client.get(f'/{missing[0]}?view=yearend')
    assert r.status_code == 302
