#!/usr/bin/env python3
"""
Billboard Data Auto-Updater
Automatically downloads the latest Billboard data from Kaggle
"""
import os
import json
import zipfile
import shutil
from datetime import datetime
from pathlib import Path

# Configuration
KAGGLE_DATASET = 'ludmin/billboard'
DATA_DIR = Path('data')
METADATA_FILE = DATA_DIR / 'metadata.json'

def setup_data_directory():
    """Create data directory if it doesn't exist"""
    DATA_DIR.mkdir(exist_ok=True)
    print(f"✓ Data directory: {DATA_DIR}")

def check_kaggle_setup():
    """Check if Kaggle API is configured"""
    kaggle_json = Path.home() / '.kaggle' / 'kaggle.json'
    if not kaggle_json.exists():
        print("\n⚠️  Kaggle API not configured!")
        print("\nTo set up Kaggle API:")
        print("1. Go to https://www.kaggle.com/settings")
        print("2. Scroll to 'API' section")
        print("3. Click 'Create New API Token'")
        print("4. Save kaggle.json to ~/.kaggle/kaggle.json")
        print("5. Run: chmod 600 ~/.kaggle/kaggle.json")
        return False
    return True

def get_local_metadata():
    """Get metadata about currently downloaded dataset"""
    if METADATA_FILE.exists():
        with open(METADATA_FILE, 'r') as f:
            return json.load(f)
    return None

def save_metadata(info):
    """Save dataset metadata"""
    with open(METADATA_FILE, 'w') as f:
        json.dump(info, f, indent=2)

def download_billboard_data():
    """Download latest Billboard data from Kaggle"""
    try:
        import kaggle

        print("\n🔍 Checking for latest Billboard data...")

        # Get dataset info
        api = kaggle.api
        dataset_info = api.dataset_list(search=KAGGLE_DATASET)[0]

        # Check local metadata
        local_meta = get_local_metadata()
        remote_date = dataset_info.lastUpdated

        if local_meta:
            local_date = datetime.fromisoformat(local_meta['lastUpdated'])
            if remote_date <= local_date:
                print(f"✓ Data is up to date (last updated: {local_date.strftime('%Y-%m-%d')})")
                return False

        print(f"\n📥 Downloading new Billboard data (updated: {remote_date.strftime('%Y-%m-%d')})")

        # Download dataset
        api.dataset_download_files(
            KAGGLE_DATASET,
            path=DATA_DIR,
            unzip=True
        )

        # Save metadata
        save_metadata({
            'dataset': KAGGLE_DATASET,
            'lastUpdated': remote_date.isoformat(),
            'downloadedAt': datetime.now().isoformat()
        })

        print(f"✅ Billboard data updated successfully!")
        print(f"📁 Files saved to: {DATA_DIR.absolute()}")

        # List downloaded files
        print("\n📊 Downloaded files:")
        for file in DATA_DIR.glob('*.csv'):
            size_mb = file.stat().st_size / (1024 * 1024)
            print(f"  - {file.name} ({size_mb:.1f} MB)")

        return True

    except ImportError:
        print("\n❌ Kaggle package not installed!")
        print("Install it with: pip install kaggle")
        return False
    except Exception as e:
        print(f"\n❌ Error downloading data: {str(e)}")
        return False

def find_hot100_file():
    """Find the Hot 100 CSV file in downloaded data"""
    # Common Hot 100 file names
    hot100_files = [
        'hot-100-current.csv',
        'data/hot100.csv',
        'billboard_hot_100.csv',
        'hot_100.csv'
    ]

    for filename in hot100_files:
        filepath = DATA_DIR / filename
        if filepath.exists():
            return filepath

    # If not found, list all CSV files
    csv_files = list(DATA_DIR.glob('*.csv'))
    if csv_files:
        print(f"\n📋 Available CSV files:")
        for i, f in enumerate(csv_files, 1):
            print(f"  {i}. {f.name}")
        # Return the first one as default
        return csv_files[0]

    return None

def main():
    """Main function"""
    print("="*60)
    print("Billboard Data Auto-Updater")
    print("="*60)

    # Setup
    setup_data_directory()

    # Check Kaggle setup
    if not check_kaggle_setup():
        return

    # Download data
    updated = download_billboard_data()

    if updated or not get_local_metadata():
        hot100_file = find_hot100_file()
        if hot100_file:
            print(f"\n✓ Hot 100 data file: {hot100_file.name}")

            # Copy to Desktop for easy access
            desktop_path = Path.home() / 'Desktop' / 'hot100.csv'
            shutil.copy(hot100_file, desktop_path)
            print(f"✓ Copied to Desktop: {desktop_path}")

    print("\n" + "="*60)
    print("Update check complete!")
    print("="*60)

if __name__ == '__main__':
    main()
