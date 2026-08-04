"""The scraper's parse and its use of the guard, with no network."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))

from backfill_yearend import is_weekly_url, parse_yearend, scrape_chart

ROW = '''
<div class="o-chart-results-list-row-container">
  <span class="c-label">{rank}</span>
  <h3 class="c-title">{song}</h3>
  <span class="a-no-trucate">{artist}</span>
  <img class="c-lazy-image__img" data-lazy-src="https://img/{rank}.jpg">
</div>
'''


def page(*triples):
    return '<html><body>' + ''.join(
        ROW.format(rank=i + 1, song=s, artist=a)
        for i, (s, a) in enumerate(triples)) + '</body></html>'


def test_parse_reads_every_field():
    rows = parse_yearend(page(('Lose Control', 'Teddy Swims')))
    assert rows == [{'Rank': 1, 'Song': 'Lose Control',
                     'Artist': 'Teddy Swims', 'Image URL': 'https://img/1.jpg'}]


def test_parse_keeps_chart_order():
    rows = parse_yearend(page(('A', 'X'), ('B', 'Y')))
    assert [r['Rank'] for r in rows] == [1, 2]
    assert [r['Song'] for r in rows] == ['A', 'B']


def test_parse_empty_page():
    assert parse_yearend('<html><body></body></html>') == []


def test_scrape_drops_forward_clamped_years():
    # 1998-2000 all answer with 2001's chart, which is what Billboard does.
    real = {2001: page(('New', 'Now')), 1997: page(('Old', 'Then'))}

    def fake_fetch(slug, year, session=None, timeout=25):
        if year >= 1998:
            return parse_yearend(real[2001])
        return parse_yearend(real[1997])

    rows, dropped = scrape_chart('top100', 'hot-100-songs',
                                 range(1997, 2002), fetch=fake_fetch,
                                 weekly_rows=[])
    assert sorted({r['Year'] for r in rows}) == [1997, 2001]
    assert dropped == [(1998, 2001), (1999, 2001), (2000, 2001)]


def test_scrape_stamps_chart_and_year():
    def fake_fetch(slug, year, session=None, timeout=25):
        return [{'Rank': 1, 'Song': f'S{year}', 'Artist': 'A',
                 'Image URL': ''}]

    rows, dropped = scrape_chart('canadian_hot100', 'canadian-hot-100',
                                 [2023, 2024], fetch=fake_fetch,
                                 weekly_rows=[])
    assert dropped == []
    assert {(r['Chart'], r['Year']) for r in rows} == {
        ('canadian_hot100', 2023), ('canadian_hot100', 2024)}


def test_scrape_survives_a_failing_year():
    def fake_fetch(slug, year, session=None, timeout=25):
        if year == 2023:
            raise RuntimeError('boom')
        return [{'Rank': 1, 'Song': f'S{year}', 'Artist': 'A', 'Image URL': ''}]

    rows, dropped = scrape_chart('top100', 'hot-100-songs',
                                 [2023, 2024], fetch=fake_fetch,
                                 weekly_rows=[])
    assert sorted({r['Year'] for r in rows}) == [2024]


def test_scrape_rejects_the_weekly_chart_falling_through():
    """A chart with no year-end edition serves its weekly chart for any year.

    Every year would otherwise look like one long clamped run and the latest
    would be kept, writing one arbitrary week as a year of chart history.
    """
    weekly = parse_yearend(page(('This Week', 'Someone')))

    def fake_fetch(slug, year, session=None, timeout=25):
        return list(weekly)

    rows, dropped = scrape_chart('adult_contemporary', 'adult-contemporary',
                                 range(2020, 2025), fetch=fake_fetch,
                                 weekly_rows=weekly)
    assert rows == []


def test_a_year_end_only_slug_has_no_weekly_page():
    """/charts/hot-100-songs/ settles at /charts/year-end/hot-100-songs/.

    That is the LATEST year-end chart. Treating it as the weekly reference
    would drop the newest year of every year-end-only chart.
    """
    assert not is_weekly_url('https://www.billboard.com/charts/year-end/hot-100-songs/')


def test_a_real_weekly_page_is_recognised():
    assert is_weekly_url('https://www.billboard.com/charts/adult-contemporary/')


def test_weekly_rows_do_not_suppress_a_real_year():
    """Only an exact match with the weekly page is a fall-through."""
    weekly = parse_yearend(page(('This Week', 'Someone')))

    def fake_fetch(slug, year, session=None, timeout=25):
        return parse_yearend(page((f'Song {year}', 'Someone')))

    rows, dropped = scrape_chart('top100', 'hot-100-songs', [2023, 2024],
                                 fetch=fake_fetch, weekly_rows=weekly)
    assert sorted({r['Year'] for r in rows}) == [2023, 2024]
