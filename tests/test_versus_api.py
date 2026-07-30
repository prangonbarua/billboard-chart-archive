"""Wiring tests. These import app, which loads every CSV — slow by design.
Keep the fast unit tests in test_versus.py, which must never import app."""
import pandas as pd
import pytest


@pytest.fixture(scope='session')
def application():
    import app
    return app


def test_chart_dt_covers_every_loaded_chart(application):
    for key, (df, _dates) in application.CHART_DATA.items():
        if df is None or not len(df):
            continue
        dt = application.CHART_DT[key]
        assert len(dt) == len(df), f'{key}: dt length {len(dt)} != df length {len(df)}'
        assert dt.index.equals(df.index), f'{key}: dt index misaligned'
        assert pd.api.types.is_datetime64_any_dtype(dt), f'{key}: dt is not datetime64'
        assert dt.notna().all(), f'{key}: {dt.isna().sum()} unparseable dates'


def test_versus_rejects_unknown_chart(application):
    r = application.app.test_client().get('/api/versus?chart=nope&artists=Drake')
    assert r.status_code == 400


def test_versus_returns_one_entry_per_requested_artist(application):
    r = application.app.test_client().get(
        '/api/versus?chart=top100&artists=Taylor+Swift|Drake')
    assert r.status_code == 200
    body = r.get_json()
    assert [a['name'] for a in body['artists']] == ['Taylor Swift', 'Drake']
    assert body['chart']['key'] == 'top100'
    assert body['chart']['depth'] == 100


def test_versus_unknown_artist_returns_null_stats_not_an_error(application):
    r = application.app.test_client().get(
        '/api/versus?chart=top100&artists=Drake|Zzzznotanartist')
    assert r.status_code == 200
    artists = r.get_json()['artists']
    assert artists[0]['entries'] > 0
    assert artists[1]['entries'] == 0
    assert artists[1]['timeline'] == []


def test_versus_does_not_substring_match_artists(application):
    """artist_match_mask must be used: 'Tyla' must not absorb 'Tyla Yaweh'."""
    r = application.app.test_client().get('/api/versus?chart=top100&artists=Tyla')
    rows = application._versus_artist_rows('top100', 'Tyla')
    credits = set(rows['Artist'].astype(str))
    assert not any('yaweh' in c.casefold() for c in credits)
    assert r.status_code == 200


def test_versus_empty_artists_param_returns_empty_list(application):
    r = application.app.test_client().get('/api/versus?chart=top100&artists=')
    assert r.status_code == 200
    assert r.get_json()['artists'] == []


def test_artists_endpoint_without_chart_is_unchanged(application):
    r = application.app.test_client().get('/api/artists?q=tay')
    assert r.status_code == 200
    names = r.get_json()['artists']
    assert names == [a for a in application.MODERN_ARTISTS
                     if a.lower().startswith('tay')][:50]


def test_country_pool_holds_acts_the_hot100_pool_misses(application):
    pool = set(application.CHART_ARTISTS['country_airplay'])
    assert len(pool) > 500
    # Reached country radio without a comparable Hot 100 footprint.
    assert any('Rhett Akins' == a for a in pool)


def test_adult_contemporary_pool_reaches_before_1990(application):
    """MODERN_ARTISTS is filtered to 1990+; this chart starts in 1961."""
    pool = set(application.CHART_ARTISTS['adult_contemporary'])
    assert 'ABBA' in pool
    # and prove it discriminates:
    assert 'ABBA' not in application.MODERN_ARTISTS


def test_artists_endpoint_honours_the_chart_param(application):
    r = application.app.test_client().get('/api/artists?chart=country_airplay&q=a')
    assert r.status_code == 200
    names = r.get_json()['artists']
    assert names
    assert set(names) <= set(application.CHART_ARTISTS['country_airplay'])
    assert len(names) <= 50


def test_artists_endpoint_falls_back_on_unknown_chart(application):
    r = application.app.test_client().get('/api/artists?chart=nope&q=tay')
    assert r.status_code == 200


def test_versus_page_renders_without_artists(application):
    r = application.app.test_client().get('/versus')
    assert r.status_code == 200
    assert b'Versus' in r.data


def test_versus_page_state_lives_in_the_url(application):
    r = application.app.test_client().get(
        '/versus?chart=country_airplay&artists=Luke+Combs|Morgan+Wallen')
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert 'country_airplay' in body
    assert 'Luke Combs' in body


def test_versus_link_is_in_the_nav(application):
    body = application.app.test_client().get('/top100').get_data(as_text=True)
    assert '/versus' in body
