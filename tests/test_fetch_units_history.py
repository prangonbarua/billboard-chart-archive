"""scripts/fetch_units_history.py: the Wikipedia No. 1 table, the pre-2026
HITS page, placing a HITS week on its Billboard chart, and matching.

Offline: pages are built in the shape each source serves.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
import fetch_units_history as u  # noqa: E402


WIKI = '''{| class="wikitable sortable plainrowheaders"
! scope=col| Issue date
! scope=col| Album
! scope=col| Artist(s)
! scope=col| Sales
! scope=col class="unsortable" | {{abbr|Ref.|Reference(s)}}
|-
! scope="row" | {{dts|May 18}}
|style="text-align: center;" rowspan=3|''[[Out of Time (album)|Out of Time]]''
|style="text-align: center;" rowspan=3|[[R.E.M.]]
| rowspan="2" style="text-align: center;" bgcolor="#63666A" |
|<ref>x</ref>
|-
! scope="row" | {{dts|May 25}}
|<ref>y</ref>
|-
! scope="row" | {{dts|June 1}}
|style="text-align: center;"|89,000
|<ref>z</ref>
|-
! scope="row" | {{dts|June 8}}
|''[[Spellbound (Paula Abdul album)|Spellbound]]'' {{dagger}}
|{{Sortname|Paula|Abdul}}
|rowspan="1"|1,258,667
|<ref>{{cite web|url=https://example.org|title=a}}</ref>
|}'''


def test_wiki_rowspans_carry_album_and_skip_the_greyed_weeks():
    rows = u.parse_wiki_year(WIKI, 1991)
    assert rows == [('1991-06-01', 'Out of Time', 'R.E.M.', 89000),
                    ('1991-06-08', 'Spellbound', 'Paula Abdul', 1258667)]


def test_wiki_figure_spanning_several_weeks_is_not_repeated():
    text = WIKI.replace('|style="text-align: center;"|89,000', '|rowspan="2"|89,000').replace(
        "|''[[Spellbound (Paula Abdul album)|Spellbound]]'' {{dagger}}\n|{{Sortname|Paula|Abdul}}\n|rowspan=\"1\"|1,258,667",
        "|''[[Spellbound (Paula Abdul album)|Spellbound]]''\n|{{Sortname|Paula|Abdul}}")
    assert [r[0] for r in u.parse_wiki_year(text, 1991)] == []


def chart(*titles, artist='A'):
    return [(i, t, artist) for i, t in enumerate(titles, 1)]


def test_official_figure_needs_the_same_no1_on_that_date():
    billboard = {'2018-01-06': chart('Revival', artist='Eminem'),
                 '2001-04-21': chart('Now 6', artist='Various Artists'),
                 '2013-02-02': chart('Long.Live.A$AP', artist='A$AP Rocky')}
    rows, rejected = u.official_rows([
        ('2018-01-06', 'Reputation', 'Taylor Swift', 107000),          # a different album
        ('2001-04-21', "Now That's What I Call Music! 6", 'Various Artists', 525005),
        ('2013-02-02', 'Long. Live. ASAP', 'ASAP Rocky', 139000),
        ('2018-01-03', 'Revival', 'Eminem', 267000),                    # no stored chart
    ], billboard)
    assert [(r['Date'], r['Song'], r['Units']) for r in rows] == [
        ('2001-04-21', 'Now 6', 525005), ('2013-02-02', 'Long.Live.A$AP', 139000)]
    assert [d for d, _, _ in rejected] == ['2018-01-06', '2018-01-03']


def legacy_row(tw, lw, artist, title, total, split=None, top=False):
    if top:
        who = (f"<span class='hits_album_chart_item_top_full_details_artist'>{artist}</span><br>"
               f"<span class='hits_album_chart_item_top_dull_details_release'>{title}</span>")
        cells = (f"<td class='hits_album_chart_tw_full_top'>\n{lw}</td>"
                 f"<td class='hits_album_chart_lw_full_top'>{tw}</td><td>{who}</td>")
    else:
        cells = (f"<td class='hits_album_chart_full_tw'>{lw}</td><td class='hits_album_chart_full_lw'>{tw} </td>"
                 f"<td><span class='hits_album_chart_item_details_full_artist'>{artist} | {title}</span></td>")
    cells += f"<td class='hits_album_chart_item_top_details_full_sales chart_tweak col_sales'>{total}</td>"
    if split:
        for name, v in zip(('albums', 'tea', 'sea'), split):
            cells += f"<td class='hits_album_chart_item_top_details_full_sales_{name} chart_tweak'>{v} </td>"
    return f"<tr class='hits_album_chart_header_full_alt1'>{cells}</tr>"


def legacy_page(rows, status='Final'):
    return ("<div class='hits_album_chart_date'>Chart Date: <span class='hits_album_chart_date_value'> "
            "07/06/2018 (WEEK ENDING: 07/05/2018)</span></div>"
            f"<span class='hits_album_chart_version_value'>Status: {status}</span>"
            "<table>" + ''.join(rows) + '</table>')


def test_legacy_page_reads_rank_from_the_swapped_class_and_both_layouts():
    week, status, rows = u.parse_legacy(legacy_page([
        legacy_row(1, '--', 'DRAKE', 'SCORPION', '749,338', ('158,072', '20,831', '570,435'), top=True),
        legacy_row(2, '--', 'FLORENCE + THE MACHINE', 'HIGH AS HOPE', '81,161'),
    ]))
    assert (week, status) == ('2018-07-06', 'Final')
    assert [(r['rank'], r['artist'], r['album']) for r in rows] == [
        (1, 'DRAKE', 'SCORPION'), (2, 'FLORENCE + THE MACHINE', 'HIGH AS HOPE')]
    assert rows[0]['data'] == {'Activity': '749,338', 'Albums': '158,072', 'TEA': '20,831', 'SEA': '570,435'}
    assert rows[1]['data']['Albums'] is None


def test_legacy_page_out_of_sequence_is_refused():
    _, _, rows = u.parse_legacy(legacy_page([legacy_row(1, 3, 'A', 'X', '10', top=True),
                                             legacy_row(3, 1, 'B', 'Y', '9')]))
    assert rows == []


def hits_rows(*titles):
    return [{'rank': i, 'artist': 'A', 'album': t, 'data': {'Activity': '1'}} for i, t in enumerate(titles, 1)]


def test_week_goes_to_the_chart_whose_ranks_it_matches():
    ten = [f'T{i}' for i in range(1, 11)]
    swapped = ten[1:2] + ten[:1] + ten[2:]
    billboard = {'2018-07-14': chart(*ten), '2018-07-21': chart(*swapped)}
    placed, dropped = u.place({'2018-07-05': hits_rows(*ten)}, billboard)
    assert placed == {'2018-07-05': '2018-07-14'} and dropped == []


def test_week_with_a_tied_fit_is_dropped():
    ten = [f'T{i}' for i in range(1, 11)]
    billboard = {'2018-07-14': chart(*ten), '2018-07-21': chart(*ten)}
    placed, dropped = u.place({'2018-07-05': hits_rows(*ten)}, billboard)
    assert placed == {} and 'tied' in dropped[0][1]


def test_repeated_week_is_dropped_both_times():
    rows = hits_rows('X', 'Y')
    kept, bad = u.drop_copies({'2015-02-03': rows, '2015-02-10': rows, '2015-02-17': hits_rows('Z')})
    assert list(kept) == ['2015-02-17'] and bad == ['2015-02-03', '2015-02-10']


def test_compilations_misspellings_and_prefixes_match_only_when_unambiguous():
    rows = [{'rank': 1, 'artist': 'HAMILTON', 'album': 'ORIGINAL BROADWAY CAST', 'data': {}},
            {'rank': 2, 'artist': 'PITBULL', 'album': 'GLOBALIZATON', 'data': {}},
            {'rank': 3, 'artist': 'NOW 57', 'album': 'VARIOUS ARTISTS', 'data': {}},
            {'rank': 4, 'artist': 'X', 'album': 'FROZEN', 'data': {}}]
    bb = [(1, 'Hamilton: An American Musical', 'Original Broadway Cast'),
          (2, 'Globalization', 'Pitbull'), (3, 'NOW 57', 'Various Artists'),
          (4, 'Frozen II', 'Soundtrack'), (5, 'Frozen: The Songs', 'Soundtrack')]
    pairs, missed = u.match(rows, bb)
    assert sorted((r['rank'], e[0]) for r, e in pairs) == [(1, 1), (2, 2), (3, 3)]
    assert [r['album'] for r in missed] == ['FROZEN']


def flight(*chunks):
    import json
    return ''.join(f'<script>self.__next_f.push([1,{json.dumps(c)}])</script>' for c in chunks)


def test_2025_page_resolves_referenced_and_inline_figures():
    row1 = ('{"id":"a","last_week":null,"this_week":1,"rank":null,"artist":"PLAYBOI CARTI",'
            '"album":"MUSIC","label":"AWGE","data":"$42","spotifyTrackId":""}')
    row2 = ('{"id":"b","last_week":2,"this_week":2,"rank":null,"artist":"KENDRICK LAMAR",'
            '"album":"GNX","label":"PGLANG","data":{"Activity":"70,764","Albums":"12,965"},"x":1}')
    page = flight('0:{"chartDate":"2025-03-21","items":[' + row1 + ',' + row2 + ']}\n',
                  '42:{"Activity":"302,083","Albums":"10,280","TEA":"427","SEA":"291,376"}\n')
    week, status, rows = u.parse_capture(page)
    assert (week, status) == ('2025-03-21', 'Final')
    assert [(r['rank'], r['album'], r['data']['Activity']) for r in rows] == [
        (1, 'MUSIC', '302,083'), (2, 'GNX', '70,764')]


def test_a_chart_dated_after_its_capture_is_not_plausible():
    assert u.plausible('2018-03-30', '20180331000000')
    assert not u.plausible('2019-03-29', '20190329010204')     # same day: partial count
    assert not u.plausible('2019-03-30', '20180331000000')     # HITS's own typo
    assert not u.plausible('2017-12-01', '20180331000000')
