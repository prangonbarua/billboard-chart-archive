"""Wiring tests. These import app, which loads every CSV — slow by design.
Keep the fast unit tests in test_versus.py, which must never import app."""
import csv
import io
import re

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


def test_app_shares_versus_credit_parsing_rather_than_copying_it(application):
    """Song keying and artist selection must not drift apart; a second copy of
    either regex in app.py is exactly how they would."""
    import versus as versus_mod
    assert application.primary_artist is versus_mod.primary_artist
    assert application.artist_match_mask is versus_mod.artist_match_mask
    assert application._CREDIT_MARKER_RE is versus_mod._CREDIT_MARKER_RE
    assert not hasattr(application, '_CREDIT_SPLIT_RE')


def test_slash_and_parenthetical_credits_reach_the_versus_totals(application):
    """Elton John's slash-credited and backing-band #1s were being dropped."""
    r = application.app.test_client().get('/api/versus?chart=top100&artists=Elton+John')
    assert r.status_code == 200
    assert r.get_json()['artists'][0]['number_ones'] >= 9


def _versus_csv(application, query):
    r = application.app.test_client().get('/download-versus-csv?' + query)
    return r, r.get_data(as_text=True)


def test_versus_csv_carries_the_scorecard_and_the_weekly_ranks(application):
    r, body = _versus_csv(application, 'chart=top100&artists=Taylor+Swift|Drake')
    assert r.status_code == 200
    assert r.mimetype == 'text/csv'
    rows = list(csv.reader(io.StringIO(body)))
    header = next(r for r in rows if r and r[0] == 'Stat')
    assert header[1:] == ['Taylor Swift', 'Drake']
    labels = [r[0] for r in rows if r]
    for expected, _key in application._VERSUS_CSV_ROWS:
        assert expected in labels
    # Weekly section: a date row with a rank for at least one artist.
    dates = [r for r in rows if r and re.fullmatch(r'\d{1,2}/\d{1,2}/\d{4}', r[0])]
    assert len(dates) > 100
    assert all(len(r) == 3 for r in dates)
    assert any(r[1] and r[2] for r in dates)


def test_versus_csv_blanks_stats_nulled_by_chart_kind(application):
    """Artist 100 nulls the song-level counts; blank, never a misleading 0."""
    _r, body = _versus_csv(application, 'chart=artist100&artists=Drake')
    rows = {r[0]: r[1:] for r in csv.reader(io.StringIO(body)) if r}
    assert rows['Entries'] == ['']
    assert rows['Number ones'] == ['']
    assert rows['Best peak'] != ['']


def test_versus_csv_filename_names_the_artists_and_chart(application):
    r, _body = _versus_csv(application, 'chart=country_airplay&artists=Luke+Combs')
    assert 'Luke_Combs_country_airplay.csv' in r.headers['Content-Disposition']


def test_versus_csv_rejects_bad_input(application):
    assert _versus_csv(application, 'chart=nope&artists=Drake')[0].status_code == 400
    assert _versus_csv(application, 'chart=top100&artists=')[0].status_code == 400


def test_artist_csv_defaults_to_the_hot_100_unchanged(application):
    """The artist report page links here with no query string; its filename
    and contents must not move."""
    r = application.app.test_client().get('/download-csv/Drake')
    assert r.status_code == 200
    assert 'Drake_Chart_History.csv' in r.headers['Content-Disposition']
    rows = list(csv.reader(io.StringIO(r.get_data(as_text=True))))
    assert rows[0][0] == 'Song' and len(rows[0]) > 100
    assert rows[1][0] == 'Image'


def test_artist_csv_can_be_scoped_to_another_chart(application):
    r = application.app.test_client().get(
        '/download-csv/Luke Combs?chart=country_airplay')
    assert r.status_code == 200
    assert 'Luke_Combs_country_airplay_Chart_History.csv' in \
        r.headers['Content-Disposition']
    rows = list(csv.reader(io.StringIO(r.get_data(as_text=True))))
    titles = set(rows[0][1:])
    assert titles
    # Scoped, not the Hot 100 slice: this is the country chart's own frame.
    country = application._versus_artist_rows('country_airplay', 'Luke Combs')
    assert titles <= set(country['Song'].astype(str))


def test_artist_csv_rejects_an_unknown_chart(application):
    r = application.app.test_client().get('/download-csv/Drake?chart=nope')
    assert r.status_code == 400


def test_artist_csv_404s_for_an_artist_absent_from_that_chart(application):
    r = application.app.test_client().get(
        '/download-csv/Zzzznotanartist?chart=country_airplay')
    assert r.status_code == 404


def test_versus_chips_link_each_artists_own_csv(application):
    body = application.app.test_client().get('/versus').get_data(as_text=True)
    assert '/download-csv/' in body
    assert 'chip-csv' in body


def test_versus_page_offers_the_csv_download(application):
    body = application.app.test_client().get(
        '/versus?chart=top100&artists=Drake').get_data(as_text=True)
    assert '/download-versus-csv' in body


def test_versus_link_is_in_the_nav(application):
    body = application.app.test_client().get('/top100').get_data(as_text=True)
    assert '/versus' in body
