"""The derived recurrents view.

This is the only page on the site whose table is not scraped Billboard data,
and the thing most worth guarding is not the arithmetic — it is that the page
never stops saying so. Billboard's Hot 100 Recurrents has no weekly archive
(re-probed 2026-08-22, docs/HANDOFF-new-charts.md), so anything here that
reads as a Billboard ranking is an invention with a real chart's name on it.

The empty week is the normal case, not a failure, so it is tested as a
first-class outcome rather than skipped over.
"""
import re
from pathlib import Path

import pytest

TEMPLATE = (Path(__file__).resolve().parent.parent / 'templates' / 'recurrents.html').read_text()


@pytest.fixture(scope='session')
def client():
    import app
    return app.app.test_client()


def test_the_page_loads(client):
    assert client.get('/recurrents').status_code == 200


def test_the_page_says_it_is_not_a_billboard_chart(client):
    """The whole condition the feature was built under."""
    body = client.get('/recurrents').get_data(as_text=True)
    assert 'Derived, not a Billboard chart' in body
    assert 'never published with a weekly archive' in body


def test_the_rank_column_is_not_labelled_as_a_chart_position(client):
    """A bare '#' would read as a recurrent chart position — the one number
    this page cannot know, because ranking recurrents needed post-Hot-100
    airplay and streaming that this archive does not hold."""
    body = client.get('/recurrents').get_data(as_text=True)
    assert 'Last&nbsp;pos.' in body
    assert not re.search(r'<th class="col-rank">\s*#\s*</th>', body)


def test_the_notice_names_the_ordering_it_actually_used():
    """Saying 'derived' is not enough on its own; the page has to say what the
    order IS, or a reader supplies Billboard's."""
    assert 'last Hot&nbsp;100 position' in TEMPLATE
    assert 'not the order Billboard used' in TEMPLATE


def test_every_row_satisfies_the_rule_it_claims(client):
    """No row may appear that the stated rule does not cover.

    Both halves matter. Under the week threshold and it is an ordinary
    fall-off; inside the top 25 and the rule does not retire it at all --
    measured, 56 long-tenured entries left from the top 25 across 554 weeks,
    and padding the list with those would make the page's own rule a lie.
    """
    import app

    checked = 0
    for week in app.hot100_recurrents()['weeks'][:400]:
        report = app.hot100_recurrents(week)
        for row in report['dropouts']:
            assert row['weeks'] >= app.RECURRENT_MIN_WEEKS, (week, row)
            assert row['rank'] > app.RECURRENT_RANK, (week, row)
            checked += 1
    assert checked, 'no qualifying rows in 400 weeks — the filter matches nothing'


def test_recurrents_are_a_subset_of_that_week_s_dropouts(client):
    """A recurrent must have actually left the chart. Deriving the rule from
    the live chart instead would retire songs that are still on it."""
    import app

    for week in app.hot100_recurrents()['weeks'][:120]:
        rec = app.hot100_recurrents(week)
        drop = app.chart_dropouts('top100', week)
        gone = {(d['title'], d['rank']) for d in drop['dropouts']}
        for row in rec['dropouts']:
            assert (row['title'], row['rank']) in gone, (week, row)
        assert rec['considered'] == len(drop['dropouts'])


def test_an_empty_week_renders_as_a_normal_result(client):
    """523 of 554 weeks retire nobody. That has to read as the expected
    outcome, not as a broken page."""
    import app

    empty = next(w for w in app.hot100_recurrents()['weeks'][:200]
                 if not app.hot100_recurrents(w)['dropouts'])
    body = client.get('/recurrents?week=' + empty).get_data(as_text=True)
    assert body.count('Nothing became recurrent this week') == 1
    assert 'retired nobody' in body
    # The notice does not disappear on the week where there is no table.
    assert 'Derived, not a Billboard chart' in body


def test_a_bad_week_falls_back_rather_than_erroring(client):
    for q in ('?week=', '?week=nonsense', '?week=1800-01-01', '?week=2199-12-31'):
        assert client.get('/recurrents' + q).status_code == 200, q


def test_the_nav_links_it(client):
    assert 'Recurrents</a>' in client.get('/top100').get_data(as_text=True)
