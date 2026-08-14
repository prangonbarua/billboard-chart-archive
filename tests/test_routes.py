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
    """Registered charts that actually have data loaded.

    A registered chart with no CSV is a supported state, not a failure: app.py
    loads it as None, available_charts() drops it from the nav, and its route
    flashes and redirects. That is what lets a chart be registered before its
    backfill finishes. These tests assert what a chart with data must do, so
    they iterate the same set the nav does — a chart joins every guarantee here
    the moment its CSV lands, and nothing is weakened for the ones that have it.
    """
    import app
    return {k: m for k, m in app.CHARTS.items()
            if (lambda df: df is not None and len(df))(app.CHART_DATA.get(k, (None, None))[0])}


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
    """Tag sets for every entry on a rendered chart page (hero included)."""
    return [set(m.split()) for m in ROW_TAGS_RE.findall(body)]


def test_every_chart_page_tags_its_rows(client, charts):
    """data-tags is written by the shared renderer, so all charts get it from one
    edit. It is how the tests below observe the new/re-entry/peak derivation,
    and a chart rendering rows without it would silently skip those checks."""
    for key in charts:
        body = client.get('/' + key).get_data(as_text=True)
        rows = ROW_TAGS_RE.findall(body)
        assert len(rows) > 1, f'{key}: rows carry no data-tags'


def test_the_row_filter_control_is_gone(client, charts):
    """The Filter dropdown was removed from the chart toolbar. Its markup and the
    grower threshold that fed its one computed option should not come back with
    a template copy-paste."""
    for key in charts:
        body = client.get('/' + key).get_data(as_text=True)
        assert 'rowFilterSelect' not in body, key
        assert 'filterCount' not in body, key
        assert 'Growers (+' not in body, key


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
    assert not any('peak' in t or 're-entry' in t for t in tags)


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


@pytest.fixture(scope='session')
def graduations():
    """(song, artist) pairs, in their stored casing, that charted on both
    Bubbling Under and the Hot 100 — built by an independent join so the tests
    below are not checking _crossover_run against itself."""
    import app
    import pandas as pd

    def keyed(df, key):
        d = df[['Song', 'Artist']].copy()
        d['k'] = list(zip(d['Song'].astype(str).str.strip().str.casefold(),
                          d['Artist'].map(app.primary_artist, na_action='ignore')))
        d['dt'] = app.CHART_DT[key].loc[d.index]
        return d

    b = keyed(app.BUBBLING_DATA, 'bubbling')
    h = keyed(app.BILLBOARD_DATA, 'top100')
    both = set(b['k']) & set(h['k'])
    # One stored-casing example per matched pair. A dict, not .loc: the keys are
    # tuples, which pandas reads as a multi-axis indexer rather than a label.
    stored = dict(zip(b['k'], zip(b['Song'].astype(str), b['Artist'].astype(str))))
    return both, [stored[k] for k in sorted(both)[:25]]


def test_crossover_finds_the_bulk_of_bubbling_under_graduations(graduations):
    """A join that fails silently returns zero and looks exactly like a chart
    where nothing ever graduated. Thousands of titles appear on both charts, so
    a low number here means the join broke, not that history changed."""
    both, _ = graduations
    assert len(both) > 4000, f'only {len(both)} titles matched across the two charts'


def test_crossover_resolves_every_sampled_graduation(graduations):
    import app
    _, sample = graduations
    assert sample
    missed = [(s, a) for s, a in sample
              if app._crossover_run('bubbling', str(s), str(a), None) is None]
    assert missed == [], f'{len(missed)} known graduations returned nothing: {missed[:5]}'


def test_crossover_join_survives_artist_casing_drift():
    """Scraped casing drifts week to week ('The Kid LAROI' vs 'The Kid Laroi').
    An exact-key join drops real graduations and reports nothing found."""
    import app
    b = app.BUBBLING_DATA
    for song, artist in zip(b['Song'].astype(str), b['Artist'].astype(str)):
        base = app._crossover_run('bubbling', song, artist, None)
        if base is None:
            continue
        for variant in (artist.upper(), artist.lower(), artist.swapcase()):
            got = app._crossover_run('bubbling', song, variant, None)
            assert got == base, (song, variant)
        return
    pytest.fail('no crossover found to test casing against')


def test_crossover_reports_both_directions(client):
    """Bubbling Under asks 'did it graduate'; the Hot 100 asks 'did it start
    there'. `later` is what separates the two sentences."""
    import app
    b = app.BUBBLING_DATA
    for song, artist in zip(b['Song'].astype(str), b['Artist'].astype(str)):
        up = app._crossover_run('bubbling', song, artist, None)
        if up is None:
            continue
        assert up['chart'] == 'top100'
        down = app._crossover_run('top100', song, artist, None)
        assert down is not None and down['chart'] == 'bubbling'
        # Each side reports the other chart's run, so the labels must differ.
        assert up['label'] != down['label']
        return
    pytest.fail('no crossover found')


def test_charts_without_a_pair_report_no_crossover(client, charts):
    """Only Bubbling Under and the Hot 100 are paired; everything else must
    return null rather than a wrong-chart match or an error."""
    import app
    for key in charts:
        if key in ('bubbling', 'top100') or app.CHARTS[key]['kind'] != 'song':
            continue
        df, _ = app.CHART_DATA[key]
        song, artist = str(df['Song'].iloc[0]), str(df['Artist'].iloc[0])
        assert app._crossover_run(key, song, artist, None) is None, key


def test_song_history_carries_the_crossover_field(client):
    import app
    b = app.BUBBLING_DATA
    for song, artist in zip(b['Song'].astype(str), b['Artist'].astype(str)):
        if app._crossover_run('bubbling', song, artist, None) is None:
            continue
        r = client.get('/api/song-history', query_string={
            'chart': 'bubbling', 'artist': artist, 'song': song})
        assert r.status_code == 200
        x = r.get_json()['crossover']
        assert x and x['chart'] == 'top100'
        assert set(x) == {'chart', 'label', 'debut', 'peak', 'weeks', 'later'}
        return
    pytest.fail('no crossover found')


def test_primary_artist_col_matches_the_scalar_definition():
    """_song_chart_page used to inline the credit regex instead of calling
    primary_artist, and the copy drifted — it never learned to split on commas,
    so the page keyed credits differently than the lookups beside it. Any future
    divergence between the column and scalar forms fails here."""
    import app
    import pandas as pd

    credits = pd.Series([
        'Rumi, JINU, EJAE & Andrew Choi', 'Rumi & JINU: EJAE & Andrew Choi',
        'Future , Metro Boomin & The Weeknd', 'Future, Metro Boomin & The Weeknd',
        '10,000 Maniacs', 'Hank Williams, Jr.', 'Tyler, The Creator',
        'Weezer Featuring Best Coast', '  Drake  ', None,
    ])
    got = app._primary_artist_col(credits)
    want = credits.map(app.primary_artist, na_action='ignore')
    assert list(got.fillna('<na>')) == list(want.fillna('<na>'))


def test_credit_change_mid_run_keeps_one_week_count(client):
    """Billboard re-credited 'Free' for the last 4 of its 20 Hot 100 weeks
    ('Rumi, JINU, EJAE & Andrew Choi' -> 'Rumi & JINU: EJAE & Andrew Choi').
    The page counted only the 4 weeks under the new credit and reported a peak
    of #35 against the true #23."""
    import app

    rows = app.BILLBOARD_DATA
    free = rows[rows['Song'].astype(str).str.strip().str.casefold() == 'free']
    free = free[free['Artist'].astype(str).str.startswith('Rumi')]
    assert free['Artist'].nunique() == 2, 'fixture assumes both stored credits'
    total_weeks = free['Date'].nunique()

    html = client.get('/top100', query_string={'date': '2025-11-22'}).get_data(as_text=True)
    row = re.search(r'data-song="Free".*?</tr>', html, re.S)
    assert row, 'Free not on the 2025-11-22 chart'
    text = re.sub(r'<[^>]+>', ' ', row.group(0))
    assert str(total_weeks) in text, f'expected the merged {total_weeks}-week run'
    assert '#23' in text, 'expected the peak from the full run, not the recredited tail'


def test_registered_chart_without_data_is_hidden_not_broken():
    """A chart may be registered before its backfill finishes.

    This is what the `charts` fixture above relies on, so it needs its own
    guard: without it, loosening that fixture would leave the dataless path
    untested and a chart could 500 for however long its data took to land.
    Three things must hold — it stays out of the nav, its route redirects
    instead of erroring, and it is still in the registry so the nav picks it
    up automatically once the CSV appears.
    """
    import app

    dataless = [k for k in app.CHARTS
                if (app.CHART_DATA.get(k, (None, None))[0] is None
                    or not len(app.CHART_DATA[k][0]))]
    if not dataless:
        pytest.skip('every registered chart currently has data')

    key = dataless[0]
    nav = app.available_charts()
    assert all(c['key'] != key for group in nav.values() for c in group), \
        f'{key} has no data but is offered in the nav'

    client = app.app.test_client()
    resp = client.get('/' + key)
    assert resp.status_code in (302, 303), \
        f'/{key} should redirect while dataless, got {resp.status_code}'
