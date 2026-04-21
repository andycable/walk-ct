#!/usr/bin/env python3
"""Generate lat_long.4 parquet files for all months with activity data."""

from pathlib import Path
import pandas as pd
from datetime import datetime

# Get all activities files
activities_dir = Path("C:/walking")
activities_files = sorted(activities_dir.glob("activities_*.parquet"))

print(f"Found {len(activities_files)} activities files")
print("Generating 4-decimal precision files...\n")

data_dir = Path("C:/Repo/walk-ct/data")
data_dir.mkdir(parents=True, exist_ok=True)

success_count = 0
for activities_file in activities_files:
    # Extract year and month from filename
    stem = activities_file.stem  # e.g., "activities_2026_04"
    year_month = stem.replace("activities_", "")  # e.g., "2026_04"

    try:
        # Read activities parquet
        df = pd.read_parquet(activities_file)

        if len(df) == 0:
            continue

        # Extract unique lat/lon and round to 4 decimals
        coords_4 = df[['lat', 'lon']].copy()
        coords_4['lat'] = coords_4['lat'].round(4)
        coords_4['lon'] = coords_4['lon'].round(4)
        coords_4 = coords_4.drop_duplicates().reset_index(drop=True)

        # Write 4-decimal file
        file_4 = data_dir / f"lat_long.4.{year_month}.parquet"
        coords_4.to_parquet(file_4, compression="snappy", index=False)

        print(f"{year_month}: {len(coords_4)} unique coordinates at 4-decimal precision")
        success_count += 1

    except Exception as e:
        print(f"Error processing {activities_file.name}: {e}")

print(f"\nCompleted: {success_count}/{len(activities_files)} files processed")
