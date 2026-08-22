"""Wiring tests for the cross-chart lookup endpoints.

These import app, which loads every CSV and builds the index — slow by design,
same as test_artist_report.py. Test subjects are picked out of the live index
rather than hardcoded, so a data refresh cannot turn a passing test into a
false failure.
"""
import pytest


@pytest.fixture(scope='session')
def application():
    import app
    return app


@pytest.fixture(scope='session')
def client(application):
    application.app.config['TESTING'] = True
    return application.app.test_client()


def pick_title(application, kind, min_charts=2):
    """A (title, artist) of the given kind that really is on several charts."""
    idx = application.CHART_INDEX
    rows = idx[idx['kind'] == kind]
    counts = rows.groupby(level=['title', 'artist'], observed=True).size()
    counts = counts[counts >= min_charts]
    if counts.empty:
        pytest.skip(f'no {kind} title on {min_charts}+ charts')
    title, artist = counts.sort_values(ascending=False).index[0]
    display = str(rows.loc[[(title, artist)]]['display'].iloc[0])
    return display, artist


# ── /api/songs ──────────────────────────────────────────────────────────────

def test_songs_autocomplete_returns_matching_titles(client, application):
    display, _artist = pick_title(application, 'song')
    res = client.get('/api/songs', query_string={'q': display[:3], 'kind': 'song'})
    assert res.status_code == 200
    songs = res.get_json()['songs']
    assert songs
    assert any(s['title'].casefold().startswith(display[:3].casefold()) for s in songs)


def test_songs_autocomplete_suggestions_can_be_looked_up(client):
    """The pair a suggestion hands back must resolve. A box that offers
    'the kid laroi' as the artist, or offers a title with no artist at all,
    produces a search that always comes back empty."""
    res = client.get('/api/songs', query_string={'q': 'sta', 'kind': 'song'})
    suggestion = res.get_json()['songs'][0]
    assert set(suggestion) == {'title', 'credit', 'artist', 'charts'}

    found = client.get('/api/song-charts', query_string={
        'song': suggestion['title'], 'artist': suggestion['artist'], 'kind': 'song'})
    assert found.status_code == 200
    assert found.get_json()['charts'], 'a suggested pair resolved to nothing'


def test_songs_autocomplete_rejects_an_unknown_kind(client):
    res = client.get('/api/songs', query_string={'q': 'a', 'kind': 'artist'})
    assert res.status_code == 400


# ── /api/song-charts ────────────────────────────────────────────────────────

def test_song_charts_requires_both_parameters(client):
    assert client.get('/api/song-charts', query_string={'song': 'Flowers'}).status_code == 400
    assert client.get('/api/song-charts', query_string={'artist': 'Miley Cyrus'}).status_code == 400


def test_song_charts_returns_every_chart_a_song_reached(client, application):
    display, artist = pick_title(application, 'song')
    res = client.get('/api/song-charts',
                     query_string={'song': display, 'artist': artist, 'kind': 'song'})
    assert res.status_code == 200
    body = res.get_json()
    assert body['found'] is True
    assert len(body['charts']) >= 2
    for row in body['charts']:
        assert set(row) == {'chart', 'label', 'debut', 'peak', 'weeks', 'later'}


def test_song_charts_results_are_sorted_by_peak(client, application):
    display, artist = pick_title(application, 'song')
    charts = client.get('/api/song-charts', query_string={
        'song': display, 'artist': artist, 'kind': 'song'}).get_json()['charts']
    assert [c['peak'] for c in charts] == sorted(c['peak'] for c in charts)


def test_song_charts_never_returns_album_charts(client, application):
    """Kind matching, end to end: the registry says which charts are albums."""
    display, artist = pick_title(application, 'song')
    charts = client.get('/api/song-charts', query_string={
        'song': display, 'artist': artist, 'kind': 'song'}).get_json()['charts']
    for row in charts:
        assert application.CHARTS[row['chart']]['kind'] == 'song'


def test_album_lookup_returns_only_album_charts(client, application):
    display, artist = pick_title(application, 'album')
    charts = client.get('/api/song-charts', query_string={
        'song': display, 'artist': artist, 'kind': 'album'}).get_json()['charts']
    assert charts
    for row in charts:
        assert application.CHARTS[row['chart']]['kind'] == 'album'


def test_a_title_that_charted_nowhere_is_found_but_empty(client):
    """found=True with no charts is an answer, not a failure."""
    res = client.get('/api/song-charts', query_string={
        'song': 'Definitely Not A Real Song Title 12345', 'artist': 'Nobody At All'})
    assert res.status_code == 200
    body = res.get_json()
    assert body['found'] is True
    assert body['charts'] == []


# ── /api/song-history's changed contract ────────────────────────────────────

def test_album_history_carries_the_crossover_field(client, application):
    """The Billboard 200 is the one album chart that does NOT render through
    chart.html — it has its own page and its own /api/album-history. Without
    this the flagship album chart is the only one with no 'also charted on'."""
    display, artist = pick_title(application, 'album')
    res = client.get('/api/album-history',
                     query_string={'album': display, 'artist': artist})
    if res.status_code == 404:
        pytest.skip('album not on the Billboard 200')
    assert res.status_code == 200
    body = res.get_json()
    assert body['crossover_ok'] is True
    assert isinstance(body['crossover'], list)
    for row in body['crossover']:
        assert application.CHARTS[row['chart']]['kind'] == 'album'
        assert row['chart'] != 'albums200'


def test_song_history_returns_crossover_as_a_list(client, application):
    """Was a single object or null. templates/chart.html reads the new shape."""
    display, artist = pick_title(application, 'song')
    idx = application.CHART_INDEX
    origin = str(idx.loc[[(display.strip().casefold(),
                           artist)]]['chart'].iloc[0])
    res = client.get('/api/song-history', query_string={
        'song': display, 'artist': artist, 'chart': origin})
    assert res.status_code == 200
    body = res.get_json()
    assert isinstance(body['crossover'], list)
    assert body['crossover_ok'] is True
    assert origin not in {c['chart'] for c in body['crossover']}
