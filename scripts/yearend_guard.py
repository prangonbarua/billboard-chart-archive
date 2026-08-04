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

    A year survives unless the NEXT year is consecutive and carries the same
    signature, which means this year is that year's clamped copy.

    `weekly_sig` is the signature of the chart's own weekly page. Years
    matching it are removed first, before the clamp rule runs, so that
    dropping a weekly-matching year never promotes the copy behind it.
    """
    years = sorted(y for y, s in year_sigs.items()
                   if s is not None and s != weekly_sig)
    keep = []
    for i, year in enumerate(years):
        nxt = years[i + 1] if i + 1 < len(years) else None
        clamped = (nxt is not None
                   and nxt == year + 1
                   and year_sigs[nxt] == year_sigs[year])
        if not clamped:
            keep.append(year)
    return keep
