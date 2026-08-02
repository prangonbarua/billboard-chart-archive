# Handoff: Adult R&B Airplay (chart 17)

Branch `add-adult-rnb-airplay` (631ec34), off main 66319b6. Main is green and deployed.

## Done

Registry wiring in `app.py`, all four touchpoints:
- `ADULT_RNB_DATA, ADULT_RNB_AVAILABLE_DATES = _load_global_chart('adult_rnb_airplay.csv')`
- `CHARTS['adult_rnb']` — label "Adult R&B Airplay", group Airplay, depth 25, kind song
- `CHART_DATA['adult_rnb']`
- added to the format-airplay route loop, so it gets a page off the shared `chart.html`

Also `scripts/fast_billboard_scraper.py` (weekly line, slug `adult-r-and-b-songs`)
and the `git add` line in `.github/workflows/update-charts.yml`.

Nav needs no edit — it loops the registry.

## Remaining

1. **The scrape.** Started 2026-08-02, `nohup python3 scrape_adult_rnb.py` writing
   `data/adult_rnb_airplay.csv`, ~1,760 weeks back from now, about 7.5 weeks/min
   so roughly 4 hours. The scraper only writes the CSV at the END, so an
   interrupted run leaves nothing — check the process before assuming it worked.
   Re-run: `update_chart_data('adult-r-and-b-songs', 'data/adult_rnb_airplay.csv', weeks_to_fetch=1760)`
   with `scripts/` on `sys.path`.

2. **Confirm the depth.** Registry says 25. The 1993 weeks scrape at 50 rows, so
   the chart shrank at some point; set `depth` to its CURRENT size, and note the
   registry comment that depth is display-only and must not be used as a scrape
   completeness threshold.

3. **`test_every_chart_route_returns_200` fails until the CSV lands.** That is the
   test doing its job, not a defect. It should pass with no code change once the
   data is there. Do not merge before it is green.

4. Then merge to main, push, `railway up --detach --service billboard-chart-archive`.

## Separate, unrelated, still open

Data audit on 2026-08-02 found a real defect in three charts — `radio`,
`digital_songs`, `streaming_songs`. Their pre-November-2025 rows are
Wednesday-dated and every one is **3 days earlier than Billboard's actual chart
date**, verified against billboard.com:

| our row | our date | Billboard's date |
|---|---|---|
| radio Wed 10-15 | 2025-10-15 | 2025-10-18 |
| radio Wed 10-22 | 2025-10-22 | 2025-10-25 |

That is 1,826 / 1,096 / 666 weeks respectively. The 2025-10-25 week is also
stored **twice** in all three (once as Wed 10-22, once as Sat 10-25) —
`streaming_songs` shows them byte-identical.

Fix: shift Wednesday rows +3 days, then drop the week that collides at the seam.
The other 13 charts are correctly Saturday-dated.

Also unexplained, low priority: three gaps in `adult_contemporary` at 1979-04-21,
1979-09-15, 1980-12-06. The other 26 calendar gaps across all charts are
Billboard's holiday non-publication weeks and are accurate.
