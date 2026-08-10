"""The year-end fabrication guard.

Billboard serves any year you ask for. A year it has no chart for is answered
with the next year it does have, at HTTP 200 with a full row count and no year
stated anywhere on the page. Observed on hot-100-songs: 1958-1969 all return
the 1970 chart, and 1991-2005 all return the 2006 chart.

So a run of consecutive years sharing one ranking signature is one real year
(the latest) plus its clamped copies.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))

from yearend_guard import ranking_signature, real_years


def rows(*titles):
    return [{'Rank': i + 1, 'Song': t, 'Artist': f'Artist {t}'}
            for i, t in enumerate(titles)]


def test_signature_is_stable_for_identical_rankings():
    assert ranking_signature(rows('a', 'b')) == ranking_signature(rows('a', 'b'))


def test_signature_differs_when_order_differs():
    assert ranking_signature(rows('a', 'b')) != ranking_signature(rows('b', 'a'))


def test_signature_of_empty_is_none():
    assert ranking_signature([]) is None


def test_forward_clamp_keeps_only_the_latest_year():
    # 1998, 1999, 2000 all serve 2001's chart.
    sigs = {1998: 'X', 1999: 'X', 2000: 'X', 2001: 'X'}
    assert real_years(sigs) == [2001]


def test_distinct_years_all_survive():
    sigs = {2020: 'A', 2021: 'B', 2022: 'C'}
    assert real_years(sigs) == [2020, 2021, 2022]


def test_fabricated_run_between_two_real_runs():
    # The observed hot-100-songs shape: real 1989-1990, fabricated 1991-2005
    # all serving 2006, then real 2007.
    sigs = {1989: 'P', 1990: 'Q'}
    sigs.update({y: 'R' for y in range(1991, 2007)})
    sigs[2007] = 'S'
    assert real_years(sigs) == [1989, 1990, 2006, 2007]


def test_non_consecutive_years_with_equal_signatures_collapse():
    # This test used to assert both survive, on the reasoning that a gap means
    # the two are not one run so neither can be a clamp of the other. Measured
    # 2026-08-10, that is wrong: hot-rock-songs serves 2009's list for both
    # 1978 and 2005 while returning 0 rows for 1979-1981 and 2006-2008, so the
    # empty years split one clamped run into pieces. Both survived the old rule
    # and stored 2009's chart under years in which the chart did not exist.
    sigs = {2010: 'A', 2012: 'A'}
    assert real_years(sigs) == [2012]


def test_gap_years_do_not_rescue_a_clamped_copy():
    # The hot-rock-songs shape, reduced: one list served for two blocks
    # separated by years the source answers with nothing.
    sigs = {1978: 'A', 1979: None, 1980: None, 2005: 'A', 2009: 'A'}
    assert real_years(sigs) == [2009]


def test_years_with_no_signature_are_dropped():
    sigs = {2019: None, 2020: 'A'}
    assert real_years(sigs) == [2020]


def test_empty_input():
    assert real_years({}) == []


# A slug with no year-end edition is not answered with a 404. Billboard serves
# the CURRENT WEEKLY chart at full depth for every year asked:
# /charts/year-end/2024/adult-contemporary/ is byte-identical to
# /charts/adult-contemporary/. The run-of-identical-years rule alone would keep
# the latest year and store one arbitrary week as a year of chart history, so
# the weekly page is fetched once per chart and matched against explicitly.

def test_weekly_fallthrough_drops_every_year():
    sigs = {y: 'W' for y in range(2020, 2025)}
    assert real_years(sigs, weekly_sig='W') == []


def test_weekly_signature_dropped_from_a_mixed_run():
    sigs = {2022: 'A', 2023: 'B', 2024: 'W'}
    assert real_years(sigs, weekly_sig='W') == [2022, 2023]


def test_no_weekly_signature_changes_nothing():
    sigs = {2022: 'A', 2023: 'B'}
    assert real_years(sigs, weekly_sig=None) == [2022, 2023]


def test_weekly_drop_happens_before_the_clamp_rule():
    """A year is not kept just because the weekly-matching year after it went.

    2023 and 2024 share a signature, so 2023 is 2024's clamped copy. If 2024
    is dropped as the weekly chart, 2023 must not be promoted in its place:
    it is still a copy of a page that was never a year-end chart.
    """
    sigs = {2022: 'A', 2023: 'W', 2024: 'W'}
    assert real_years(sigs, weekly_sig='W') == [2022]
