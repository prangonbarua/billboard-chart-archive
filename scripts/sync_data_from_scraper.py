#!/usr/bin/env python3
"""
Sync Billboard data from the scraper project to the website
"""
import os
import shutil
from pathlib import Path
import pandas as pd

# Paths
SCRAPER_DIR = Path.home() / 'Billboard-Streaming-Songs-Datacollector'
WEBSITE_DIR = Path.home() / 'Billboard-Hot-100-Website'

SCRAPER_HOT_100 = SCRAPER_DIR / 'data' / 'hot_100.csv'
SCRAPER_BILLBOARD_200 = SCRAPER_DIR / 'data' / 'billboard_200.csv'

WEBSITE_HOT_100 = WEBSITE_DIR / 'data/hot100.csv'
WEBSITE_BILLBOARD_200 = WEBSITE_DIR / 'data/billboard200.csv'

def convert_hot_100_format(scraper_file, website_file):
    """Convert Hot 100 data from scraper format and merge with existing website data"""
    print(f"Converting and merging Hot 100 data...")

    # Read scraper data
    df_new = pd.read_csv(scraper_file)

    # Scraper format: date, rank, song, artist, last_week, peak_position, weeks_on_chart
    # Website format: Date, Song, Artist, Rank, Last Week, Peak Position, Weeks On Chart

    # Rename columns to match website format
    df_new = df_new.rename(columns={
        'date': 'Date',
        'song': 'Song',
        'artist': 'Artist',
        'rank': 'Rank',
        'last_week': 'Last Week',
        'peak_position': 'Peak Position',
        'weeks_on_chart': 'Weeks on Chart'
    })

    # Reorder columns
    columns_order = ['Date', 'Song', 'Artist', 'Rank', 'Last Week', 'Peak Position', 'Weeks on Chart']
    df_new = df_new[columns_order]

    # Load existing website data if it exists
    if website_file.exists():
        print(f"  Loading existing data from {website_file.name}...")
        df_existing = pd.read_csv(website_file, low_memory=False)
        print(f"  Found {len(df_existing)} existing entries")

        # Merge, then normalize the Date to a single canonical form BEFORE dedup, so the
        # same week stored in different textual forms collapses to one key.
        df_combined = pd.concat([df_existing, df_new], ignore_index=True)
        df_combined['Date'] = pd.to_datetime(df_combined['Date'], errors='coerce').dt.strftime('%Y-%m-%d')

        # One row per chart position: dedup on (Date, Rank) so a corrected Song/Artist
        # string on an existing slot replaces the old row instead of duplicating it.
        df_combined = df_combined.drop_duplicates(
            subset=['Date', 'Rank'],
            keep='last'  # Keep the newer entry
        )

        # Sort by date (canonical YYYY-MM-DD sorts chronologically)
        df_combined = df_combined.sort_values(['Date', 'Rank'])

        print(f"  Added {len(df_new)} new entries")
        print(f"  Total after deduplication: {len(df_combined)} entries")

        df_website = df_combined
    else:
        df_website = df_new
        print(f"  No existing data found, using {len(df_new)} new entries")

    # Save to website location
    df_website.to_csv(website_file, index=False)
    print(f"  Saved {len(df_website)} total Hot 100 entries")

def convert_billboard_200_format(scraper_file, website_file):
    """Convert Billboard 200 data from scraper format and merge with existing website data"""
    print(f"Converting and merging Billboard 200 data...")

    # Read scraper data
    df_new = pd.read_csv(scraper_file)

    # Scraper format: date, rank, album, artist, last_week, peak_position, weeks_on_chart
    # Website format: Date, Song, Artist, Rank, Last Week, Peak Position, Weeks On Chart
    # Note: Website uses 'Song' column for album names in Billboard 200

    # Rename columns to match website format
    df_new = df_new.rename(columns={
        'date': 'Date',
        'album': 'Song',  # Website uses 'Song' column for albums
        'artist': 'Artist',
        'rank': 'Rank',
        'last_week': 'Last Week',
        'peak_position': 'Peak Position',
        'weeks_on_chart': 'Weeks on Chart'
    })

    # Reorder columns
    columns_order = ['Date', 'Song', 'Artist', 'Rank', 'Last Week', 'Peak Position', 'Weeks on Chart']
    df_new = df_new[columns_order]

    # Load existing website data if it exists
    if website_file.exists():
        print(f"  Loading existing data from {website_file.name}...")
        df_existing = pd.read_csv(website_file, low_memory=False)
        print(f"  Found {len(df_existing)} existing entries")

        # Merge, then normalize the Date to a single canonical form BEFORE dedup, so the
        # same week stored in different textual forms collapses to one key.
        df_combined = pd.concat([df_existing, df_new], ignore_index=True)
        df_combined['Date'] = pd.to_datetime(df_combined['Date'], errors='coerce').dt.strftime('%Y-%m-%d')

        # One row per chart position: dedup on (Date, Rank) so a corrected Album/Artist
        # string on an existing slot replaces the old row instead of duplicating it.
        df_combined = df_combined.drop_duplicates(
            subset=['Date', 'Rank'],
            keep='last'  # Keep the newer entry
        )

        # Sort by date (canonical YYYY-MM-DD sorts chronologically)
        df_combined = df_combined.sort_values(['Date', 'Rank'])

        print(f"  Added {len(df_new)} new entries")
        print(f"  Total after deduplication: {len(df_combined)} entries")

        df_website = df_combined
    else:
        df_website = df_new
        print(f"  No existing data found, using {len(df_new)} new entries")

    # Save to website location
    df_website.to_csv(website_file, index=False)
    print(f"  Saved {len(df_website)} total Billboard 200 entries")

def main():
    print("=" * 60)
    print("Syncing Billboard Data from Scraper to Website")
    print("=" * 60)
    print()

    # Check if scraper data exists
    if not SCRAPER_HOT_100.exists():
        print(f"Error: Scraper Hot 100 data not found at {SCRAPER_HOT_100}")
        print("Run the scraper first: cd ~/Billboard-Streaming-Songs-Datacollector && python scraper.py")
        return

    if not SCRAPER_BILLBOARD_200.exists():
        print(f"Warning: Scraper Billboard 200 data not found at {SCRAPER_BILLBOARD_200}")

    # Backup existing website data
    if WEBSITE_HOT_100.exists():
        backup_file = WEBSITE_DIR / 'hot100_backup.csv'
        shutil.copy(WEBSITE_HOT_100, backup_file)
        print(f"Backed up existing Hot 100 data to {backup_file.name}")

    if WEBSITE_BILLBOARD_200.exists():
        backup_file = WEBSITE_DIR / 'billboard200_backup.csv'
        shutil.copy(WEBSITE_BILLBOARD_200, backup_file)
        print(f"Backed up existing Billboard 200 data to {backup_file.name}")

    print()

    # Convert and sync Hot 100 data
    try:
        convert_hot_100_format(SCRAPER_HOT_100, WEBSITE_HOT_100)
        print(f"Hot 100 data synced successfully!")
    except Exception as e:
        print(f"Error syncing Hot 100 data: {e}")

    print()

    # Convert and sync Billboard 200 data
    if SCRAPER_BILLBOARD_200.exists():
        try:
            convert_billboard_200_format(SCRAPER_BILLBOARD_200, WEBSITE_BILLBOARD_200)
            print(f"Billboard 200 data synced successfully!")
        except Exception as e:
            print(f"Error syncing Billboard 200 data: {e}")

    print()
    print("=" * 60)
    print("Sync complete!")
    print("=" * 60)
    print()
    print("You can now start your website with: python app.py")

if __name__ == '__main__':
    main()
