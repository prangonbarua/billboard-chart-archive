"""refresh_to_week.py must be safe to rerun and to kill.

Hermetic: every test builds a throwaway repo layout (app.py registry, data CSVs,
scripts/*.json) and drives refresh() with a fake scraper, so nothing here
touches the network or the real data.
"""
import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
import refresh_to_week as r  # noqa: E402

FIELDS = ['Date', 'Rank', 'Song', 'Artist', 'Last Week', 'Peak Position', 'Weeks on Chart']

APP = """
CHARTS = {}
BATCH_CHARTS = {
    'alpha': ('Alpha Songs', 'Test', 5, 'song', 'alpha.csv'),
    'beta':  ('Beta Songs',  'Test', 5, 'song', 'beta.csv'),
    'gone':  ('Gone Songs',  'Test', 5, 'song', 'gone.csv'),
}
HOTW_COUNTRIES = []
"""

WEEKS = ['2026-09-12', '2026-09-19', '2026-09-26', '2026-10-03']


def ranking(slug, week):
    """A distinct top 5 per (slug, week), so clamp and proof checks are real."""
    return [{'Rank': i, 'Song': f'{slug} {week} song {i}', 'Artist': 'x',
             'Last Week': '', 'Peak Position': i, 'Weeks on Chart': 1, 'Date': week}
            for i in range(1, 6)]


class FakeBillboard:
    """Serves `ranking()` for each slug up to its last published week."""

    def __init__(self, published):
        self.published = published   # slug -> last published week
        self.calls = []

    def __call__(self, slug, week):
        self.calls.append((slug, week))
        last = self.published.get(slug)
        if last is None or week > last:
            return None
        return ranking(slug, week)


def write_csv(path, slug, weeks):
    with open(path, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for wk in weeks:
            for row in ranking(slug, wk):
                w.writerow({f: row.get(f, '') for f in FIELDS})


@pytest.fixture
def repo(tmp_path):
    (tmp_path / 'app.py').write_text(APP)
    (tmp_path / 'data').mkdir()
    (tmp_path / 'scripts').mkdir()
    write_csv(tmp_path / 'data' / 'alpha.csv', 'alpha-songs', WEEKS[:2])
    write_csv(tmp_path / 'data' / 'beta.csv', 'beta-songs', WEEKS[:1])
    write_csv(tmp_path / 'data' / 'gone.csv', 'gone-songs', WEEKS[:1])
    (tmp_path / 'scripts' / 'known_slugs.json').write_text(
        '{\n  "alpha": "alpha-songs"\n}\n')
    (tmp_path / 'scripts' / 'frozen_charts.json').write_text(json.dumps(
        {'_about': 'x', 'gone': {'kind': 'discontinued', 'until': WEEKS[0]}}))
    return tmp_path


def fake():
    return FakeBillboard({'alpha-songs': WEEKS[3], 'beta-songs': WEEKS[3],
                          'gone-songs': WEEKS[3]})


def run(repo, scrape, **kw):
    return r.refresh(WEEKS[3], root=repo, scrape=scrape, sleep=lambda s: None, **kw)


def weeks_of(path):
    return r.weeks_in(r.read_csv(path)[0])


def test_brings_charts_to_target(repo):
    res = run(repo, fake())
    assert res['alpha'][0] == 'updated' and res['beta'][0] == 'updated'
    assert weeks_of(repo / 'data' / 'alpha.csv') == WEEKS
    assert weeks_of(repo / 'data' / 'beta.csv') == WEEKS


def test_second_run_changes_nothing_and_fetches_nothing(repo):
    run(repo, fake())
    before = {p.name: p.read_bytes() for p in (repo / 'data').iterdir()}
    again = fake()
    res = run(repo, again, fresh=True)
    assert again.calls == []
    assert {k: s for k, (s, _) in res.items()} == {
        'alpha': 'current', 'beta': 'current', 'gone': 'frozen'}
    assert {p.name: p.read_bytes() for p in (repo / 'data').iterdir()} == before


def test_killed_run_resumes_without_refetching_finished_charts(repo, monkeypatch):
    real_prove = r.prove

    def prove(slug, week, rows, scrape=None):
        # A Ctrl-C landing while beta is being worked on, after alpha finished.
        if slug == 'beta-songs':
            raise KeyboardInterrupt
        return real_prove(slug, week, rows, scrape)

    monkeypatch.setattr(r, 'prove', prove)
    with pytest.raises(KeyboardInterrupt):
        run(repo, fake())
    monkeypatch.setattr(r, 'prove', real_prove)

    ckpt = json.loads((repo / 'logs' / 'refresh_checkpoints' / f'{WEEKS[3]}.json').read_text())
    assert ckpt['alpha']['status'] == 'updated'
    assert 'beta' not in ckpt

    second = fake()
    res = run(repo, second)
    assert res['alpha'][1].get('resumed') is True
    assert not any(slug == 'alpha-songs' for slug, _ in second.calls)
    assert res['beta'][0] == 'updated'
    assert weeks_of(repo / 'data' / 'beta.csv') == WEEKS


def test_frozen_chart_is_never_fetched_or_extended(repo):
    before = (repo / 'data' / 'gone.csv').read_bytes()
    scrape = fake()
    res = run(repo, scrape)
    assert res['gone'][0] == 'frozen'
    assert not any(slug == 'gone-songs' for slug, _ in scrape.calls)
    assert (repo / 'data' / 'gone.csv').read_bytes() == before


def test_one_chart_run_keeps_every_other_charts_plan_entry(repo):
    plan = repo / 'scripts' / 'chart_plan.json'
    plan.write_text(json.dumps({'other-slug': {'key': 'other', 'csv': 'o.csv',
                                               'anchor': '2026-01-03'}}))
    run(repo, fake(), only={'beta'})
    got = json.loads(plan.read_text())
    assert got['other-slug']['key'] == 'other'
    assert got['beta-songs']['key'] == 'beta'


def test_plan_holds_one_entry_per_chart_when_its_slug_changes(repo):
    plan = repo / 'scripts' / 'chart_plan.json'
    plan.write_text(json.dumps({'old-beta': {'key': 'beta', 'csv': 'beta.csv',
                                             'anchor': WEEKS[0]}}))
    run(repo, fake(), only={'beta'})
    got = json.loads(plan.read_text())
    assert [s for s, v in got.items() if v['key'] == 'beta'] == ['beta-songs']


def test_clamped_week_is_not_stored(repo):
    class Clamping(FakeBillboard):
        def __call__(self, slug, week):
            self.calls.append((slug, week))
            # Serves the boundary week's ranking under any later date.
            return ranking(slug, min(week, WEEKS[1]))

    res = run(repo, Clamping({}), only={'alpha'})
    assert res['alpha'][0] == 'none'
    assert weeks_of(repo / 'data' / 'alpha.csv') == WEEKS[:2]


def test_unproven_slug_is_skipped_not_guessed(repo):
    res = run(repo, FakeBillboard({}), only={'beta'})
    assert res['beta'][0] == 'skipped'
    assert weeks_of(repo / 'data' / 'beta.csv') == WEEKS[:1]


def test_default_target_is_the_coming_saturday():
    import datetime as dt
    assert r.default_target(dt.date(2026, 9, 29)) == '2026-10-03'   # Tuesday
    assert r.default_target(dt.date(2026, 10, 3)) == '2026-10-03'   # Saturday
    assert r.default_target(dt.date(2026, 10, 4)) == '2026-10-10'   # Sunday
