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


def test_dropouts_page_serves_every_chart(client, charts):
    for key, meta in charts.items():
        resp = client.get('/dropouts?chart=' + key)
        assert resp.status_code == 200, key
        # Labels carry '&' ("Mainstream R&B/Hip-Hop"), which Jinja escapes.
        assert meta['label'].replace('&', '&amp;') in resp.get_data(as_text=True), key


def test_dropouts_bad_filters_fall_back_rather_than_error(client):
    for q in ['?chart=nope', '?week=not-a-date', '?chart=nope&week=9999-99-99',
              '?chart=top100&week=1800-01-01']:
        assert client.get('/dropouts' + q).status_code == 200, q


def test_dropouts_week_filter_selects_that_week(charts):
    import app
    report = app.chart_dropouts('adult_rnb', '1994-01-01')
    assert report['current_week'] == '1994-01-01'
    # Partner is the previous published week, not the date minus seven days.
    assert report['previous_week'] == '1993-12-25'


def test_dropouts_compare_consecutive_published_weeks(charts):
    """A fixed seven-day step would miss Billboard's skipped weeks and report a
    whole chart as dropouts; the comparison must walk the date index instead."""
    import app
    for key in charts:
        r = app.chart_dropouts(key)
        assert r is not None, key
        assert r['previous_week'] < r['current_week'], key
        # Never the degenerate "everything fell off" that a wrong week pairing gives.
        assert len(r['dropouts']) < r['previous_size'], key


def test_dropouts_key_on_case_insensitive_names(charts):
    """Scraped artist casing drifts week to week; an exact match would report
    each drift as a dropout."""
    import app
    for key, meta in charts.items():
        for entry in app.chart_dropouts(key)['dropouts']:
            assert entry['title'], key
            if meta['kind'] == 'artist':
                assert entry['artist'] is None, key


ROW_TAGS_RE = re.compile(r'data-tags="([^"]*)"')


def _row_tags(body):
    """Tag sets for every filterable entry on a rendered chart page (hero included)."""
    return [set(m.split()) for m in ROW_TAGS_RE.findall(body)]


def test_every_chart_page_offers_the_row_filters(client, charts):
    """The filter bar is built in the shared renderer so all charts get it from
    one edit. A chart rendering rows without data-tags would show the buttons
    and silently filter everything away."""
    for key in charts:
        body = client.get('/' + key).get_data(as_text=True)
        assert 'id="chartFilters"' in body, key
        for f in ('new', 're-entry', 'grower', 'peak'):
            assert f'data-filter="{f}"' in body, f'{key}: no {f} filter'
        rows = ROW_TAGS_RE.findall(body)
        assert len(rows) > 1, f'{key}: rows carry no data-tags'


def test_grower_threshold_scales_with_chart_depth(client):
    """A flat "+5 positions" would be a third of Bubbling Under and noise on the
    Global 200. The threshold is a share of the depth actually served."""
    expected = {'top100': 5, 'global200': 10, 'albums200': 10, 'bubbling': 2, 'adult_rnb': 2}
    for key, positions in expected.items():
        body = client.get('/' + key).get_data(as_text=True)
        assert f'Growers (+{positions} or more)' in body, key


def test_a_debut_is_never_tagged_a_new_peak(client, charts):
    """rank == peak holds trivially on a first week, so counting debuts would
    light up most of the lower chart and mean nothing."""
    for key in charts:
        for tags in _row_tags(client.get('/' + key).get_data(as_text=True)):
            assert not ('new' in tags and 'peak' in tags), key


def test_first_published_week_has_no_peaks_or_re_entries(client):
    """Nothing can have beaten a previous best, or returned, on week one."""
    body = client.get('/bubbling?date=1992-12-05').get_data(as_text=True)
    tags = _row_tags(body)
    assert tags, 'no rows rendered'
    assert all('new' in t for t in tags)
    assert not any('peak' in t or 're-entry' in t or 'grower' in t for t in tags)


def test_new_peak_tag_matches_the_chart_history(client):
    """The tag has to come from real chart history. The stored Peak Position
    column is corrupt in pre-2025 rows (debuts were written as Peak == 1), so a
    renderer reading it would tag the wrong songs."""
    import app
    import pandas as pd

    body = client.get('/bubbling').get_data(as_text=True)
    rows = re.findall(
        r'data-tags="([^"]*)" data-artist="([^"]*)" data-song="([^"]*)"', body)
    assert rows

    df = app.BUBBLING_DATA.copy()
    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    df['Rank'] = pd.to_numeric(df['Rank'], errors='coerce')
    df = df.dropna(subset=['Date', 'Rank'])
    latest = pd.Timestamp(app.BUBBLING_AVAILABLE_DATES[0])
    key = lambda s, a: (s.strip().casefold(), a.strip().casefold())
    prior_best = df[df['Date'] < latest].assign(
        k=[key(s, a) for s, a in zip(df[df['Date'] < latest]['Song'].astype(str),
                                     df[df['Date'] < latest]['Artist'].astype(str))]
    ).groupby('k')['Rank'].min().to_dict()
    this_week = df[df['Date'] == latest]
    rank_now = {key(str(s), str(a)): int(r) for s, a, r
                in zip(this_week['Song'], this_week['Artist'], this_week['Rank'])}

    import html as _html
    for tags, artist, song in rows:
        k = key(_html.unescape(song), _html.unescape(artist))
        if k not in rank_now:
            continue
        beat_own_best = k in prior_best and rank_now[k] < prior_best[k]
        assert ('peak' in tags.split()) == beat_own_best, (song, artist)


def test_billboard_200_reads_history_not_the_stored_columns(client):
    """/albums200 used to run its own copy of the renderer that stopped short of
    the 2026-07-29 debut/peak fix, so it showed the corrupt stored Last Week and
    Peak Position values. Reverting it to that copy must fail here."""
    import app
    import pandas as pd

    body = client.get('/albums200?date=2010-06-05').get_data(as_text=True)
    rows = re.findall(
        r'data-tags="[^"]*" data-artist="([^"]*)" data-song="([^"]*)">(.*?)</tr>',
        body, re.S)
    assert len(rows) > 100

    df = app.BILLBOARD_200_DATA.copy()
    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    df['Rank'] = pd.to_numeric(df['Rank'], errors='coerce')
    df = df.dropna(subset=['Date', 'Rank'])
    sel = pd.Timestamp('2010-06-05')
    upto = df[df['Date'] <= sel]
    best = upto.assign(k=[(str(s).strip().casefold(), str(a).strip().casefold())
                          for s, a in zip(upto['Song'], upto['Artist'])]
                       ).groupby('k')['Rank'].min().to_dict()

    import html as _html
    checked = 0
    for artist, song, cells in rows:
        k = (_html.unescape(song).strip().casefold(), _html.unescape(artist).strip().casefold())
        if k not in best:
            continue
        shown_peak = int(re.findall(r'class="stat-val">#?([^<]*)<', cells)[1].lstrip('#'))
        assert shown_peak == int(best[k]), (song, artist, shown_peak, best[k])
        checked += 1
    assert checked > 100
