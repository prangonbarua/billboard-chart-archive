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


# ── the modal's chart caption ───────────────────────────────────────────────

def test_song_history_echoes_the_resolved_chart_not_the_requested_one(client):
    """An unknown key falls back to the Hot 100 rather than 404ing. The modal
    captions itself from this field, so it has to name the chart that was
    actually read — echoing the request would put the asked-for chart's name
    over the Hot 100's numbers."""
    res = client.get('/api/song-history', query_string={
        'song': 'Hotline Bling', 'artist': 'Drake', 'chart': 'no_such_chart'})
    assert res.status_code == 200
    body = res.get_json()
    assert body['chart'] == 'top100'
    assert body['chart_label'] == 'The Hot 100™'


def test_album_history_labels_itself_as_the_billboard_200(client, application):
    """Both endpoints caption the modal the same way, so /albums200 needs the
    field even though it only ever reads one chart."""
    display, artist = pick_title(application, 'album')
    res = client.get('/api/album-history',
                     query_string={'album': display, 'artist': artist})
    if res.status_code == 404:
        pytest.skip('album not on the Billboard 200')
    body = res.get_json()
    assert body['chart'] == 'albums200'
    assert body['chart_label'] == application.CHARTS['albums200']['label']


def test_a_crossover_row_opens_the_run_it_advertises(client, application):
    """Clicking a row reopens the modal on that chart. The row's peak and week
    count are what the reader was promised, so the view they land on has to
    report the same two numbers — the row and the endpoint reach the data by
    different paths (index groupby vs. a fresh filter), and only this pins
    them together."""
    display, artist = pick_title(application, 'song', min_charts=3)
    idx = application.CHART_INDEX
    origin = str(idx.loc[[(display.strip().casefold(), artist)]]['chart'].iloc[0])
    rows = client.get('/api/song-history', query_string={
        'song': display, 'artist': artist, 'chart': origin}).get_json()['crossover']
    assert rows, 'picked a title with no crossover to click'

    for row in rows:
        res = client.get('/api/song-history', query_string={
            'song': display, 'artist': artist, 'chart': row['chart']})
        assert res.status_code == 200, f"{row['chart']} is unopenable"
        landed = res.get_json()
        assert landed['chart'] == row['chart']
        assert landed['peak'] == row['peak']
        assert landed['total_weeks'] == row['weeks']
        # The way back: the chart just left has to reappear in the new list,
        # or a reader who clicks through is stranded.
        assert origin in {c['chart'] for c in landed['crossover']}
