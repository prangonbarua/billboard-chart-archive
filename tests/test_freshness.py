"""Every chart's latest stored week must be Billboard's latest published week.

The live check fetches each chart's undated page and reads the served-week
HEADING, which is the only thing Billboard states about which week it is
serving. It makes one request per chart, so it runs only when asked:

    BILLBOARD_LIVE=1 python3 -m pytest -q tests/test_freshness.py

Charts in scripts/frozen_charts.json are held to their own rule instead: a
discontinued chart must end on exactly its 'until' week (neither truncated nor
extended), and a chart from another source is not checked against Billboard.
Those checks are offline and always run.

The slug for each chart comes from scripts/known_slugs.json first, then the
slug the last refresh proved in scripts/chart_plan.json. Both are only read.
"""
import csv
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import refresh_to_week as r  # noqa: E402

LIVE = os.environ.get('BILLBOARD_LIVE') == '1'

REGISTRY = r.registry()
FROZEN = r.frozen_charts()
KNOWN = r.known_slugs()
PLANNED = r.planned_slugs()


def stored_last(key):
    label, declared = REGISTRY[key]
    path = r.csv_path(key, declared)
    assert path is not None, f'{key}: no CSV on disk'
    return r.weeks_in(r.read_csv(path)[0])[-1]


def test_frozen_list_names_only_registered_charts():
    assert set(FROZEN) <= set(REGISTRY)


@pytest.mark.parametrize('key', sorted(k for k, v in FROZEN.items()
                                       if v.get('kind') == 'discontinued'))
def test_discontinued_chart_ends_on_its_final_week(key):
    assert stored_last(key) == FROZEN[key]['until']


@pytest.mark.skipif(not LIVE, reason='live Billboard check; set BILLBOARD_LIVE=1')
@pytest.mark.parametrize('key', sorted(set(REGISTRY) - set(FROZEN)))
def test_latest_stored_week_is_latest_published(key):
    from fast_billboard_scraper import latest_published_week
    slug = KNOWN.get(key) or PLANNED.get(key)
    assert slug, f'{key}: no proven slug in known_slugs.json or chart_plan.json'
    published = None
    for attempt in range(3):
        published = latest_published_week(slug)
        if published:
            break
        time.sleep(2 * (attempt + 1))
    time.sleep(0.5)
    assert published, f'{key}: {slug} served no week heading'
    assert stored_last(key) == published, f'{key}: stale ({slug})'


# The silent-overwrite guard. A real refresh run, driven offline against a
# copy of the repo layout, must leave the override file byte-identical.

def test_override_file_is_byte_identical_after_a_refresh_run(tmp_path):
    (tmp_path / 'scripts').mkdir()
    (tmp_path / 'data').mkdir()
    (tmp_path / 'app.py').write_text(
        "CHARTS = {}\n"
        "BATCH_CHARTS = {'alpha': ('Alpha Songs', 'T', 5, 'song', 'alpha.csv')}\n"
        "HOTW_COUNTRIES = []\n")
    override = tmp_path / 'scripts' / 'known_slugs.json'
    override.write_bytes((ROOT / 'scripts' / 'known_slugs.json').read_bytes()
                         .replace(b'{', b'{\n  "alpha": "alpha-songs",', 1))
    with open(tmp_path / 'data' / 'alpha.csv', 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['Date', 'Rank', 'Song', 'Artist'])
        for i in range(1, 6):
            w.writerow(['2026-09-19', i, f'old {i}', 'x'])

    def scrape(slug, week):
        if slug != 'alpha-songs' or week > '2026-09-26':
            return None
        tag = 'old' if week == '2026-09-19' else 'new'
        return [{'Rank': i, 'Song': f'{tag} {i}', 'Artist': 'x'} for i in range(1, 6)]

    before = hashlib.sha256(override.read_bytes()).hexdigest()
    res = r.refresh('2026-09-26', root=tmp_path, scrape=scrape, sleep=lambda s: None)
    assert res['alpha'][0] == 'updated'
    assert hashlib.sha256(override.read_bytes()).hexdigest() == before
    # The proven slug went to the plan, which is where tooling may write.
    assert json.loads((tmp_path / 'scripts' / 'chart_plan.json').read_text()) \
        ['alpha-songs']['key'] == 'alpha'

