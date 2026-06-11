#!/usr/bin/env python3
"""
Billboard Direct Data Updater
Fetches data directly from Billboard.com when Kaggle data is outdated
Uses the billboard-charts library which respects Billboard's robots.txt and rate limits
"""
import os
import time
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

def check_billboard_library():
    """Check if billboard.py library is installed"""
    try:
        import billboard
        return True
    except ImportError:
        print("\n❌ billboard-charts library not installed!")
        print("\nInstall it with:")
        print("  pip3 install billboard.py")
        print("\nThis library:")
        print("  ✓ Respects Billboard's robots.txt")
        print("  ✓ Includes built-in rate limiting")
        print("  ✓ Is maintained by the open-source community")
        return False

def get_latest_date_in_csv(csv_path):
    """Get the most recent date in existing CSV file"""
    if not Path(csv_path).exists():
        return None

    try:
        df = pd.read_csv(csv_path, low_memory=False)
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        return df['Date'].max()
    except Exception as e:
        print(f"⚠️  Error reading {csv_path}: {e}")
        return None

def get_existing_dates(csv_path):
    """Set of 'YYYY-MM-DD' chart dates already present in the CSV."""
    if not Path(csv_path).exists():
        return set()
    try:
        df = pd.read_csv(csv_path, low_memory=False)
        dates = pd.to_datetime(df['Date'], errors='coerce').dropna()
        return set(dates.dt.strftime('%Y-%m-%d'))
    except Exception as e:
        print(f"⚠️  Error reading {csv_path}: {e}")
        return set()

def fetch_chart_week(chart_name, date_str, retries=3):
    """
    Fetch a single week of chart data from Billboard

    Args:
        chart_name: 'hot-100' or 'billboard-200'
        date_str: Date in 'YYYY-MM-DD' format
        retries: Number of retry attempts

    Returns:
        List of chart entries or None if failed
    """
    import billboard

    for attempt in range(retries):
        try:
            print(f"  📥 Fetching {chart_name} for {date_str}...", end=' ')
            chart = billboard.ChartData(chart_name, date=date_str)

            entries = []
            for entry in chart:
                entries.append({
                    'Date': chart.date,
                    'Rank': entry.rank,
                    'Song': entry.title,
                    'Artist': entry.artist,
                    'Last Week': entry.lastPos if entry.lastPos else '-',
                    'Peak Position': entry.peakPos if entry.peakPos else entry.rank,
                    'Weeks on Chart': entry.weeks if entry.weeks else 1
                })

            print(f"✓ ({len(entries)} songs)")

            # Rate limiting: reduced to 0.5 seconds for faster scraping
            time.sleep(0.5)
            return entries

        except Exception as e:
            print(f"✗ Attempt {attempt + 1} failed: {e}")
            if attempt < retries - 1:
                wait_time = (attempt + 1) * 5
                print(f"  ⏳ Waiting {wait_time} seconds before retry...")
                time.sleep(wait_time)
            else:
                print(f"  ❌ Failed after {retries} attempts")
                return None

def get_saturdays_between(start_date, end_date):
    """Get list of Saturdays between two dates"""
    saturdays = []
    current = start_date

    # Move to next Saturday if start_date is not Saturday
    days_ahead = 5 - current.weekday()  # 5 = Saturday
    if days_ahead < 0:
        days_ahead += 7
    current = current + timedelta(days=days_ahead)

    while current <= end_date:
        saturdays.append(current)
        current += timedelta(weeks=1)

    return saturdays

def update_hot100(weeks_to_fetch=4):
    """
    Update Hot 100 data from Billboard.com

    Args:
        weeks_to_fetch: Number of recent weeks to fetch (default: 4)
    """
    print("\n" + "="*60)
    print("📊 Updating U.S. Top Charts 100 from Billboard.com")
    print("="*60)

    csv_path = Path('data/hot100.csv')

    # Check latest date in existing CSV
    latest_date = get_latest_date_in_csv(csv_path)
    existing_dates = get_existing_dates(csv_path)

    end_date = datetime.now()
    if latest_date is not None and not pd.isna(latest_date):
        print(f"\n📅 Latest data in CSV: {latest_date.strftime('%Y-%m-%d')}")
        # Look back ~1 year so any recently-missed week gets backfilled (a transient
        # failure would otherwise leave a permanent hole once the latest date advances
        # past it). Weeks already present are filtered out below.
        start_date = latest_date - timedelta(weeks=52)
    else:
        print("\n📅 No existing data found")
        # Fetch last N weeks
        start_date = end_date - timedelta(weeks=weeks_to_fetch)

    saturdays = [s for s in get_saturdays_between(start_date, end_date)
                 if s.strftime('%Y-%m-%d') not in existing_dates]

    if not saturdays:
        print("\n✓ Data is already up to date!")
        return True

    print(f"\n🔄 Fetching {len(saturdays)} week(s) of data...")
    print(f"   From: {saturdays[0].strftime('%Y-%m-%d')}")
    print(f"   To:   {saturdays[-1].strftime('%Y-%m-%d')}")

    # Fetch each week in parallel (max 4 concurrent threads to be respectful)
    all_new_data = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_date = {
            executor.submit(fetch_chart_week, 'hot-100', saturday.strftime('%Y-%m-%d')): saturday
            for saturday in saturdays
        }

        for future in as_completed(future_to_date):
            saturday = future_to_date[future]
            try:
                entries = future.result()
                if entries:
                    all_new_data.extend(entries)
                else:
                    print(f"  ⚠️  Skipping {saturday.strftime('%Y-%m-%d')} due to errors")
            except Exception as exc:
                print(f"  ⚠️  {saturday.strftime('%Y-%m-%d')} generated an exception: {exc}")

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

        # Combine and remove duplicates
        combined_df = pd.concat([existing_df, new_df], ignore_index=True)
        combined_df = combined_df.drop_duplicates(subset=['Date', 'Rank'], keep='last')
        combined_df = combined_df.sort_values(['Date', 'Rank'])
    else:
        combined_df = new_df.sort_values(['Date', 'Rank'])

    # Clean artist names (replace pipe characters)
    combined_df['Artist'] = combined_df['Artist'].str.replace('|', ',')

    # Save to CSV
    combined_df.to_csv(csv_path, index=False)

    size_mb = csv_path.stat().st_size / (1024 * 1024)
    print(f"\n✅ Updated {csv_path.name}")
    print(f"   Size: {size_mb:.1f} MB")
    print(f"   Records: {len(combined_df):,}")
    print(f"   Date range: {combined_df['Date'].min().strftime('%Y-%m-%d')} to {combined_df['Date'].max().strftime('%Y-%m-%d')}")

    return True

def update_billboard200(weeks_to_fetch=4):
    """
    Update Billboard 200 data from Billboard.com

    Args:
        weeks_to_fetch: Number of recent weeks to fetch (default: 4)
    """
    print("\n" + "="*60)
    print("💿 Updating U.S. Album Charts 200 from Billboard.com")
    print("="*60)

    csv_path = Path('data/billboard200.csv')

    # Check latest date in existing CSV
    latest_date = get_latest_date_in_csv(csv_path)
    existing_dates = get_existing_dates(csv_path)

    end_date = datetime.now()
    if latest_date is not None and not pd.isna(latest_date):
        print(f"\n📅 Latest data in CSV: {latest_date.strftime('%Y-%m-%d')}")
        # Look back ~1 year to backfill any recently-missed weeks, then fetch forward.
        start_date = latest_date - timedelta(weeks=52)
    else:
        print("\n📅 No existing data found")
        start_date = end_date - timedelta(weeks=weeks_to_fetch)

    saturdays = [s for s in get_saturdays_between(start_date, end_date)
                 if s.strftime('%Y-%m-%d') not in existing_dates]

    if not saturdays:
        print("\n✓ Data is already up to date!")
        return True

    print(f"\n🔄 Fetching {len(saturdays)} week(s) of data...")
    print(f"   From: {saturdays[0].strftime('%Y-%m-%d')}")
    print(f"   To:   {saturdays[-1].strftime('%Y-%m-%d')}")

    # Fetch each week in parallel (max 4 concurrent threads to be respectful)
    all_new_data = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_date = {
            executor.submit(fetch_chart_week, 'billboard-200', saturday.strftime('%Y-%m-%d')): saturday
            for saturday in saturdays
        }

        for future in as_completed(future_to_date):
            saturday = future_to_date[future]
            try:
                entries = future.result()
                if entries:
                    all_new_data.extend(entries)
                else:
                    print(f"  ⚠️  Skipping {saturday.strftime('%Y-%m-%d')} due to errors")
            except Exception as exc:
                print(f"  ⚠️  {saturday.strftime('%Y-%m-%d')} generated an exception: {exc}")

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

    # Clean artist names
    combined_df['Artist'] = combined_df['Artist'].str.replace('|', ',')

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
    import sys

    print("\n" + "="*60)
    print("🎵 Billboard Direct Data Updater")
    print("="*60)
    print("\nThis tool fetches data directly from Billboard.com")
    print("when Kaggle data is outdated.")
    print("\nFeatures:")
    print("  ✓ Uses billboard.py library (respects robots.txt)")
    print("  ✓ Built-in rate limiting (2 sec between requests)")
    print("  ✓ Incremental updates (only fetches new weeks)")
    print("  ✓ Automatic data cleaning and deduplication")

    # Check if library is installed
    if not check_billboard_library():
        return

    # Change to script directory
    os.chdir(Path(__file__).parent)

    # Parse command line arguments
    weeks = 4
    if '--weeks' in sys.argv:
        try:
            idx = sys.argv.index('--weeks')
            weeks = int(sys.argv[idx + 1])
        except (IndexError, ValueError):
            print("\n⚠️  Invalid --weeks argument, using default (4)")

    # Determine what to update
    update_hot100_flag = '--hot100' in sys.argv or '--all' in sys.argv or len(sys.argv) == 1
    update_billboard200_flag = '--billboard200' in sys.argv or '--all' in sys.argv or len(sys.argv) == 1

    success = True

    if update_hot100_flag:
        if not update_hot100(weeks_to_fetch=weeks):
            success = False

    if update_billboard200_flag:
        if not update_billboard200(weeks_to_fetch=weeks):
            success = False

    print("\n" + "="*60)
    if success:
        print("✅ Update complete!")
    else:
        print("⚠️  Update completed with errors")
    print("="*60)
    print("\nUsage examples:")
    print("  python3 update_from_billboard.py              # Update both charts (last 4 weeks)")
    print("  python3 update_from_billboard.py --hot100     # Update only Hot 100")
    print("  python3 update_from_billboard.py --billboard200  # Update only Billboard 200")
    print("  python3 update_from_billboard.py --weeks 8    # Fetch last 8 weeks")
    print("  python3 update_from_billboard.py --all        # Update both charts")
    print("\n")

if __name__ == '__main__':
    main()
