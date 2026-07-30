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
import time
import json

def scrape_billboard_chart(chart_name='hot-100', date=None):
    """
    Scrape a Billboard chart for a specific date

    Args:
        chart_name: 'hot-100' or 'billboard-200'
        date: Date string 'YYYY-MM-DD' or None for latest

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

        # Find chart date from page
        chart_date_elem = soup.find('p', class_='c-tagline')
        if chart_date_elem and 'dated' in chart_date_elem.text.lower():
            # Extract date from text like "Week of November 1, 2025"
            date_text = chart_date_elem.text
            # Use provided date or extract from page
            chart_date = date if date else datetime.now().strftime('%Y-%m-%d')
        else:
            chart_date = date if date else datetime.now().strftime('%Y-%m-%d')

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
                    'artist-100': 100, 'pop-songs': 40}.get(chart_name, 20)
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
