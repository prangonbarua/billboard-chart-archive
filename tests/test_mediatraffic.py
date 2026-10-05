import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
import backfill_mediatraffic  # noqa: E402
import fast_mediatraffic_scraper as mt  # noqa: E402


class Resp:
    def __init__(self, body, status=200):
        self.status_code, self.content = status, body.encode('iso-8859-1')


class Session:
    def __init__(self, pages):
        self.pages = pages

    def get(self, url, **_):
        return Resp(self.pages[url]) if url in self.pages else Resp('', 404)


def row(rank, meta, title):
    return (f'<tr><td><img src="{rank:02d}.jpg"></td><td>{meta}</td>'
            f'<td><b>{title}</b><br>Label - 1.000</td></tr>')


def week_page(label, rows):
    return f'<html>{label}<table>{"".join(rows)}</table></html>'


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(mt.time, 'sleep', lambda s: None)


def test_album_pages_are_artist_first_and_tracks_are_song_first():
    rows = [row(1, '2 / 1 week 5', 'Dido - Life For Rent'), row(2, '- / -', 'Usher - Confessions')]
    page = week_page('week 01 / 2004 - January 3', rows)
    s = Session({mt.week_url(2004, 1, 'albums'): page, mt.week_url(2004, 1): page})
    _, albums, _ = mt.scrape_mediatraffic_week(2004, 1, session=s, chart='albums')
    _, tracks, _ = mt.scrape_mediatraffic_week(2004, 1, session=s)
    assert (albums[0]['Song'], albums[0]['Artist']) == ('Life For Rent', 'Dido')
    assert (tracks[0]['Song'], tracks[0]['Artist']) == ('Dido', 'Life For Rent')
    assert albums[0]['Last Week'] == '2' and albums[0]['Weeks on Chart'] == 5
    assert albums[1]['Last Week'] == ''  # "- / -" is a re-entry, not rank 0


def test_album_urls_and_first_year():
    assert mt.week_url(2010, 20, 'albums').endswith('/albums-week20-2010.htm')
    assert mt.week_url(2003, 2).endswith('/singles-week02-2003.htm')
    with pytest.raises(ValueError):
        mt.scrape_mediatraffic_week(2003, 1, chart='albums')


def test_yearend_requires_its_own_year_and_a_complete_rank_run():
    rows = [row(1, '', 'This Love - Maroon 5'), row(2, '', 'Yeah! - Usher')]
    url = f'{mt.BASE}/tracks-2004.htm'
    assert mt.scrape_mediatraffic_yearend(2004, session=Session({url: week_page('COUNTDOWN 2004', rows)})) == [
        (1, 'This Love', 'Maroon 5'), (2, 'Yeah!', 'Usher')]
    assert mt.scrape_mediatraffic_yearend(2004, session=Session({url: week_page('COUNTDOWN 2005', rows)})) is None
    holed = [rows[0], row(3, '', 'Hey Ya! - Outkast')]
    assert mt.scrape_mediatraffic_yearend(2004, session=Session({url: week_page('COUNTDOWN 2004', holed)})) is None
    albums = f'{mt.BASE}/albums-2004.htm'
    got = mt.scrape_mediatraffic_yearend(
        2004, 'albums', session=Session({albums: week_page('COUNTDOWN 2004', [row(1, '', 'Usher - Confessions')])}))
    assert got == [(1, 'Confessions', 'Usher')]


def test_backfill_appends_new_weeks_without_rewriting_old_rows(tmp_path, monkeypatch):
    csv_path = tmp_path / 'w.csv'
    old = ('Date,Rank,Song,Artist,Last Week,Peak Position,Weeks on Chart\r\n'
           '2026-09-26,1,Old,Someone,1,,10\r\n')
    csv_path.write_bytes(old.encode())
    week = {'Date': '2026-10-03', 'Rank': 1, 'Song': 'New', 'Artist': 'X', 'Last Week': '',
            'Peak Position': '', 'Weeks on Chart': ''}
    old_week = dict(week, Date='2026-09-26', Song='Old')

    def fake(year, w, chart='tracks'):
        return {39: ('2026-09-26', [old_week], 0), 40: ('2026-10-03', [week], 0)}.get(w)

    monkeypatch.setattr(backfill_mediatraffic, 'scrape_mediatraffic_week', fake)
    monkeypatch.setattr(sys, 'argv', ['x', str(csv_path), '2026', '2026'])
    backfill_mediatraffic.main()
    assert csv_path.read_bytes() == (old + '2026-10-03,1,New,X,,,\r\n').encode()


def test_an_unparseable_last_row_refuses_the_week_instead_of_truncating_it():
    # The rank check alone cannot see a dropped LAST row: 1..9 is a complete run.
    # This is how 2021-01-23 was stored as a 9-album top 10.
    rows = [row(1, '', 'Dido - Life For Rent'), row(2, '', 'Harry Styles . Fine Line')]
    url = mt.week_url(2004, 1, 'albums')
    s = Session({url: week_page('week 01 / 2004 - January 3', rows)})
    assert mt.scrape_mediatraffic_week(2004, 1, session=s, chart='albums') is None
    yurl = f'{mt.BASE}/albums-2004.htm'
    ys = Session({yurl: week_page('COUNTDOWN 2004', rows)})
    assert mt.scrape_mediatraffic_yearend(2004, 'albums', session=ys) is None


def test_a_known_separator_typo_is_split_by_its_override_and_only_on_exact_text(monkeypatch):
    monkeypatch.setitem(mt.SEPARATOR_TYPOS, ('albums', 2004, 1, 2),
                        ('Harry Styles . Fine Line', 'Fine Line', 'Harry Styles'))
    url = mt.week_url(2004, 1, 'albums')
    good = [row(1, '', 'Dido - Life For Rent'), row(2, '', 'Harry Styles . Fine Line')]
    s = Session({url: week_page('week 01 / 2004 - January 3', good)})
    _, rows, _ = mt.scrape_mediatraffic_week(2004, 1, session=s, chart='albums')
    assert [(r['Rank'], r['Song'], r['Artist']) for r in rows] == [
        (1, 'Life For Rent', 'Dido'), (2, 'Fine Line', 'Harry Styles')]
    # A page whose text drifted from what was checked by hand is refused, not guessed.
    drifted = [good[0], row(2, '', 'Harry Styles . Fine Line (Deluxe)')]
    s = Session({url: week_page('week 01 / 2004 - January 3', drifted)})
    assert mt.scrape_mediatraffic_week(2004, 1, session=s, chart='albums') is None
