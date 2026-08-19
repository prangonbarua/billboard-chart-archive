#!/usr/bin/env python3
"""
Fast Billboard Scraper - Direct web scraping when billboard.py library fails
Uses BeautifulSoup to scrape Billboard.com directly
"""
import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import re
import time
import json

def scrape_billboard_chart(chart_name='hot-100', date=None, min_rows=None):
    """
    Scrape a Billboard chart for a specific date

    Args:
        chart_name: 'hot-100' or 'billboard-200'
        date: Date string 'YYYY-MM-DD' or None for latest
        min_rows: Override the row-count floor below. Only measure_depth_floor.py
            passes this, and only as 1: the floor is what that script exists to
            measure, so applying the default would reject every week of a chart
            that ever ran shallower than 20 and report it as having no depth at
            all. Nothing on the weekly or backfill path may pass this.

    Returns:
        List of chart entries or None if failed
    """
    if date:
        url = f'https://www.billboard.com/charts/{chart_name}/{date}/'
    else:
        url = f'https://www.billboard.com/charts/{chart_name}/'

    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    }

    try:
        print(f"  📥 Scraping {chart_name} for {date or 'latest'}...", end=' ', flush=True)
        response = requests.get(url, headers=headers, timeout=15)

        if response.status_code != 200:
            print(f"✗ Status {response.status_code}")
            return None

        soup = BeautifulSoup(response.content, 'html.parser')

        # Billboard answers 200 for a week a chart never had, and the page it
        # returns parses cleanly, so row count cannot catch it. Two ways it
        # happens, both observed on adult-r-and-b-songs: a slug that is not a
        # weekly chart redirects to /charts/year-end/<slug>/, and a date before
        # the chart launched is clamped to its first published week. Either one
        # would be stored under the date we ASKED for — fabricated history that
        # looks complete. The page states the week it actually served, so make
        # that the authority and drop anything that isn't the week we requested.
        served_date = None
        week_text = soup.find(string=re.compile(r'Week of\s+[A-Z]', re.I))
        if week_text:
            m = re.search(r'Week of\s+([A-Z][a-z]+\s+\d{1,2},\s*\d{4})', week_text)
            if m:
                try:
                    served_date = datetime.strptime(
                        re.sub(r'\s+', ' ', m.group(1)), '%B %d, %Y').strftime('%Y-%m-%d')
                except ValueError:
                    served_date = None

        if date:
            if served_date is None:
                print("✗ No chart date on page (redirect or markup change) — skipping")
                return None
            if served_date != date:
                print(f"✗ Billboard served {served_date}, not {date} — skipping")
                return None

        chart_date = date if date else (served_date or datetime.now().strftime('%Y-%m-%d'))

        # Find all chart entries
        entries = []
        chart_items = soup.find_all('div', class_='o-chart-results-list-row-container')

        for item in chart_items:
            try:
                # Get rank
                rank_elem = item.find('span', class_='c-label')
                if not rank_elem:
                    continue
                rank = int(rank_elem.text.strip())

                # Get song title
                title_elem = item.find('h3', class_='c-title')
                if not title_elem:
                    continue
                song = title_elem.text.strip()

                # Get artist — span.a-no-trucate is the reliable selector
                artist_elem = item.find('span', class_='a-no-trucate')
                if artist_elem:
                    import re as _re
                    artist = _re.sub(r' +', ' ', artist_elem.get_text(separator=' ', strip=True))
                else:
                    artist = "Unknown"

                def find_stat(label):
                    """Find a stat value by its label span (LW, PEAK, WEEKS)."""
                    label_span = next(
                        (s for s in item.find_all('span', class_='c-span')
                         if s.get_text(strip=True) == label), None
                    )
                    if label_span:
                        val_span = label_span.find_next('span', class_='c-label')
                        if val_span:
                            txt = val_span.get_text(strip=True)
                            if txt and txt != '-':
                                try:
                                    return int(txt)
                                except ValueError:
                                    pass
                    return None

                last_week = find_stat('LW')
                peak = find_stat('PEAK') or rank
                weeks = find_stat('WEEKS') or 1

                entries.append({
                    'Date': chart_date,
                    'Rank': rank,
                    'Song': song,
                    'Artist': artist,
                    'Last Week': last_week if last_week else '-',
                    'Peak Position': peak,
                    'Weeks on Chart': weeks
                })

            except Exception as e:
                print(f"  ⚠️  Error parsing entry: {e}")
                continue

        # A partial scrape (e.g. a Billboard markup change drops rows) must not be saved
        # as a complete week, or the incremental logic never re-fetches the missing ranks.
        expected = {'billboard-200': 200, 'billboard-global-200': 200,
                    'billboard-global-excl-us': 200, 'hot-100': 100,
                    'artist-100': 100, 'pop-songs': 40,
                    # These five ran shallower decades ago (Adult Contemporary
                    # was 19-20 rows in 1961-62, Alternative was 30 in 1988),
                    # but that only matters to backfill_chart.py, which walks
                    # those old weeks. This function is also the ONLY gate on
                    # update_chart_data's weekly path, which never looks back
                    # more than 52 weeks — over 2024+ all five run at a fixed
                    # modern depth every single week (verified against the
                    # CSVs: 135/135 weeks at exactly this row count each). A
                    # floor of 10 let a Billboard markup change that drops
                    # rows produce e.g. a 12-row week that still passed the
                    # gate, got written as complete, landed in existing_dates,
                    # and was never re-fetched — a permanent partial week,
                    # the exact failure this gate exists to prevent. Floors
                    # are set to the modern depth instead. A pre-2024 backfill
                    # run of these five will now (correctly, per this file's
                    # sole purpose of guarding the live weekly path) reject
                    # shallow historical weeks below modern depth; fabricated
                    # weeks are still separately caught by the duplicate-
                    # ranking check in backfill_chart.py, not by row count.
                    'country-airplay': 60, 'adult-pop-songs': 40,
                    'rhythmic-40': 40, 'alternative-airplay': 40,
                    'adult-contemporary': 30,
                    # Mainstream R&B/Hip-Hop launched 1993-09-18 at 40 and has
                    # been 40 every week since 1998. The only exceptions are 21
                    # weeks scattered through 1995-1997 that Billboard serves
                    # 34-39 deep; they are already in the CSV, and the weekly
                    # path never looks back that far, so 40 is the right guard.
                    'mainstream-r-and-b-hip-hop': 40,
                    # Dance Airplay is the shallow-era case, same as the five
                    # above. It launched 2003-08-16 at 40, dropped to 25 by
                    # 2003-10-04, held 25 until at least 2014-09-06, and was
                    # back to 40 by 2014-12-06. 40 is the modern depth and so
                    # the right guard for the weekly path; a backfill of the
                    # 25-row era has to run before this floor applies, which is
                    # how data/dance_airplay.csv was populated.
                    'hot-dance-airplay': 40,
                    # Adult R&B Airplay launched 1993-09-18 at 30 rows and has
                    # run 30 every week since — confirmed by find_chart_start.py
                    # and spot checks at 1995, 2000, 2010, 2020 and 2026.
                    'hot-adult-r-and-b-airplay': 30,
                    # Bubbling Under has run 25 rows every week since its
                    # 1992 revival, the only span Billboard serves.
                    'bubbling-under-hot-100-singles': 25,
                    # Canadian Hot 100 has run 100 rows every week since
                    # Billboard's archive begins at 2007-03-31.
                    'canadian-hot-100': 100,
                    # BACKFILL FLOORS, NOT MODERN DEPTHS — raise these to the
                    # modern depth (25 and 20) once each CSV is complete and
                    # the chart joins the weekly path above.
                    #
                    # Both launched at 10 rows and grew, so the default floor
                    # of 20 would reject every early week — and reject it
                    # SILENTLY, leaving a CSV that looks finished but is
                    # missing years. Verified at source: japan-hot-100's
                    # 2011-04-09 first week and official-uk-songs' 2011-01-29
                    # both serve 10 rows, and the week before each serves that
                    # same first week's content under its own date, which is
                    # the pre-launch clamp the served-week guard catches.
                    # Japan's backfill is COMPLETE, so this is back to its
                    # modern depth and guards the live weekly path properly.
                    'japan-hot-100': 25,
                    # The UK chart's backfill is COMPLETE (811 weeks, 227 of
                    # them at its launch depth of 10), so this is back to its
                    # modern depth of 20 and guards the live weekly path.
                    'official-uk-songs': 20,
                    # Neither of these ever ran shallow: rock-songs served 50
                    # rows in all 895 weeks of its history and gospel-songs 25
                    # in all 1117, measured across the completed CSVs. So these
                    # are modern depths and backfill floors at once.
                    'rock-songs': 50, 'gospel-songs': 25,
                    # Both hard rock charts run 25 rows in every era measured —
                    # albums at 2007, 2010, 2014, 2018, 2022 and its 2007-07-28
                    # launch week, songs at 2020, 2021, 2023, 2025, 2026 — so 25
                    # is modern depth and backfill floor at once. Measure depth
                    # with THIS FILE'S parser, not by counting
                    # 'o-chart-results-list-row' in the raw HTML: that string
                    # appears twice per rank, so a hand probe reports exactly
                    # double and sets the floor at 50, which rejects every week
                    # of both charts.
                    'hard-rock-albums': 25, 'hot-hard-rock-songs': 25,
                    # Adult Alternative's backfill is COMPLETE (1596 weeks), so
                    # the floor of 15 it needed is gone and this is back to its
                    # modern depth. The 15 was a backfill floor only: the chart
                    # serves 20 rows in 1996 and 2000, 30 by 2010 and 40 today,
                    # so its early era sat exactly ON the default floor of 20
                    # and any week served one row short would have been dropped
                    # SILENTLY. Nothing was: the finished CSV runs 20 (538
                    # weeks), 30 (589) and 40 (469) with nothing partial in
                    # between, and every one of the last 200 weeks is 40.
                    'triple-a': 40,
                    # Mainstream Rock needs no backfill floor: it served 40
                    # rows at every era probed, 1981-03-21 through 2026, with
                    # no clamping after launch.
                    'hot-mainstream-rock-tracks': 40,
                    # Latin Pop Airplay's backfill is COMPLETE (1661 weeks), so
                    # the floor of 1 it needed is gone and this is its modern
                    # depth. The 1 was never a depth: the chart serves ONE row
                    # a week at its 1994-10-08 launch, the same shape that
                    # nearly cost Hot Latin Songs its entire 1986, and the
                    # default floor of 20 would have rejected its early era
                    # SILENTLY. Nothing was lost — the finished CSV runs 1 (4
                    # weeks), 15 (72), 20 (165) and 25 (1420) with nothing
                    # partial in between, and it has been 25 since 1999-06-05.
                    'latin-pop-airplay': 25,
                    # Latin Airplay ran 40 rows for its first 348 weeks and 50
                    # since 2001-07-28; 50 is the modern depth and the weekly
                    # path never looks back to the 40-row era.
                    'latin-airplay': 50,
                    # Backfills COMPLETE 2026-08-13, so the floors of 1, 1 and 15
                    # these needed during the backfill are gone and each is back
                    # to its modern depth, which is what guards the weekly path.
                    # Tropical and Regional Mexican both served ONE row a week at
                    # their 1994-10-08 launch, the Latin trap again, and Rap
                    # Airplay launched at EXACTLY 20 — the default floor — so a
                    # week served one row short would have been dropped SILENTLY
                    # and left a CSV that looked finished. Their shallow eras are
                    # already in the CSVs; the weekly path never looks back.
                    'latin-tropical-airplay': 25,
                    'latin-regional-mexican-airplay': 40,
                    'hot-rap-tracks': 25,
                    # The other two launched at or above the default floor of 20
                    # (25 and 40), so neither needed one. Both run deeper today.
                    'latin-rhythm-airplay': 25,
                    'hot-r-and-b-hip-hop-airplay': 50,
                    # Christian grew 30 -> 40 -> 50 over its life and has run
                    # 50 for its last 894 weeks, so 50 guards the weekly path
                    # correctly. Its shallow era is already in the CSV.
                    'christian-songs': 50,
                    # All three run 50 rows today. Country and R&B were 29-100
                    # over their lives and Top Album Sales SHRANK from 100 to
                    # 50, but the weekly path never looks back past the modern
                    # era, so 50 is the right guard for each.
                    'country-songs': 50, 'r-b-hip-hop-songs': 50,
                    'top-album-sales': 50,
                    # Latin's backfill is COMPLETE (2072 weeks), so the floor of
                    # 1 it needed is gone and this is back to its modern depth.
                    # The 1 was never a depth — Hot Latin Songs really does
                    # serve ONE row per week in 1986, and the default floor of
                    # 20 would have rejected its entire first era and left a CSV
                    # that looked finished and was missing years. It has run 50
                    # since 2005, so 50 guards the live weekly path correctly.
                    'latin-songs': 50,
                    # The three airplay charts added 2026-08-12. None needed a
                    # backfill floor — each launched at or above the default 20
                    # — so these are modern depths guarding the weekly path.
                    # Christian Airplay's depth is NOT monotonic — measured
                    # across the finished CSV it runs 40 (2003-06-21, 165
                    # weeks), 30 (2006-08-19, 148), 50 (2009-06-20, 749) and
                    # 40 again from 2023-10-28. So 40 is the modern value and
                    # must not be read as its historical depth; its 30-row era
                    # is already in the CSV and sits above the default floor.
                    'rock-airplay': 50, 'christian-airplay': 40,
                    'gospel-airplay': 30,
                    # Same failure the latin-songs note above describes, and it
                    # already cost this chart six years. Hot Dance Singles Sales
                    # runs 30 rows to 2007-02-24, then 15, then 10 from 2010 to
                    # its final week 2013-11-30 — so the default floor of 20
                    # rejected EVERY week after Feb 2007 as "incomplete" and the
                    # CSV stopped there looking finished. Measured at source, not
                    # inferred. 10 is the true minimum depth; the chart is
                    # discontinued, so this floor guards a backfill only.
                    'hot-dance-singles-sales': 10,
                    # ── Batch added 2026-08-14: genre albums, international,
                    # Hits of the World. Every floor below is the MINIMUM depth
                    # measured across five samples spanning each chart's whole
                    # archive, not its current depth — the two differ on most of
                    # them, and it is the minimum that decides whether a backfill
                    # completes or stops early looking finished.
                    #
                    # r-b-hip-hop-albums is the one that proves the point: it
                    # reproduced the Dance Singles Sales failure on the very
                    # first test scrape, rejecting 1965-01-30 as "10/20 rows"
                    # under the default floor. It runs 10 rows in 1965, 100 in
                    # the 1990s and 50 today, so only 10 admits its full span.
                    'country-albums': 20, 'r-b-hip-hop-albums': 10,
                    'christian-albums': 27, 'gospel-albums': 15,
                    'latin-albums': 50, 'independent-albums': 50,
                    # Canadian Albums' earliest served week returns a single row.
                    # A floor of 1 would admit anything, so this keeps a real
                    # guard and the backfill starts from the first week that
                    # actually carries a ranking — see the CANADIAN_ALBUMS_START
                    # note in the backfill runner.
                    'canadian-albums': 10,
                    # Vinyl Albums, added 2026-08-15. Runs 15 rows from its
                    # 2011-01-22 launch through late 2014 and 25 from 2015 on —
                    # measured at source across eleven samples, not inferred.
                    # The default floor of 20 rejected all four early years as
                    # "15/20 rows" on the first backfill attempt, which is the
                    # Dance Singles Sales failure again: the CSV would have
                    # started at 2015 and looked complete. 15 is the true
                    # minimum, so it is the floor.
                    'vinyl-albums': 15,
                    # Hot Dance/Pop Songs, added 2026-08-19. Runs 15 rows in
                    # every week of its short life (launched 2025-01-18), so
                    # the default floor of 20 rejects the ENTIRE chart as
                    # "15/20 rows" — Vinyl Albums and Dance Singles Sales
                    # again, except here it leaves no CSV at all rather than a
                    # truncated one that looks finished. 15 is modern depth and
                    # backfill floor at once; it has never run deeper.
                    'hot-dance-pop-songs': 15,
                    # International editions, all flat-depth since launch.
                    'billboard-argentina-hot-100': 25, 'billboard-brasil-hot-100': 25,
                    'billboard-italy-hot-100': 25, 'billboard-philippines-hot-100': 25,
                    'china-tme-uni-songs': 50,
                    # All 38 Hits of the World charts launched together on
                    # 2022-02-19 at 25 rows and have never varied, so they share
                    # one floor rather than getting 38 identical lines.
                    **{f'{c}-songs-hotw': 25 for c in (
                        'australia', 'austria', 'belgium', 'bolivia', 'chile',
                        'croatia', 'czech-republic', 'denmark', 'ecuador',
                        'finland', 'france', 'germany', 'greece', 'hong-kong',
                        'hungary',
                        'iceland', 'india', 'indonesia', 'ireland', 'luxembourg',
                        'malaysia', 'mexico', 'netherlands', 'new-zealand',
                        'norway', 'peru', 'poland', 'portugal', 'romania',
                        'singapore', 'slovakia', 'south-africa', 'spain',
                        'sweden', 'switzerland', 'taiwan', 'thailand', 'turkey',
                        'u-k')},
                    # ── Batch added 2026-08-17 ─────────────────────────
                    # MODERN DEPTHS, raised from the backfill floors now that
                    # every CSV is complete — this is what guards the weekly
                    # path, which never looks back far enough to see the
                    # shallow eras the backfill needed. Each is the MINIMUM row
                    # count over that chart's last 52 weeks, taken from the
                    # finished CSV; all 57 hold one constant depth across that
                    # window, so none of these is a compromise between eras.
                    #
                    # The backfill floors they replace were much lower and were
                    # right for their purpose: four charts launch at ONE row,
                    # and four more (bluegrass, kids, cast, blues) dip in
                    # 2021-2025 and recover by 2026. Re-deriving a backfill
                    # needs measure_depth_floor.py again, NOT these numbers.
                    'alternative-albums': 25,
                    'alternative-streaming-songs': 25,
                    'americana-folk-albums': 25,
                    'australian-albums': 10,
                    'billboard-italy-albums-top-100': 25,
                    'billboard-philippines-top-philippine-songs': 25,
                    'billboard-u-s-afrobeats-songs': 50,
                    'bluegrass-albums': 15,
                    'blues-albums': 15,
                    'cast-albums': 15,
                    'christian-streaming-songs': 25,
                    'classical-albums': 25,
                    'classical-crossover-albums': 15,
                    'comedy-albums': 10,
                    'contemporary-jazz': 15,
                    'country-streaming-songs': 25,
                    'dance-electronic-albums': 25,
                    'dance-electronic-streaming-songs': 15,
                    'emerging-artists': 50,
                    'gospel-streaming-songs': 15,
                    'greece-albums': 10,
                    'hard-rock-streaming-songs': 25,
                    'hot-alternative-songs': 25,
                    'hot-christian-adult-contemporary': 30,
                    'hot-rock-songs': 25,
                    'indie-store-album-sales': 25,
                    'jazz-albums': 25,
                    'jazz-songs': 30,
                    'kids-albums': 25,
                    'latin-pop-albums': 25,
                    'latin-rhythm-albums': 25,
                    'latin-streaming-songs': 25,
                    'lyricfind-global': 25,
                    'lyricfind-us': 25,
                    'new-age-albums': 15,
                    'official-uk-albums': 20,
                    'r-and-b-albums': 25,
                    'r-and-b-hip-hop-streaming-songs': 25,
                    'r-and-b-songs': 25,
                    'r-and-b-streaming-songs': 15,
                    'rap-albums': 25,
                    'rap-song': 25,
                    'rap-streaming-songs': 15,
                    'reggae-albums': 10,
                    'regional-mexican-albums': 25,
                    'rock-albums': 25,
                    'rock-streaming-songs': 25,
                    'soundtracks': 25,
                    'the-arabic-hot-100': 25,
                    'top-arabic-artist-100': 25,
                    'top-rock-alternative-albums': 50,
                    'top-streaming-albums': 50,
                    'traditional-classic-albums': 15,
                    'traditional-jazz-albums': 15,
                    'tropical-albums': 25,
                    'world-albums': 25,
                    }.get(chart_name, 20)
        if min_rows is not None:
            expected = min_rows
        if len(entries) < expected:
            print(f"✗ Incomplete chart: {len(entries)}/{expected} rows — skipping (will retry next run)")
            time.sleep(1)
            return None

        print(f"✓ ({len(entries)} songs)")
        time.sleep(1)  # Be respectful
        return entries

    except requests.RequestException as e:
        print(f"✗ Network error: {e}")
        return None
    except Exception as e:
        # Not a network issue — likely a markup/selector change. Logged distinctly so a
        # code/parse failure isn't silently mistaken for a transient network skip.
        print(f"✗ PARSE/CODE error (check selectors): {e}")
        return None

def update_chart_data(chart_name, csv_filename, weeks_to_fetch=15):
    """Update chart data by scraping Billboard.com"""
    print(f"\n{'='*60}")
    print(f"📊 Updating {chart_name.upper()} from Billboard.com")
    print(f"{'='*60}")

    csv_path = Path(csv_filename)

    # Get latest date in CSV
    latest_date = None
    existing_dates = set()
    if csv_path.exists():
        df = pd.read_csv(csv_path, low_memory=False)
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        latest_date = df['Date'].max()
        existing_dates = set(df['Date'].dropna().dt.strftime('%Y-%m-%d'))
        if pd.isna(latest_date):
            latest_date = None  # corrupt/empty Date column — fall back to the window below

    # Charts are dated the upcoming Saturday and published mid-week, so scan up to
    # 6 days ahead of now; an unpublished future week scrapes 0 rows and is skipped.
    end_date = datetime.now() + timedelta(days=6)

    # Calculate the window to scan. We look back ~1 year so any recently-missed week gets
    # backfilled (a transient failure would otherwise leave a permanent hole once the
    # latest date advances past it); weeks already present are filtered out below.
    if latest_date is not None:
        print(f"\n📅 Latest data in CSV: {latest_date.strftime('%Y-%m-%d')}")
        start_date = latest_date - timedelta(weeks=52)
    else:
        start_date = end_date - timedelta(weeks=weeks_to_fetch)

    # Generate Saturdays in range, skipping weeks we already have
    saturdays = []
    current = start_date
    days_ahead = 5 - current.weekday()  # 5 = Saturday
    if days_ahead < 0:
        days_ahead += 7
    current = current + timedelta(days=days_ahead)

    while current <= end_date:
        if current.strftime('%Y-%m-%d') not in existing_dates:
            saturdays.append(current)
        current += timedelta(weeks=1)

    if not saturdays:
        print("\n✓ Data is already up to date!")
        return True

    print(f"\n🔄 Fetching {len(saturdays)} week(s) of data...")
    print(f"   From: {saturdays[0].strftime('%Y-%m-%d')}")
    print(f"   To:   {saturdays[-1].strftime('%Y-%m-%d')}")

    # Scrape each week
    all_new_data = []
    for saturday in saturdays:
        date_str = saturday.strftime('%Y-%m-%d')
        entries = scrape_billboard_chart(chart_name, date_str)

        if entries:
            all_new_data.extend(entries)
        else:
            print(f"  ⚠️  Skipping {date_str} due to errors")

    if not all_new_data:
        print("\n❌ No new data fetched")
        return False

    # Convert to DataFrame
    new_df = pd.DataFrame(all_new_data)
    new_df['Date'] = pd.to_datetime(new_df['Date'])

    # Merge with existing data
    if csv_path.exists():
        print(f"\n📂 Loading existing data from {csv_path}...")
        existing_df = pd.read_csv(csv_path, low_memory=False)
        existing_df['Date'] = pd.to_datetime(existing_df['Date'], errors='coerce')

        combined_df = pd.concat([existing_df, new_df], ignore_index=True)
        combined_df = combined_df.drop_duplicates(subset=['Date', 'Rank'], keep='last')
        combined_df = combined_df.sort_values(['Date', 'Rank'])
    else:
        combined_df = new_df.sort_values(['Date', 'Rank'])

    # Save to CSV
    combined_df.to_csv(csv_path, index=False)

    size_mb = csv_path.stat().st_size / (1024 * 1024)
    print(f"\n✅ Updated {csv_path.name}")
    print(f"   Size: {size_mb:.1f} MB")
    print(f"   Records: {len(combined_df):,}")
    print(f"   Date range: {combined_df['Date'].min().strftime('%Y-%m-%d')} to {combined_df['Date'].max().strftime('%Y-%m-%d')}")

    return True

def main():
    """Main function"""
    print("\n" + "="*60)
    print("🎵 Fast Billboard Scraper")
    print("="*60)
    print("\nDirect web scraping from Billboard.com")
    print("(Used when billboard.py library fails)")

    # Update Hot 100
    success_hot100 = update_chart_data('hot-100', 'data/hot100.csv', weeks_to_fetch=15)

    # Update Billboard 200
    success_bb200 = update_chart_data('billboard-200', 'data/billboard200.csv', weeks_to_fetch=15)

    # Update global charts (exist since Sept 2020)
    update_chart_data('billboard-global-200', 'data/global200.csv', weeks_to_fetch=15)
    update_chart_data('billboard-global-excl-us', 'data/globalexus.csv', weeks_to_fetch=15)

    # Update component charts (public site shows top 25 since Sept 2023)
    update_chart_data('radio-songs', 'data/radio.csv', weeks_to_fetch=15)
    update_chart_data('digital-song-sales', 'data/digital_songs.csv', weeks_to_fetch=15)
    update_chart_data('streaming-songs', 'data/streaming_songs.csv', weeks_to_fetch=15)
    update_chart_data('artist-100', 'data/artist100.csv', weeks_to_fetch=15)
    update_chart_data('pop-songs', 'data/pop_airplay.csv', weeks_to_fetch=15)

    # Genre/format airplay charts. Full histories were backfilled separately;
    # these keep them current. The completeness floor for these slugs is 10
    # rows, not their modern depth — they ran shallower in early decades.
    update_chart_data('adult-contemporary', 'data/adult_contemporary.csv', weeks_to_fetch=15)
    update_chart_data('adult-pop-songs', 'data/adult_pop_airplay.csv', weeks_to_fetch=15)
    update_chart_data('rhythmic-40', 'data/rhythmic_airplay.csv', weeks_to_fetch=15)
    update_chart_data('country-airplay', 'data/country_airplay.csv', weeks_to_fetch=15)
    update_chart_data('alternative-airplay', 'data/alternative_airplay.csv', weeks_to_fetch=15)
    update_chart_data('mainstream-r-and-b-hip-hop', 'data/rnb_hiphop_airplay.csv', weeks_to_fetch=15)
    update_chart_data('hot-adult-r-and-b-airplay', 'data/adult_rnb_airplay.csv', weeks_to_fetch=15)
    update_chart_data('hot-dance-airplay', 'data/dance_airplay.csv', weeks_to_fetch=15)
    update_chart_data('bubbling-under-hot-100-singles', 'data/bubbling_under.csv', weeks_to_fetch=15)
    update_chart_data('canadian-hot-100', 'data/canadian_hot100.csv', weeks_to_fetch=15)
    update_chart_data('dance-electronic-songs', 'data/dance_electronic_songs.csv', weeks_to_fetch=15)
    update_chart_data('japan-hot-100', 'data/japan_hot100.csv', weeks_to_fetch=15)
    update_chart_data('official-uk-songs', 'data/uk_songs.csv', weeks_to_fetch=15)
    update_chart_data('rock-songs', 'data/rock_songs.csv', weeks_to_fetch=15)
    update_chart_data('gospel-songs', 'data/gospel_songs.csv', weeks_to_fetch=15)
    update_chart_data('christian-songs', 'data/christian_songs.csv', weeks_to_fetch=15)
    update_chart_data('country-songs', 'data/country_songs.csv', weeks_to_fetch=15)
    update_chart_data('r-b-hip-hop-songs', 'data/rnb_hiphop_songs.csv', weeks_to_fetch=15)
    update_chart_data('top-album-sales', 'data/top_album_sales.csv', weeks_to_fetch=15)
    update_chart_data('latin-songs', 'data/latin_songs.csv', weeks_to_fetch=15)
    update_chart_data('hot-mainstream-rock-tracks', 'data/mainstream_rock.csv', weeks_to_fetch=15)
    update_chart_data('triple-a', 'data/adult_alternative.csv', weeks_to_fetch=15)
    update_chart_data('rock-airplay', 'data/rock_airplay.csv', weeks_to_fetch=15)
    update_chart_data('christian-airplay', 'data/christian_airplay.csv', weeks_to_fetch=15)
    update_chart_data('gospel-airplay', 'data/gospel_airplay.csv', weeks_to_fetch=15)
    update_chart_data('latin-pop-airplay', 'data/latin_pop_airplay.csv', weeks_to_fetch=15)
    update_chart_data('latin-airplay', 'data/latin_airplay.csv', weeks_to_fetch=15)

    # ── Batch added 2026-08-14 ────────────────────────────────────────────────
    # All 50 are live charts, so every one needs a weekly line or its CSV freezes
    # at whatever the backfill left and quietly rots. The genre album charts and
    # international editions are spelled out; Hits of the World is a loop because
    # 38 identical lines differing only in a country name is worse to read and
    # worse to keep in step with HOTW_COUNTRIES in app.py.
    for _slug, _csv in (('country-albums', 'country_albums'),
                        ('r-b-hip-hop-albums', 'rnb_hiphop_albums'),
                        ('christian-albums', 'christian_albums'),
                        ('gospel-albums', 'gospel_albums'),
                        ('latin-albums', 'latin_albums'),
                        ('canadian-albums', 'canadian_albums'),
                        ('independent-albums', 'independent_albums'),
                        ('billboard-argentina-hot-100', 'argentina_hot100'),
                        ('billboard-brasil-hot-100', 'brasil_hot100'),
                        ('billboard-italy-hot-100', 'italy_hot100'),
                        ('billboard-philippines-hot-100', 'philippines_hot100'),
                        ('china-tme-uni-songs', 'china_tme'),
                        ('hard-rock-albums', 'hard_rock_albums'),
                        ('hot-hard-rock-songs', 'hard_rock_songs')):
        update_chart_data(_slug, f'data/{_csv}.csv', weeks_to_fetch=15)

    for _country in ('australia', 'austria', 'belgium', 'bolivia', 'chile',
                     'croatia', 'czech-republic', 'denmark', 'ecuador',
                     'finland', 'france', 'germany', 'greece', 'hong-kong',
                     'hungary',
                     'iceland', 'india', 'indonesia', 'ireland', 'luxembourg',
                     'malaysia', 'mexico', 'netherlands', 'new-zealand',
                     'norway', 'peru', 'poland', 'portugal', 'romania',
                     'singapore', 'slovakia', 'south-africa', 'spain', 'sweden',
                     'switzerland', 'taiwan', 'thailand', 'turkey', 'u-k'):
        update_chart_data(f'{_country}-songs-hotw',
                          f"data/{_country.replace('-', '_')}_hotw.csv",
                          weeks_to_fetch=15)

    # ── Batch added 2026-08-17 ────────────────────────────────────────────────
    # The other 56 of the batch. Same rule as the 2026-08-14 block above: a
    # chart with no weekly line freezes at whatever its backfill left, and the
    # freeze is silent — the CSV keeps loading and the page keeps rendering,
    # just never past that date. Hong Kong is not here because it joined
    # HOTW_COUNTRIES and the loop above covers it.
    for _slug, _csv in (('alternative-albums', 'alternative_albums'),
                        ('alternative-streaming-songs', 'alternative_streaming'),
                        ('americana-folk-albums', 'americana_folk_albums'),
                        ('australian-albums', 'australia_albums'),
                        ('billboard-italy-albums-top-100', 'italy_albums'),
                        ('billboard-philippines-top-philippine-songs', 'philippines_top_songs'),
                        ('billboard-u-s-afrobeats-songs', 'afrobeats_songs'),
                        ('bluegrass-albums', 'bluegrass_albums'),
                        ('blues-albums', 'blues_albums'),
                        ('cast-albums', 'cast_albums'),
                        ('christian-streaming-songs', 'christian_streaming'),
                        ('classical-albums', 'classical_albums'),
                        ('classical-crossover-albums', 'classical_crossover_albums'),
                        ('comedy-albums', 'comedy_albums'),
                        ('contemporary-jazz', 'contemporary_jazz_albums'),
                        ('country-streaming-songs', 'country_streaming'),
                        ('dance-electronic-albums', 'dance_albums'),
                        ('dance-electronic-streaming-songs', 'dance_streaming'),
                        ('emerging-artists', 'emerging_artists'),
                        ('gospel-streaming-songs', 'gospel_streaming'),
                        ('greece-albums', 'greece_albums'),
                        ('hard-rock-streaming-songs', 'hard_rock_streaming'),
                        ('hot-alternative-songs', 'hot_alternative_songs'),
                        ('hot-christian-adult-contemporary', 'christian_ac_airplay'),
                        ('hot-rock-songs', 'hot_rock_songs'),
                        ('indie-store-album-sales', 'indie_store_album_sales'),
                        ('jazz-albums', 'jazz_albums'),
                        ('jazz-songs', 'smooth_jazz_airplay'),
                        ('kids-albums', 'kid_albums'),
                        ('latin-pop-albums', 'latin_pop_albums'),
                        ('latin-rhythm-albums', 'latin_rhythm_albums'),
                        ('latin-streaming-songs', 'latin_streaming'),
                        ('lyricfind-global', 'lyricfind_global'),
                        ('lyricfind-us', 'lyricfind_us'),
                        ('new-age-albums', 'new_age_albums'),
                        ('official-uk-albums', 'uk_albums'),
                        ('r-and-b-albums', 'rnb_albums'),
                        ('r-and-b-hip-hop-streaming-songs', 'rnb_hiphop_streaming'),
                        ('r-and-b-songs', 'hot_rnb_songs'),
                        ('r-and-b-streaming-songs', 'rnb_streaming'),
                        ('rap-albums', 'rap_albums'),
                        ('rap-song', 'rap_songs'),
                        ('rap-streaming-songs', 'rap_streaming'),
                        ('reggae-albums', 'reggae_albums'),
                        ('regional-mexican-albums', 'regional_mexican_albums'),
                        ('rock-albums', 'rock_albums'),
                        ('rock-streaming-songs', 'rock_streaming'),
                        ('soundtracks', 'soundtracks'),
                        ('the-arabic-hot-100', 'arabic_hot100'),
                        ('top-arabic-artist-100', 'arabic_artist100'),
                        ('top-rock-alternative-albums', 'rock_alternative_albums'),
                        ('top-streaming-albums', 'top_streaming_albums'),
                        ('traditional-classic-albums', 'traditional_classical_albums'),
                        ('traditional-jazz-albums', 'traditional_jazz_albums'),
                        ('tropical-albums', 'tropical_albums'),
                        ('world-albums', 'world_albums')):
        update_chart_data(_slug, f'data/{_csv}.csv', weeks_to_fetch=15)

    print("\n" + "="*60)
    if success_hot100 and success_bb200:
        print("✅ Update complete!")
    elif success_hot100 or success_bb200:
        print("⚠️  Partial update completed")
    else:
        print("❌ Update failed")
    print("="*60 + "\n")

if __name__ == '__main__':
    main()
