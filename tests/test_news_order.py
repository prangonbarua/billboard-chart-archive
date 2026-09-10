"""The order the news page lists number-one changes in.

A week turns over more number ones than the page prints, so which ones survive
the cap is an editorial decision and the only one on that page. It is made
here, once: the flagship charts lead in a fixed order and everything else
follows alphabetically. Alphabetical alone put Adult R&B Airplay above the
Hot 100.

Ordering is keyed on the chart KEY, not its label. Labels carry trademark
symbols and get reworded; keys are the registry's identity and do not move.
"""
import pandas as pd
import pytest

import news


def _chart(rows_now, rows_prev, week, prev_week):
    """A two-week frame in the shape weekly_news reads."""
    recs, dates = [], []
    for rank, (song, artist) in enumerate(rows_prev, start=1):
        recs.append(dict(Rank=rank, Song=song, Artist=artist))
        dates.append(prev_week)
    for rank, (song, artist) in enumerate(rows_now, start=1):
        recs.append(dict(Rank=rank, Song=song, Artist=artist))
        dates.append(week)
    return pd.DataFrame(recs), pd.Series(pd.to_datetime(dates))


WEEK = '2026-09-05'
PREV = '2026-08-29'


def _world(keys):
    """One flipped number one on every chart in `keys`."""
    chart_data, chart_dt, charts = {}, {}, {}
    for i, key in enumerate(keys):
        df, dt = _chart([(f'New {key}', 'A')], [(f'Old {key}', 'B')], WEEK, PREV)
        chart_data[key] = (df, None)
        chart_dt[key] = dt
        charts[key] = dict(label=f'Label {i} {key}', kind='song')
    return chart_data, chart_dt, charts


def _order(keys):
    out = news.weekly_news(*_world(keys))
    return [n['key'] for n in out['new_ones']]


def test_the_flagship_charts_lead_in_their_declared_order():
    # Deliberately fed in reverse, with labels that sort the other way too, so
    # a pass cannot come from input order or from alphabetising the labels.
    assert _order(list(reversed(news.LEAD_CHARTS))) == list(news.LEAD_CHARTS)


def test_a_flagship_outranks_a_chart_that_is_alphabetically_first():
    # The case that prompted this: 'Adult R&B Airplay' beat the Hot 100.
    order = _order(['adultrb', 'top100'])
    assert order[0] == 'top100'


@pytest.mark.parametrize('key', news.LEAD_CHARTS)
def test_every_lead_chart_is_a_real_registry_key(key):
    """A typo here fails silently — the chart just never leads. Ordering is by
    key precisely so this check is possible."""
    import ast

    from test_nav_panel_width import APP, _assignment

    tree = ast.parse(APP.read_text())
    charts = _assignment(tree, 'CHARTS')
    keys = {k.value for k in charts.keys if isinstance(k, ast.Constant)}
    assert key in keys


def test_non_flagship_charts_stay_alphabetical_by_label():
    out = news.weekly_news(*_world(['zzz', 'aaa', 'mmm']))
    labels = [n['chart'] for n in out['new_ones']]
    assert labels == sorted(labels)


def test_the_lead_order_survives_a_chart_that_did_not_change_hands():
    """Rank the ones that flipped, not the registry. A flagship holding its
    number one must not leave a hole at the top of the list."""
    chart_data, chart_dt, charts = _world(['top100', 'albums200'])
    # Hot 100 holds: same title both weeks.
    df, dt = _chart([('Held', 'A')], [('Held', 'A')], WEEK, PREV)
    chart_data['top100'], chart_dt['top100'] = (df, None), dt
    out = news.weekly_news(chart_data, chart_dt, charts)
    assert [n['key'] for n in out['new_ones']] == ['albums200']
