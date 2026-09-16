"""
Clip Distance_3.csv to only points within Connecticut's boundary.

Filters the CSV to points inside the state and writes Distance_3_ct.csv.

This is the legacy path, kept for the SQL-derived Distance_3.csv.
distance_from_parquet.py builds the same output straight from the parquet
files and is the one do_current_month.bat runs.
"""

import argparse

import numpy as np
import pandas as pd
from shapely import contains_xy

import ct_outline

INPUT_CSV = "Distance_3.csv"
OUTPUT_CSV = "Distance_3_ct.csv"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--boundary", choices=("shoreline", "towns", "state"),
                        default="shoreline",
                        help="shoreline = town outlines clipped to the coast "
                             "(default, matches the rest of the maps); towns = "
                             "adds each coastal town's water jurisdiction; "
                             "state = the old 16-point outline")
    parser.add_argument("--islands", action="store_true",
                        help="keep the offshore islands, which no walker can "
                             "reach (default: mainland only)")
    args = parser.parse_args()

    ct_poly = ct_outline.ct_outline(args.boundary, islands=args.islands)
    print(f"Boundary: {args.boundary} outline, "
          f"{'islands included' if args.islands else 'mainland only'}")

    print(f"Loading {INPUT_CSV}...")
    df = pd.read_csv(INPUT_CSV, low_memory=False)
    df = df.dropna(subset=['lat', 'long', 'Dist'])
    df['lat'] = pd.to_numeric(df['lat'], errors='coerce')
    df['Dist'] = pd.to_numeric(df['Dist'], errors='coerce')
    df = df.dropna()
    print(f"  Loaded {len(df)} points")

    print("Filtering points inside Connecticut...")
    coords = np.column_stack([df['long'].values, df['lat'].values])
    inside = contains_xy(ct_poly, coords[:, 0], coords[:, 1])

    df_ct = df[inside].copy()
    removed = len(df) - len(df_ct)
    print(f"  Kept {len(df_ct)} points inside CT")
    print(f"  Removed {removed} points outside CT")

    df_ct.to_csv(OUTPUT_CSV, index=False)
    print(f"Saved {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
