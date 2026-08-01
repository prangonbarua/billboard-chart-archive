"""Every route loads. Guards the closure late-binding failure mode, where all
loop-registered routes serve whichever chart the loop ended on — a bug that
renders perfectly and is invisible without checking each page's own heading."""
import re

import pytest


@pytest.fixture(scope='session')
def client():
    import app
    return app.app.test_client()


@pytest.fixture(scope='session')
def charts():
    import app
    return app.CHARTS


def test_every_chart_route_returns_200(client, charts):
    bad = [k for k in charts if client.get('/' + k).status_code != 200]
    assert bad == []


def test_every_chart_renders_its_own_heading(client, charts):
    """The late-binding bug's signature: several routes sharing one heading."""
    seen = {}
    for key, meta in charts.items():
        body = client.get('/' + key).get_data(as_text=True)
        h1 = re.search(r'<h1[^>]*>(.*?)</h1>', body, re.S)
        assert h1, f'{key}: no <h1>'
        seen[key] = h1.group(1).strip()
    assert len(set(seen.values())) == len(seen), f'duplicate headings: {seen}'


def test_support_routes_load(client):
    for path in ('/', '/versus', '/search', '/about'):
        assert client.get(path).status_code in (200, 302), path


def test_song_history_never_500s_on_a_missing_song(client, charts, monkeypatch):
    """Adult Contemporary has 20 rows with a blank Artist (1984 'Ghostbusters',
    1989 'Hearts On Fire'). Artist is a category column, and pandas'
    Categorical.map calls the mapper with np.nan when the column has NAs — so a
    primary_artist that assumes a string took out song history for every song on
    that chart, not just those rows. The crash happens while normalizing the
    column, before any matching, so an unknown song is enough to catch it.

    primary_artist is stubbed strict on purpose: the live outage was a build
    whose primary_artist did name.strip() directly, and coercion inside
    versus.primary_credit is not what this endpoint should be relying on.
    """
    import app

    def strict_primary_artist(name):
        return name.strip().casefold()

    monkeypatch.setattr(app, 'primary_artist', strict_primary_artist)

    bad = {}
    for key in charts:
        resp = client.get('/api/song-history', query_string={
            'chart': key, 'artist': 'Nobody At All', 'song': 'No Such Song'})
        if resp.status_code >= 500:
            bad[key] = resp.status_code
    assert bad == {}
