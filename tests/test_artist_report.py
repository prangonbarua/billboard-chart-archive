"""Wiring tests for the all-charts artist report. These import app, which
loads every CSV — slow by design. Fixture artists are real rows in data/."""
import pytest


@pytest.fixture(scope='session')
def application():
    import app
    return app


def test_summaries_cover_more_than_hot100_and_albums(application):
    """The bug this feature exists to fix: the old report read two frames."""
    result = application.artist_chart_summaries('Taylor Swift')
    keys = {c['key'] for c in result['charts']}
    assert len(keys) > 2
    assert 'country_airplay' in keys, 'format charts must reach the report'


def test_summaries_only_include_charts_with_rows(application):
    result = application.artist_chart_summaries('Aaron Watson')
    for c in result['charts']:
        assert c['total_weeks_charted'] > 0, f"{c['key']} has no weeks charted"
    assert result['hidden'] == len(application.CHARTS) - len(result['charts'])


def test_summaries_preserve_registry_order(application):
    result = application.artist_chart_summaries('Taylor Swift')
    order = [k for k in application.CHARTS if k in {c['key'] for c in result['charts']}]
    assert [c['key'] for c in result['charts']] == order


def test_artist100_stats_are_none_not_zero(application):
    """An artist chart's song-level counts are booleans in disguise. Rendering
    them as 0 beside a real 0 would be a lie the em dash exists to prevent."""
    import versus
    result = application.artist_chart_summaries('Drake')
    row = next(c for c in result['charts'] if c['key'] == 'artist100')
    for key in versus._ARTIST_KIND_NULLS:
        assert row[key] is None, f'{key} should be None on an artist chart'
    assert row['best_peak'] is not None, 'best_peak is meaningful on artist charts'


def test_summaries_omit_timeline(application):
    """519 KB of timeline has no business in a 3 KB coverage table."""
    result = application.artist_chart_summaries('Taylor Swift')
    assert all('timeline' not in c for c in result['charts'])


def test_summaries_none_for_unknown_artist(application):
    assert application.artist_chart_summaries('Zzzz Not A Real Artist') is None


def test_detail_includes_pre_1990_history(application):
    """The 1990 cutoff dropped 163,861 Hot 100 rows — 46% of that chart."""
    detail = application.artist_chart_detail('The Supremes', 'top100')
    assert detail is not None, 'a pre-1990 artist must have a Hot 100 report'
    earliest = min(p['date'] for s in detail['series'].values() for p in s)
    assert earliest < '1990-01-01'


def test_detail_reads_the_requested_chart_not_hot100(application):
    detail = application.artist_chart_detail('Aaron Watson', 'country_airplay')
    assert detail is not None
    assert detail['chart']['key'] == 'country_airplay'
    assert detail['items']


def test_detail_items_sorted_by_weeks_then_peak(application):
    detail = application.artist_chart_detail('Taylor Swift', 'top100')
    keys = [(-i['weeks'], i['peak']) for i in detail['items']]
    assert keys == sorted(keys)


def test_detail_serves_albums_for_albums200(application):
    detail = application.artist_chart_detail('Taylor Swift', 'albums200')
    assert detail['chart']['kind'] == 'album'
    assert detail['items']


def test_detail_none_when_artist_absent_from_chart(application):
    assert application.artist_chart_detail('Aaron Watson', 'globalexus') is None


def test_artist_chart_endpoint_returns_detail(application):
    c = application.app.test_client()
    r = c.get('/api/artist-chart?artist=Taylor+Swift&chart=country_airplay')
    assert r.status_code == 200
    body = r.get_json()
    assert body['chart']['key'] == 'country_airplay'
    assert body['items']


def test_artist_chart_endpoint_rejects_unknown_chart(application):
    c = application.app.test_client()
    assert c.get('/api/artist-chart?artist=Drake&chart=nope').status_code == 400


def test_artist_chart_endpoint_rejects_blank_artist(application):
    c = application.app.test_client()
    assert c.get('/api/artist-chart?artist=&chart=top100').status_code == 400


def test_artist_chart_endpoint_404s_when_artist_absent(application):
    c = application.app.test_client()
    r = c.get('/api/artist-chart?artist=Aaron+Watson&chart=globalexus')
    assert r.status_code == 404


def test_all_artists_pool_covers_every_chart(application):
    union = set()
    for names in application.CHART_ARTISTS.values():
        union |= set(names)
    assert set(application.ALL_ARTISTS) == union
    assert application.ALL_ARTISTS == sorted(application.ALL_ARTISTS)


def test_autocomplete_finds_a_pre_1990_artist(application):
    """The Supremes are reportable but absent from MODERN_ARTISTS."""
    assert 'The Supremes' not in application.MODERN_ARTISTS
    c = application.app.test_client()
    got = c.get('/api/artists?q=the+supremes').get_json()['artists']
    assert 'The Supremes' in got


def test_autocomplete_finds_a_country_only_artist(application):
    assert 'Aaron Watson' not in application.MODERN_ARTISTS
    c = application.app.test_client()
    got = c.get('/api/artists?q=aaron+watson').get_json()['artists']
    assert 'Aaron Watson' in got


def test_autocomplete_chart_scoped_pool_unchanged(application):
    """The versus page passes ?chart= and must keep its own pool."""
    c = application.app.test_client()
    got = c.get('/api/artists?chart=country_airplay&q=aaron').get_json()['artists']
    assert set(got) <= set(application.CHART_ARTISTS['country_airplay'])


def test_analyze_renders_a_format_chart_row(application):
    c = application.app.test_client()
    r = c.post('/analyze', data={'artist_name': 'Taylor Swift'})
    assert r.status_code == 200
    assert 'Country Airplay' in r.get_data(as_text=True)


def test_analyze_works_for_a_pre_1990_artist(application):
    """This 302'd to /search with 'No results found' before this change."""
    c = application.app.test_client()
    r = c.post('/analyze', data={'artist_name': 'The Supremes'})
    assert r.status_code == 200


def test_analyze_works_for_a_country_only_artist(application):
    c = application.app.test_client()
    r = c.post('/analyze', data={'artist_name': 'Aaron Watson'})
    assert r.status_code == 200
    assert 'Country Airplay' in r.get_data(as_text=True)


def test_analyze_defaults_to_the_most_charted_chart(application):
    c = application.app.test_client()
    body = c.post('/analyze', data={'artist_name': 'Aaron Watson'}).get_data(as_text=True)
    assert 'data-selected-chart="country_airplay"' in body


def test_analyze_still_redirects_for_an_unknown_artist(application):
    c = application.app.test_client()
    r = c.post('/analyze', data={'artist_name': 'Zzzz Not A Real Artist'})
    assert r.status_code == 302


def test_results_page_has_no_tab_switcher(application):
    """The Songs/Albums tabs are replaced by coverage rows."""
    c = application.app.test_client()
    body = c.post('/analyze', data={'artist_name': 'Taylor Swift'}).get_data(as_text=True)
    assert 'switchTab' not in body
    assert 'id="albumsTab"' not in body


def test_results_page_rows_carry_chart_keys(application):
    c = application.app.test_client()
    body = c.post('/analyze', data={'artist_name': 'Taylor Swift'}).get_data(as_text=True)
    assert 'data-chart="albums200"' in body
    assert 'data-chart="country_airplay"' in body
