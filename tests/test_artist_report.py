"""Wiring tests for the all-charts artist report. These import app, which
loads every CSV — slow by design. The stat math itself is covered by
test_versus.py, which must never import app; what is tested here is the
wiring: which charts reach the report, and what the report says about them.
"""
import pytest


@pytest.fixture(scope='session')
def application():
    import app
    return app


# The Supremes' last Hot 100 week is in 1977, so every row of theirs sat below
# the report's old 1990 cutoff. Rhett Akins reached country radio without a
# comparable Hot 100 footprint. Between them they cover both halves of what the
# old report could not see.
PRE_1990_ARTIST = 'The Supremes'
COUNTRY_ONLY_ARTIST = 'Rhett Akins'


def test_a_pre_1990_artists_report_is_not_empty(application):
    """The regression this change exists to fix: the old report filtered the
    Hot 100 to 1990+, so an artist who stopped charting in 1977 got the 'no
    results' flash rather than a career that ran 404 chart weeks."""
    report = application.artist_chart_summaries(PRE_1990_ARTIST)
    assert report is not None
    assert 'top100' in {c['key'] for c in report['charts']}
    hot100 = next(c for c in report['charts'] if c['key'] == 'top100')
    assert hot100['entries'] > 10
    assert hot100['last_entry'] < '1990-01-01'


def test_analyze_renders_a_pre_1990_artist_rather_than_redirecting(application):
    r = application.app.test_client().post(
        '/analyze', data={'artist_name': PRE_1990_ARTIST})
    assert r.status_code == 200
    assert PRE_1990_ARTIST in r.get_data(as_text=True)


def test_summaries_cover_charts_beyond_the_two_the_report_used_to_read(application):
    """14 of the 16 charts were invisible to the report. A country act's
    coverage has to include country radio."""
    report = application.artist_chart_summaries('Luke Combs')
    keys = {c['key'] for c in report['charts']}
    assert 'country_airplay' in keys
    assert keys - {'top100', 'albums200'}


def test_summaries_list_only_charts_the_artist_actually_charted_on(application):
    report = application.artist_chart_summaries(COUNTRY_ONLY_ARTIST)
    for row in report['charts']:
        assert row['total_weeks_charted'] > 0
        # Every listed chart must really hold rows for them.
        assert not application._artist_rows(row['key'], COUNTRY_ONLY_ARTIST).empty
    # Absence is stated, not left looking like missing data.
    loaded = sum(1 for _k, (df, _d) in application.CHART_DATA.items()
                 if df is not None and len(df))
    assert report['hidden'] == loaded - len(report['charts'])
    assert report['hidden'] > 0


def test_summaries_are_in_registry_order(application):
    report = application.artist_chart_summaries('Drake')
    order = [k for k in application.CHARTS if k in {c['key'] for c in report['charts']}]
    assert [c['key'] for c in report['charts']] == order


def test_summaries_return_none_when_the_artist_charted_nowhere(application):
    """/analyze's 'no results' flash path depends on None, not an empty list."""
    assert application.artist_chart_summaries('Zzzznotanartist') is None


def test_artist_chart_stats_are_null_never_zero(application):
    """On an artist chart the song-level counts are booleans in disguise, so
    compute_artist_stats nulls them. A 0 there would read as 'none', which is
    a different and false claim."""
    report = application.artist_chart_summaries('Drake')
    row = next(c for c in report['charts'] if c['key'] == 'artist100')
    for stat in ('entries', 'number_ones', 'top_10s', 'top_40s', 'biggest_hit'):
        assert row[stat] is None, stat
    # and the stats that do mean something on that chart are still numbers:
    assert row['best_peak'] == 1
    assert row['total_weeks_charted'] > 0


def test_the_default_chart_is_the_one_with_the_most_entries(application):
    report = application.artist_chart_summaries('Luke Combs')
    default = next(c for c in report['charts'] if c['key'] == report['default_chart'])
    assert all((c['entries'] or 0) <= default['entries'] for c in report['charts'])


def test_default_chart_can_be_an_artist_chart_when_it_is_all_there_is(application):
    """entries is None on an artist chart, so ranking by entries alone would
    pick nothing at all for an artist who only appears there."""
    report = application.artist_chart_summaries('Drake')
    assert report['default_chart']


def test_detail_song_count_matches_the_coverage_entry_count(application):
    """The table and the summary are built from the same cleaned rows, and
    disagreeing about how many songs an artist has is the failure that
    guarantees one of them is wrong."""
    for name in (PRE_1990_ARTIST, 'Luke Combs'):
        report = application.artist_chart_summaries(name)
        for row in report['charts']:
            if row['kind'] == 'artist':
                continue
            detail = application.artist_chart_detail(name, row['key'])
            assert len(detail['songs']) == row['entries'], (name, row['key'])


def test_detail_covers_the_full_history_not_just_1990_onward(application):
    detail = application.artist_chart_detail(PRE_1990_ARTIST, 'top100')
    assert detail['timeline']
    assert min(p['date'] for p in detail['timeline']) < '1990-01-01'


def test_an_artist_charts_detail_has_a_timeline_and_no_song_table(application):
    detail = application.artist_chart_detail('Drake', 'artist100')
    assert detail['chart']['kind'] == 'artist'
    assert detail['songs'] == []
    assert detail['series'] == {}
    assert len(detail['timeline']) > 0


def test_detail_series_is_keyed_by_song_id(application):
    detail = application.artist_chart_detail('Luke Combs', 'country_airplay')
    assert {s['id'] for s in detail['songs']} == set(detail['series'])
    for song in detail['songs']:
        weeks = detail['series'][song['id']]
        assert song['peak'] == min(w['rank'] for w in weeks)
        assert song['weeks'] == len({w['date'] for w in weeks})


def test_album_detail_reads_from_the_album_frame(application):
    detail = application.artist_chart_detail('Luke Combs', 'albums200')
    assert detail['chart']['kind'] == 'album'
    assert detail['songs']


def test_api_artist_chart_rejects_an_unknown_chart(application):
    r = application.app.test_client().get('/api/artist-chart?artist=Drake&chart=nope')
    assert r.status_code == 400


def test_api_artist_chart_requires_an_artist(application):
    r = application.app.test_client().get('/api/artist-chart?chart=top100')
    assert r.status_code == 400


def test_api_artist_chart_404s_for_an_artist_absent_from_that_chart(application):
    r = application.app.test_client().get(
        '/api/artist-chart?artist=Zzzznotanartist&chart=top100')
    assert r.status_code == 404


def test_api_artist_chart_serves_the_selected_chart(application):
    r = application.app.test_client().get(
        '/api/artist-chart?artist=Luke+Combs&chart=country_airplay')
    assert r.status_code == 200
    body = r.get_json()
    assert body['chart']['key'] == 'country_airplay'
    assert body['songs']


def test_the_widened_pool_reaches_artists_the_report_can_now_render(application):
    """12,209 artists gained a report under this change; without the wider
    pool none of them would be reachable from the search box."""
    pool = set(application.ALL_ARTISTS)
    assert PRE_1990_ARTIST in pool
    assert COUNTRY_ONLY_ARTIST in pool
    assert len(pool) > 10000
    # Both have a report to reach:
    assert application.artist_chart_summaries(PRE_1990_ARTIST) is not None
    assert application.artist_chart_summaries(COUNTRY_ONLY_ARTIST) is not None


def test_the_report_page_carries_the_coverage_table_and_one_detail_payload(application):
    """The default chart's detail ships with the page so the report is not
    blank until a fetch lands; the other 15 are not in the HTML."""
    body = application.app.test_client().post(
        '/analyze', data={'artist_name': 'Luke Combs'}).get_data(as_text=True)
    assert 'Chart coverage' in body
    assert 'Country Airplay' in body
    assert '/api/artist-chart' in body
    assert body.count('"timeline"') == 1
