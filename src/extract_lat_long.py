#!/usr/bin/env python3
r"""
Extract unique lat/lon coordinates from activities parquet files.

Reads activities_YYYY_MM.parquet from C:\walking\, extracts unique coordinates
at multiple precisions, and writes to data/lat_long.{2,3,4}.YYYY_MM.parquet files.
"""

from pathlib import Path
import pandas as pd
import sys


def extract_lat_long_for_month(year: int, month: int):
    """Extract lat/long from monthly activities parquet."""
    activities_file = Path(f"C:\\walking\\activities_{year:04d}_{month:02d}.parquet")
    data_dir = Path("C:\\Repo\\walk-ct\\data")

    if not activities_file.exists():
        print(f"Error: {activities_file} not found")
        return False

    data_dir.mkdir(parents=True, exist_ok=True)

    # Read activities parquet
    print(f"Reading {activities_file.name}...")
    df = pd.read_parquet(activities_file)

    if len(df) == 0:
        print("  No data found")
        return False

    # Extract unique lat/lon and round to 4 decimals
    coords_4 = df[['lat', 'lon']].copy()
    coords_4['lat'] = coords_4['lat'].round(4)
    coords_4['lon'] = coords_4['lon'].round(4)
    coords_4 = coords_4.drop_duplicates().reset_index(drop=True)

    # Write 4-decimal file
    file_4 = data_dir / f"lat_long.4.{year:04d}_{month:02d}.parquet"
    coords_4.to_parquet(file_4, compression="snappy", index=False)
    print(f"  {file_4.name}: {len(coords_4)} unique coordinates at 4-decimal precision")

    # Extract unique lat/lon and round to 3 decimals
    coords_3 = coords_4.copy()
    coords_3['lat'] = coords_3['lat'].round(3)
    coords_3['lon'] = coords_3['lon'].round(3)
    coords_3 = coords_3.drop_duplicates().reset_index(drop=True)

    # Write 3-decimal file
    file_3 = data_dir / f"lat_long.3.{year:04d}_{month:02d}.parquet"
    coords_3.to_parquet(file_3, compression="snappy", index=False)
    print(f"  {file_3.name}: {len(coords_3)} unique coordinates at 3-decimal precision")

    # Extract unique lat/lon and round to 2 decimals
    coords_2 = coords_3.copy()
    coords_2['lat'] = coords_2['lat'].round(2)
    coords_2['lon'] = coords_2['lon'].round(2)
    coords_2 = coords_2.drop_duplicates().reset_index(drop=True)

    # Write 2-decimal file
    file_2 = data_dir / f"lat_long.2.{year:04d}_{month:02d}.parquet"
    coords_2.to_parquet(file_2, compression="snappy", index=False)
    print(f"  {file_2.name}: {len(coords_2)} unique coordinates at 2-decimal precision")

    return True


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python extract_lat_long.py <year> <month>")
        print("Example: python extract_lat_long.py 2026 4")
        sys.exit(1)

    year = int(sys.argv[1])
    month = int(sys.argv[2])

    if extract_lat_long_for_month(year, month):
        print("\nDone!")
    else:
        sys.exit(1)
