#!/usr/bin/env python3
"""
Update Billboard data by running the scraper and syncing to website
This replaces the old Kaggle-based update system with direct Billboard scraping
"""
import os
import sys
import subprocess
from pathlib import Path

# Paths
SCRAPER_DIR = Path.home() / 'Billboard-Streaming-Songs-Datacollector'
WEBSITE_DIR = Path.home() / 'Billboard-Hot-100-Website'

def run_scraper():
    """Run the Billboard scraper to get latest data"""
    print("=" * 60)
    print("Running Billboard Scraper...")
    print("=" * 60)
    print()

    if not SCRAPER_DIR.exists():
        print(f"Error: Scraper project not found at {SCRAPER_DIR}")
        return False

    try:
        # Run scraper for latest week
        result = subprocess.run(
            ['python3', 'scraper.py', '--weeks', '1'],
            cwd=SCRAPER_DIR,
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )

        if result.returncode == 0:
            print(result.stdout)
            print("Scraper completed successfully!")
            return True
        else:
            print(f"Scraper failed with error:")
            print(result.stderr)
            return False

    except subprocess.TimeoutExpired:
        print("Scraper timed out after 5 minutes")
        return False
    except Exception as e:
        print(f"Error running scraper: {e}")
        return False

def sync_data():
    """Sync scraped data to website"""
    print()
    print("=" * 60)
    print("Syncing Data to Website...")
    print("=" * 60)
    print()

    try:
        result = subprocess.run(
            ['python3', 'sync_data_from_scraper.py'],
            cwd=WEBSITE_DIR,
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode == 0:
            print(result.stdout)
            return True
        else:
            print(f"Sync failed with error:")
            print(result.stderr)
            return False

    except Exception as e:
        print(f"Error syncing data: {e}")
        return False

def main():
    print("\n" + "=" * 60)
    print("Billboard Data Updater (Scraper-based)")
    print("=" * 60)
    print()

    # Step 1: Run scraper
    scraper_success = run_scraper()

    if not scraper_success:
        print("\nScraper failed. Aborting update.")
        sys.exit(1)

    # Step 2: Sync data
    sync_success = sync_data()

    if not sync_success:
        print("\nData sync failed. Check logs above.")
        sys.exit(1)

    print()
    print("=" * 60)
    print("Update Complete!")
    print("=" * 60)
    print()
    print("Billboard data has been updated with the latest charts.")
    print("Your website now has the most recent data.")

if __name__ == '__main__':
    main()
