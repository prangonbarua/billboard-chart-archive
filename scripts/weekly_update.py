#!/usr/bin/env python3
"""
Automatic Weekly Billboard Data Updater
Downloads latest data every Wednesday from Kaggle
"""
import os
import sys
import subprocess
from datetime import datetime
from pathlib import Path

def is_wednesday():
    """Check if today is Wednesday"""
    return datetime.now().weekday() == 2  # 0=Monday, 2=Wednesday

def download_billboard_data():
    """Download latest Billboard data from Kaggle"""
    print("📥 Downloading latest Billboard data from Kaggle...")

    try:
        # Download using curl
        result = subprocess.run([
            'curl', '-L',
            'https://www.kaggle.com/api/v1/datasets/download/ludmin/billboard',
            '-o', 'billboard.zip'
        ], capture_output=True, text=True, timeout=60)

        if result.returncode != 0:
            print(f"❌ Download failed: {result.stderr}")
            return False

        # Unzip
        print("📦 Extracting files...")
        subprocess.run(['unzip', '-o', '-q', 'billboard.zip'], check=True)

        # Clean up zip file
        os.remove('billboard.zip')

        # Check if hot100.csv exists
        if Path('data/hot100.csv').exists():
            # Fix dates to be Saturdays (Billboard standard)
            print("🔧 Correcting dates to Saturdays...")
            import pandas as pd
            from datetime import timedelta

            df = pd.read_csv('data/hot100.csv', low_memory=False)
            df['Date'] = pd.to_datetime(df['Date'])

            # Convert all dates to nearest Saturday
            def to_saturday(date):
                days_ahead = 5 - date.weekday()  # 5 = Saturday
                if days_ahead < 0:
                    days_ahead += 7
                return date + timedelta(days=days_ahead)

            df['Date'] = df['Date'].apply(to_saturday)

            # Clean up pipe characters in artist names
            def clean_artist_name(artist):
                if pd.isna(artist):
                    return artist
                return artist.replace('|', ',')

            df['Artist'] = df['Artist'].apply(clean_artist_name)
            df.to_csv('data/hot100.csv', index=False)

            size_mb = Path('data/hot100.csv').stat().st_size / (1024 * 1024)
            mod_time = datetime.fromtimestamp(Path('data/hot100.csv').stat().st_mtime)
            print(f"✅ Updated hot100.csv ({size_mb:.1f} MB)")
            print(f"📅 File date: {mod_time.strftime('%Y-%m-%d %H:%M')}")
            print(f"📊 Date range: {df['Date'].min()} to {df['Date'].max()}")
            return True
        else:
            print("❌ hot100.csv not found in downloaded data")
            return False

    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def main():
    """Main function"""
    print("="*60)
    print("Billboard Weekly Auto-Updater")
    print(f"Today: {datetime.now().strftime('%A, %B %d, %Y')}")
    print("="*60)

    # Change to script directory
    os.chdir(Path(__file__).parent)

    # Check if it's Wednesday or force update
    if is_wednesday() or '--force' in sys.argv:
        if '--force' in sys.argv:
            print("\n🔄 Force update requested...")
        else:
            print("\n📅 It's Wednesday! Time to update Billboard data...")

        success = download_billboard_data()

        if success:
            print("\n✅ Update complete!")
        else:
            print("\n❌ Update failed!")
    else:
        print(f"\n⏭️  Not Wednesday - skipping update")
        print("💡 Run with --force to update anyway")

    print("="*60)

if __name__ == '__main__':
    main()
