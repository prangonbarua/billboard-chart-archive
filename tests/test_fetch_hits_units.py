"""scripts/fetch_hits_units.py: parsing, the copied-week guard, and matching.

Offline: pages are built in the shape HITS serves (Next.js flight chunks).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
import fetch_hits_units as h  # noqa: E402


def row(rank, artist, album, units):
    return {'last_week': None, 'last_week_status': 'new', 'this_week': rank, 'rank': None,
            'artist': artist, 'album': album, 'label': 'L',
            'data': {'Activity': f'{units:,}', '+/-': '--', 'Albums': '1,000', 'TEA': '1', 'SEA': '2'}}


def page(chart_date, rows, split=2):
    """Top `split` rows in an items array, the rest as loose objects, as HITS does."""
    compact = {'separators': (',', ':')}   # HITS serves compact JSON
    head = json.dumps({'chartDate': chart_date, 'items': rows[:split]}, **compact)
    tail = ''.join(json.dumps({'x': r}, **compact) for r in rows[split:])
    payload = json.dumps(head + tail)
    return f'<script>self.__next_f.push([1,{payload}])</script>'


def ranked(n, tag='a'):
    return [row(i, f'Artist {tag}{i}', f'Album {tag}{i}', 1000 * (60 - i)) for i in range(1, n + 1)]


def test_reads_rows_inside_and_outside_the_items_array():
    served, rows = h.parse_page(page('2026-03-05', ranked(5)))
    assert served == '2026-03-05'
    assert [r['rank'] for r in rows] == [1, 2, 3, 4, 5]
    assert rows[4]['data']['Activity'] == '55,000'


def test_a_rank_gap_refuses_the_week():
    rows = ranked(5)
    del rows[3]
    assert h.parse_page(page('2026-03-05', rows))[1] == []


def test_fetch_rejects_a_page_serving_another_week():
    class Resp:
        status_code = 200
        text = page('2026-09-24', ranked(3))

    class Session:
        def get(self, url, **kw):
            return Resp()

    assert h.fetch_week('2026-09-17', Session()) is None
    assert h.fetch_week('2026-09-24', Session()) is not None


def parsed(rows):
    return h.parse_page(page('x', rows))[1]


def test_copied_week_keeps_the_copy_that_fits_billboard():
    # 02-05 is served as a copy of 02-12; only 02-12 fits the chart 9 days on.
    real = parsed(ranked(10, 'j'))
    weeks = {'2026-02-05': real, '2026-02-12': real, '2026-02-19': parsed(ranked(10, 'k'))}
    billboard = {
        '2026-02-14': [(i, f'Other {i}', 'x') for i in range(1, 21)],
        '2026-02-21': [(i, f'Album j{i}', f'Artist j{i}') for i in range(1, 21)],
    }
    kept, dropped = h.drop_copied_weeks(weeks, billboard)
    assert sorted(kept) == ['2026-02-12', '2026-02-19']
    assert dropped[0][0] == '2026-02-05'


def test_copied_week_with_a_tied_fit_is_dropped_on_both_dates():
    real = parsed(ranked(10, 'j'))
    kept, dropped = h.drop_copied_weeks({'2026-02-05': real, '2026-02-12': real}, {})
    assert kept == {}
    assert [w for w, _ in dropped] == ['2026-02-05', '2026-02-12']


def hits(artist, album):
    return {'rank': 1, 'artist': artist, 'album': album, 'data': {}}


def test_matching_folds_billboard_tags_and_soundtrack_credits():
    chart = [(1, 'KPop Demon Hunters', 'Soundtrack'), (2, 'GREENGREEN (EP)', 'CORTIS'),
             (3, 'The Best Of Nickelback: Volume 1', 'Nickelback'),
             (4, 'Curtain Call: The Hits', 'Eminem'), (5, 'Westside Whimsy', 'Jhene Aiko')]
    rows = [hits('KPOP DEMON HUNTERS', 'SOUNDTRACK'), hits('CORTIS', 'GREENGREEN'),
            hits('NICKELBACK', 'THE BEST OF NICKELBACK VOL. 1'), hits('EMINEM', 'CURTAIN CALL'),
            hits('JHENÉ AIKO', 'WESTSIDE WHIMSY')]
    matched, unmatched = h.match(rows, chart)
    assert unmatched == []
    assert [e[0] for _, e in matched] == [1, 2, 3, 4, 5]


def test_matching_never_guesses_between_two_candidates():
    chart = [(1, 'Greatest Hits', 'Queen'), (2, 'Greatest Hits II', 'Queen')]
    matched, unmatched = h.match([hits('QUEEN', 'HITS')], chart)
    assert matched == [] and len(unmatched) == 1


def test_one_billboard_entry_never_gets_two_units_rows():
    chart = [(1, 'Swag', 'Justin Bieber')]
    rows = [hits('JUSTIN BIEBER', 'SWAG'), hits('JUSTIN BIEBER', 'SWAG II')]
    matched, unmatched = h.match(rows, chart)
    assert len(matched) == 1 and len(unmatched) == 1


def test_billboard_date_is_nine_days_after_the_hits_week():
    assert h._bb_date('2026-09-17') == '2026-09-26'
