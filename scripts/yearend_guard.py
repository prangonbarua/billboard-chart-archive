"""Tell a real year-end chart from one Billboard fabricated.

The weekly scraper reads the page's own "Week of ..." heading and rejects any
response whose served week differs from the requested one. Year-end pages
carry no equivalent: no redirect, no heading, and the canonical link strips
the year entirely. So the year cannot be verified from a single response, and
the only signal left is comparison between years.

Billboard clamps a missing year FORWARD to the next year it holds, so a run of
consecutive years sharing one ranking is one real year at the end plus its
copies. Keep the latest, drop the rest.

A chart with no year-end edition at all fails differently and worse. It is not
answered with a 404: every year returns the CURRENT WEEKLY chart at full depth,
so /charts/year-end/2024/adult-contemporary/ is byte-identical to
/charts/adult-contemporary/. The run rule alone would keep the latest year and
store one arbitrary week as a year of chart history, so the weekly page is
fetched once per chart and its signature excluded by name.
"""
from __future__ import annotations

import hashlib


def ranking_signature(rows) -> str | None:
    """Hash a year's full (rank, song, artist) ordering."""
    if not rows:
        return None
    parts = [f"{r.get('Rank')}|{r.get('Song')}|{r.get('Artist')}" for r in rows]
    return hashlib.sha1('\n'.join(parts).encode()).hexdigest()


def real_years(year_sigs: dict[int, str | None],
               weekly_sig: str | None = None) -> list[int]:
    """Genuine years, ascending, from a {year: signature} map.

    A year survives unless some LATER year carries the same signature, which
    means this year is that year's clamped copy.

    The later year does not have to be adjacent. Requiring adjacency was the
    original rule and it leaks: hot-rock-songs answers 1962-1978 and 1982-2005
    with 2009's list but returns 0 rows for 1979-1981 and 2006-2008, and those
    empty years break the run into three pieces. 1978 and 2005 then have no
    consecutive successor and both survive, storing 2009's chart twice under
    years in which the chart did not exist. Two ranking orders of fifty songs
    do not coincide by accident, so an equal signature is a copy however far
    apart the years sit.

    `weekly_sig` is the signature of the chart's own weekly page. Years
    matching it are removed first, before the clamp rule runs, so that
    dropping a weekly-matching year never promotes the copy behind it.
    """
    years = sorted(y for y, s in year_sigs.items()
                   if s is not None and s != weekly_sig)
    return [year for i, year in enumerate(years)
            if not any(year_sigs[later] == year_sigs[year]
                       for later in years[i + 1:])]
