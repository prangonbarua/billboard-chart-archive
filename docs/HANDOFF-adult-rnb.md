# Adult R&B Airplay (chart 17) — done, plus one open defect

Chart 17 is complete. This file is kept for the slug trap below, which is a live
hazard for anyone adding another chart, and for the open chart-date defect at
the end.

## The slug trap — read this before adding a chart

The first attempt at this chart used the slug `adult-r-and-b-songs`. That is not
a weekly chart URL. Billboard answers it with **HTTP 200** and redirects to
`/charts/year-end/adult-r-and-b-songs/`, a year-end page that parses perfectly
well: 50 clean rows, correct-looking songs and artists. The scraper stored those
rows under whatever date it had requested. Every week it "fetched" — 1992, 1993
and 2026 alike — was an identical copy of the current year-end list, with Chris
Brown's "Residuals" at #1 in 1993.

Nothing in the old pipeline could catch this. The row-count floor passed (50 rows
clears any floor), the response was 200, and the markup was valid. It would have
written 1,760 weeks of fabricated history that looked complete.

A second, separate failure mode has the same shape: a date **before** a chart
launched is clamped to that chart's first published week, again under the
requested date, again 200, again valid markup.

`scrape_billboard_chart` now defends against both. It reads the "Week of ..."
heading Billboard prints on every real chart page and discards the response
unless that week equals the week requested. Row count cannot detect either
failure; the served date can. Verified to reject all three known-bad cases and
to accept 12 legitimate weeks spanning 1975-2026 across every chart family.

Corrected facts, each independently confirmed:

| | first attempt claimed | actual |
|---|---|---|
| slug | `adult-r-and-b-songs` | `hot-adult-r-and-b-airplay` |
| first week | 1993-04-24 | **1993-09-18** |
| depth | 25, "shrank from 50" | **30**, never changed |

The "shrank from 50" reading was itself an artifact of the year-end page's 50
rows. 1993-09-18 is corroborated by `scripts/find_chart_start.py` and by the
fact that Mainstream R&B/Hip-Hop launched the same week.

Use `scripts/backfill_chart.py` for a full history, never `update_chart_data`.
The backfill script is resumable and checkpoints every 25 weeks;
`update_chart_data` accumulates in memory and writes once at the very end, so an
interrupted run leaves nothing on disk.

    python3 scripts/backfill_chart.py \
        hot-adult-r-and-b-airplay data/adult_rnb_airplay.csv 1993-09-18

## Result

51,150 rows, 1,705 weeks, 1993-09-18 -> 2026-08-01. Exactly 30 rows every week,
all Saturday-dated, no duplicate (Date, Rank), no nulls, and zero clamped weeks
found by the signature check.

11 weeks are absent because **Billboard has no data for them**. Each returns 200
with an empty page — identical at 893,553 bytes against ~1.55 MB for a real week
— and each was re-checked well after the scrape with the same result:

- 1998-12-26, 1999-01-02, 1999-01-09
- 2011-09-17 through 2011-10-22 (six weeks; 2011-10-29 exists)
- 2011-11-05
- 2013-08-10

`verify_charts.py` reports these as non-weekly-step warnings, the same way it
already reports the holiday gaps in adult_contemporary, country and alternative.
They are not listed in `known_clamped_weeks.json` — that file is for weeks whose
ranking repeats a neighbour, which is a different condition.

## Still open: chart dates in radio, digital_songs, streaming_songs

Their pre-November-2025 rows are Wednesday-dated and every one is **3 days
earlier than Billboard's actual chart date**. Confirmed two ways: requesting a
Wednesday date makes Billboard serve the Wednesday+3 Saturday page, and our
2020-06-10 rows match Billboard's 2020-06-13 chart exactly.

Affected: radio 1,826 weeks, digital_songs 1,096, streaming_songs 666 — each
running from that chart's start through 2025-10-22, after which the CSVs switch
to correct Saturday dating at 2025-10-25. The other 14 charts are Saturday-dated
throughout.

Fix: shift the Wednesday rows +3 days.

Note: an earlier draft of this file also claimed the 2025-10-25 week was stored
twice, once as Wed 10-22 and once as Sat 10-25, byte-identical. That does **not**
hold — radio's 2025-10-22 and 2025-10-25 differ. Re-check the seam before
assuming there is a collision to clean up.

Also unexplained, low priority: three gaps in `adult_contemporary` at 1979-04-21,
1979-09-15, 1980-12-06. The other calendar gaps across all charts are Billboard's
holiday non-publication weeks and are accurate.
