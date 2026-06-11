#!/usr/bin/env python3
"""
Smart Billboard Data Updater
Automatically tries Kaggle first, falls back to Billboard.com if needed
"""
import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd

def get_latest_date_in_csv(csv_path):
    """Get the most recent date in CSV file"""
    if not Path(csv_path).exists():
        return None

    try:
        df = pd.read_csv(csv_path, low_memory=False)
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        return df['Date'].max()
    except Exception as e:
        print(f"⚠️  Error reading {csv_path}: {e}")
        return None

def is_data_stale(csv_path, days_threshold=7):
    """Check if CSV data is older than threshold"""
    latest_date = get_latest_date_in_csv(csv_path)

    if not latest_date:
        return True  # No data = stale

    days_old = (datetime.now() - latest_date).days
    return days_old > days_threshold

def try_kaggle_update():
    """Try to update from Kaggle"""
    print("\n" + "="*60)
    print("📦 Step 1: Trying Kaggle update...")
    print("="*60)

    try:
        result = subprocess.run(
            ['python3', 'auto_update_data.py'],
            capture_output=True,
            text=True,
            timeout=120
        )

        print(result.stdout)

        if result.returncode == 0:
            print("✅ Kaggle update successful!")
            return True
        else:
            print("⚠️  Kaggle update failed")
            if result.stderr:
                print(f"Error: {result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        print("⏱️  Kaggle update timed out")
        return False
    except Exception as e:
        print(f"❌ Kaggle update error: {e}")
        return False

def try_billboard_update(weeks=4):
    """Try to update from Billboard.com"""
    print("\n" + "="*60)
    print("🎵 Step 2: Trying Billboard direct update...")
    print("="*60)

    try:
        # Check if billboard.py is installed
        import billboard
        print("✓ billboard.py library found")
    except ImportError:
        print("⚠️  billboard.py not installed")
        print("Install with: pip3 install billboard.py")
        return False

    try:
        result = subprocess.run(
            ['python3', 'update_from_billboard.py', '--all', '--weeks', str(weeks)],
            capture_output=True,
            text=True,
            timeout=300
        )

        print(result.stdout)

        if result.returncode == 0:
            print("✅ Billboard direct update successful!")
            return True
        else:
            print("⚠️  Billboard direct update failed")
            if result.stderr:
                print(f"Error: {result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        print("⏱️  Billboard update timed out")
        return False
    except Exception as e:
        print(f"❌ Billboard update error: {e}")
        return False

def check_data_freshness():
    """Check if data needs updating"""
    print("\n" + "="*60)
    print("🔍 Checking data freshness...")
    print("="*60)

    hot100_stale = is_data_stale('data/hot100.csv', days_threshold=7)
    billboard200_stale = is_data_stale('data/billboard200.csv', days_threshold=7)

    hot100_latest = get_latest_date_in_csv('data/hot100.csv')
    billboard200_latest = get_latest_date_in_csv('data/billboard200.csv')

    if hot100_latest:
        days_old = (datetime.now() - hot100_latest).days
        print(f"\n📊 Hot 100:")
        print(f"   Latest: {hot100_latest.strftime('%Y-%m-%d')}")
        print(f"   Age: {days_old} days")
        print(f"   Status: {'🔴 Stale' if hot100_stale else '✅ Fresh'}")
    else:
        print("\n📊 Hot 100: ❌ No data found")
        hot100_stale = True

    if billboard200_latest:
        days_old = (datetime.now() - billboard200_latest).days
        print(f"\n💿 Billboard 200:")
        print(f"   Latest: {billboard200_latest.strftime('%Y-%m-%d')}")
        print(f"   Age: {days_old} days")
        print(f"   Status: {'🔴 Stale' if billboard200_stale else '✅ Fresh'}")
    else:
        print("\n💿 Billboard 200: ❌ No data found")
        billboard200_stale = True

    return hot100_stale or billboard200_stale

def main():
    """Main update logic"""
    print("\n" + "="*60)
    print("🤖 Smart Billboard Data Updater")
    print(f"⏰ {datetime.now().strftime('%A, %B %d, %Y at %I:%M %p')}")
    print("="*60)

    # Change to script directory
    os.chdir(Path(__file__).parent)

    # Check if update is needed
    needs_update = check_data_freshness()

    # Check for force flag
    force = '--force' in sys.argv

    if not needs_update and not force:
        print("\n✅ Data is fresh! No update needed.")
        print("💡 Use --force to update anyway")
        return

    if force:
        print("\n🔄 Force update requested...")

    # Step 1: Try Kaggle (fast, preferred)
    kaggle_success = try_kaggle_update()

    if kaggle_success:
        # Check if data is now fresh
        if not check_data_freshness():
            print("\n" + "="*60)
            print("🎉 Update complete via Kaggle!")
            print("="*60)
            return

    # Step 2: Kaggle failed or data still stale, try Billboard
    print("\n⚠️  Kaggle update insufficient, trying Billboard direct...")

    billboard_success = try_billboard_update(weeks=4)

    # Final status
    print("\n" + "="*60)
    if kaggle_success or billboard_success:
        print("✅ Update complete!")
        if billboard_success and not kaggle_success:
            print("📌 Note: Updated via Billboard direct (Kaggle unavailable)")
    else:
        print("❌ All update methods failed!")
        print("\nTroubleshooting:")
        print("  1. Check internet connection")
        print("  2. Install billboard.py: pip3 install billboard.py")
        print("  3. Setup Kaggle API: see KAGGLE_SETUP.md")
    print("="*60)

if __name__ == '__main__':
    main()
