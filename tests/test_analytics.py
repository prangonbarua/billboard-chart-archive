"""Tests for visitor counting and the private /admin page."""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import analytics  # noqa: E402


@pytest.fixture
def db(monkeypatch):
    """A throwaway database, so no test ever touches the Railway volume path."""
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv('ANALYTICS_DB', os.path.join(tmp, 'a.db'))
        monkeypatch.setenv('ANALYTICS_SALT', 'test-salt')
        assert analytics.init_db()
        yield


def test_same_visitor_twice_is_one_person_two_views(db):
    analytics.record_visit('/top100', '1.2.3.4', 'Firefox')
    analytics.record_visit('/top100', '1.2.3.4', 'Firefox')
    s = analytics.summary()
    assert s['lifetime_uniques'] == 1
    assert s['total_views'] == 2


def test_different_user_agent_is_a_different_person(db):
    analytics.record_visit('/top100', '1.2.3.4', 'Firefox')
    analytics.record_visit('/top100', '1.2.3.4', 'Chrome')
    assert analytics.summary()['lifetime_uniques'] == 2


def test_raw_ip_is_never_stored(db):
    analytics.record_visit('/top100', '203.0.113.9', 'Firefox')
    with open(os.environ['ANALYTICS_DB'], 'rb') as fh:
        assert b'203.0.113.9' not in fh.read()


def test_salt_change_is_what_resets_uniques(db, monkeypatch):
    analytics.record_visit('/top100', '1.2.3.4', 'Firefox')
    monkeypatch.setenv('ANALYTICS_SALT', 'a-different-salt')
    analytics.record_visit('/top100', '1.2.3.4', 'Firefox')
    # Documents the failure mode the fixed env var exists to prevent: the same
    # person counted twice because the salt moved underneath them.
    assert analytics.summary()['lifetime_uniques'] == 2


def test_top_paths_ranks_by_views(db):
    for _ in range(3):
        analytics.record_visit('/rap_airplay', '1.1.1.1', 'UA')
    analytics.record_visit('/top100', '2.2.2.2', 'UA')
    top = analytics.summary()['top_paths']
    assert top[0]['path'] == '/rap_airplay' and top[0]['views'] == 3


def test_recent_days_are_separated_by_day(db):
    analytics.record_visit('/top100', '1.1.1.1', 'UA', day='2026-08-12')
    analytics.record_visit('/top100', '2.2.2.2', 'UA', day='2026-08-13')
    days = {r['day'] for r in analytics.summary()['recent']}
    assert {'2026-08-12', '2026-08-13'} <= days


def test_unopenable_database_disables_counting_instead_of_raising(monkeypatch):
    # A directory where the file should be: open fails the way a missing
    # Railway volume does.
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv('ANALYTICS_DB', tmp)
        assert analytics.init_db() is False
        assert analytics.record_visit('/top100', '1.1.1.1', 'UA') is False
        assert analytics.summary()['available'] is False
    analytics.init_db()  # leave the module enabled for other tests


def test_check_password_rejects_when_unset(monkeypatch):
    monkeypatch.delenv('ADMIN_PASSWORD', raising=False)
    assert analytics.check_password('anything') is False


def test_check_password_matches_exactly(monkeypatch):
    monkeypatch.setenv('ADMIN_PASSWORD', 'hunter2')
    assert analytics.check_password('hunter2') is True
    assert analytics.check_password('hunter') is False
    assert analytics.check_password(None) is False


# ── /admin route ────────────────────────────────────────────────────────────

@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setenv('ADMIN_PASSWORD', 'hunter2')
    import app as app_module
    app_module.app.config['TESTING'] = True
    app_module.app.secret_key = 'test-secret'
    with app_module.app.test_client() as c:
        yield c


def test_admin_signed_out_shows_form_and_no_numbers(client):
    r = client.get('/admin')
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert 'type="password"' in body
    assert 'People, all time' not in body


def test_wrong_password_does_not_sign_in(client):
    r = client.post('/admin', data={'password': 'wrong'}, follow_redirects=True)
    body = r.get_data(as_text=True)
    assert 'Incorrect password.' in body
    assert 'People, all time' not in body


def test_correct_password_signs_in(client):
    r = client.post('/admin', data={'password': 'hunter2'}, follow_redirects=True)
    assert 'People, all time' in r.get_data(as_text=True)


def test_logout_signs_out(client):
    client.post('/admin', data={'password': 'hunter2'}, follow_redirects=True)
    client.get('/admin/logout')
    assert 'People, all time' not in client.get('/admin').get_data(as_text=True)


def test_admin_is_not_counted_in_its_own_stats(client):
    client.get('/admin')
    client.post('/admin', data={'password': 'hunter2'}, follow_redirects=True)
    assert not any(p['path'].startswith('/admin')
                   for p in analytics.summary()['top_paths'])


def test_a_chart_page_is_counted(client):
    before = analytics.summary()['total_views']
    client.get('/top100')
    assert analytics.summary()['total_views'] == before + 1


def test_broken_analytics_does_not_break_a_chart_page(client, monkeypatch):
    monkeypatch.setattr(analytics, 'record_visit',
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')))
    # The hook must not let an analytics failure reach a visitor. If this fails,
    # counting can take the whole site down, which is the one thing it may not do.
    with pytest.raises(RuntimeError):
        analytics.record_visit('/x', 'y', 'z')
    assert client.get('/top100').status_code == 200
