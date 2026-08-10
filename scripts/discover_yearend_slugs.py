"""Find each registered chart's year-end slug.

Year-end slugs differ from weekly ones ('hot-100-songs' vs 'hot-100'), and
some charts have no year-end edition at all. Probing once and storing the
result keeps every later run from guessing.

A candidate is accepted only if it returns 200, parses to at least 10 rows,
AND is not the weekly chart in disguise. A wrong slug 404s, but a *near* miss
can return a 200 shell with no rows, and a slug with no year-end edition is
answered with the CURRENT WEEKLY chart at full depth: /charts/year-end/2024/
adult-contemporary/ is byte-identical to /charts/adult-contemporary/. Six of
this project's charts hit that path, and a row count alone accepts all of
them, which would store one arbitrary week as a year of chart history.
"""
import json
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

HEADERS = {'User-Agent': ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                          'AppleWebKit/537.36')}
# A discontinued chart has no recent year to probe, and because Billboard
# clamps FORWARD there is no later year to fall back on either. Dance Singles
# Sales ended in 2007, so a 2024 probe reads as "no year-end edition" when the
# chart in fact has one. Probing an older year as well avoids that false
# negative.
PROBE_YEARS = (2024, 2006)
OUT = Path(__file__).resolve().parent / 'yearend_slugs.json'

# Hand-checked where the pattern does not hold. Everything else is guessed
# from the label by the candidate rules below.
KNOWN = {
    'top100': 'hot-100-songs',
    'albums200': 'top-billboard-200-albums',
    'artist100': 'top-artists',
    'radio': 'radio-songs',
    'digital': 'digital-song-sales',
    'streaming': 'streaming-songs',
    'global200': 'billboard-global-200',
    'globalexus': 'billboard-global-excl-us',
    'pop_airplay': 'pop-songs',
    'adult_pop': 'adult-pop-songs',
    'rhythmic': 'rhythmic-songs',
    'adult_rnb': 'adult-r-and-b-songs',
    'dance_airplay': 'dance-mix-show-airplay-songs',
    'dance_sales': 'hot-dance-singles-sales',
    # The obvious slug for each of these is the weekly one, which falls
    # through to the weekly chart instead of 404ing. The year-end editions
    # live under a '-songs' suffix.
    'digital': 'digital-songs',
    'adult_contemporary': 'adult-contemporary-songs',
    'country_airplay': 'country-airplay-songs',
    'alternative': 'alternative-songs',
    # Neither of these is reachable from the label. Measured 2026-08-10.
    #   rock_songs - the year-end kept the chart's OLD name: the weekly is
    #     "Hot Rock & Alternative Songs" but the year-end is 'hot-rock-songs'.
    #     Every label-derived candidate returns 0 rows.
    #   rnb_hiphop - the candidate rules turn '&' into 'and' and so can only
    #     ever produce 'randb'; Billboard writes 'r-and-b'. This chart was
    #     previously recorded as having NO year-end on the strength of two
    #     other slugs, and that was wrong.
    'rock_songs': 'hot-rock-songs',
    'rnb_hiphop': 'r-and-b-hip-hop-airplay-songs',
}

# Charts with no year-end edition, each confirmed by hand because a plausible
# near miss exists for every one of them:
#   heatseekers - every candidate falls through to the weekly chart.
#   bubbling    - same; Billboard publishes no year-end Bubbling Under.
#   rnb_songs   - the CONSUMPTION chart. 'hot-r-and-b-hip-hop-songs' looks
#                 right and returns 200, but it is the weekly chart falling
#                 through. The one 50-row list that does exist belongs to the
#                 airplay chart, not this one: of the titles it shares with
#                 exactly one of the two CSVs, 26 are airplay-only and 2 are
#                 consumption-only.
#   top_album_sales - 'top-album-sales' serves the weekly chart; three other
#                 candidates return 0 rows.
#   uk_songs    - 'official-uk-songs' serves the weekly chart; the rest 404.
#   japan_hot100 - the dangerous one. 'japan-hot-100' returns 100 rows for
#                 2018-2022 and looks genuine, but 2020, 2021 and 2022 are the
#                 SAME 100 titles, and only 19% of them appear anywhere in the
#                 2020 weekly data (52 weeks scraped, so this is not a coverage
#                 gap). One list filed under several years, as with the
#                 European Hot 100. The clamp rule would keep 2022 and store it
#                 as genuine, so this chart must stay excluded by name.
# The row-count test passes several of these, which is why acceptance is also
# checked against the weekly page and the chart's own CSV.
NO_YEAREND = {'heatseekers', 'bubbling', 'rnb_songs', 'top_album_sales',
              'uk_songs', 'japan_hot100'}


def candidates(key, label):
    if key in KNOWN:
        yield KNOWN[key]
    base = (label.lower()
            .replace('&', 'and').replace('/', '-').replace('.', '')
            .replace(' ', '-'))
    yield base
    yield f'{base}-songs'
    yield f'hot-{base}-songs'


def titles(session, url, weekly_only=False):
    """Ordered row titles for a chart page, or [] if there are none.

    With weekly_only, a response that settles on a year-end URL returns []: a
    year-end-only slug has no weekly page, and asking for one redirects to the
    LATEST year-end chart. Comparing against that would reject the slug for
    matching itself.
    """
    try:
        r = session.get(url, timeout=25)
    except requests.RequestException:
        return []
    if r.status_code != 200:
        return []
    if weekly_only and '/year-end/' in r.url:
        return []
    soup = BeautifulSoup(r.text, 'html.parser')
    out = []
    for item in soup.find_all('div',
                              class_='o-chart-results-list-row-container'):
        el = item.find('h3', class_='c-title')
        if el:
            out.append(el.get_text(strip=True))
    return out


def rows_for(session, slug):
    """Row count for a slug, or 0 if it is the weekly chart falling through.

    The weekly page is fetched once and compared against every probe year: a
    slug with no year-end edition serves that exact page for any year asked.
    """
    weekly = titles(session, f'https://www.billboard.com/charts/{slug}/',
                    weekly_only=True)
    best = 0
    for year in PROBE_YEARS:
        got = titles(session,
                     f'https://www.billboard.com/charts/year-end/{year}/{slug}/')
        if got and weekly and got == weekly:
            print(f'    {slug} @ {year}: weekly chart, not a year-end edition',
                  flush=True)
            return 0
        best = max(best, len(got))
        if best >= 10:
            break
    return best


def main():
    import app
    session = requests.Session()
    session.headers.update(HEADERS)
    found = {}
    for key, meta in app.CHARTS.items():
        if key in NO_YEAREND:
            found[key] = None
            print(f'{key}: NO YEAR-END EDITION (confirmed by hand)', flush=True)
            continue
        hit = None
        for slug in candidates(key, meta['label']):
            n = rows_for(session, slug)
            print(f'  {key}: {slug} -> {n} rows', flush=True)
            if n >= 10:
                hit = slug
                break
        found[key] = hit
        print(f'{key}: {hit or "NO YEAR-END EDITION"}', flush=True)
    OUT.write_text(json.dumps(found, indent=2) + '\n')
    have = sum(1 for v in found.values() if v)
    print(f'\n{have} of {len(found)} charts have a year-end edition')
    print(f'wrote {OUT}')


if __name__ == '__main__':
    main()
