"""
Clip Distance_3.csv to only points within Connecticut's boundary.

Downloads the Connecticut state boundary from the US Census Bureau
cartographic boundary files, then filters the CSV to points inside
the polygon. Outputs Distance_3_ct.csv.
"""

import json
import urllib.request
import numpy as np
import pandas as pd
from shapely.geometry import shape, Point, MultiPolygon
from shapely.prepared import prep

BOUNDARY_URL = (
    "https://raw.githubusercontent.com/PublicaMundi/"
    "MappingAPI/master/data/geojson/us-states.json"
)
BOUNDARY_CACHE = "ct_boundary.json"
INPUT_CSV = "Distance_3.csv"
OUTPUT_CSV = "Distance_3_ct.csv"


def get_ct_boundary():
    """Download US states GeoJSON and extract Connecticut polygon."""
    import os
    if os.path.exists(BOUNDARY_CACHE):
        print(f"Loading cached boundary from {BOUNDARY_CACHE}")
        with open(BOUNDARY_CACHE, 'r') as f:
            geom = json.load(f)
        return shape(geom)

    print("Downloading US states GeoJSON...")
    with urllib.request.urlopen(BOUNDARY_URL) as resp:
        data = json.loads(resp.read().decode())

    for feature in data['features']:
        if feature['properties']['name'] == 'Connecticut':
            geom = feature['geometry']
            # Cache for future runs
            with open(BOUNDARY_CACHE, 'w') as f:
                json.dump(geom, f)
            print(f"Cached CT boundary to {BOUNDARY_CACHE}")
            return shape(geom)

    raise ValueError("Connecticut not found in GeoJSON")


def main():
    ct_poly = get_ct_boundary()
    ct_prepared = prep(ct_poly)

    print(f"Loading {INPUT_CSV}...")
    df = pd.read_csv(INPUT_CSV, low_memory=False)
    df = df.dropna(subset=['lat', 'long', 'Dist'])
    df['lat'] = pd.to_numeric(df['lat'], errors='coerce')
    df['Dist'] = pd.to_numeric(df['Dist'], errors='coerce')
    df = df.dropna()
    print(f"  Loaded {len(df)} points")

    # Vectorized point-in-polygon using shapely prepared geometry
    print("Filtering points inside Connecticut...")
    coords = np.column_stack([df['long'].values, df['lat'].values])

    # Use shapely.contains_xy for fast vectorized point-in-polygon
    from shapely import contains_xy
    inside = contains_xy(ct_poly, coords[:, 0], coords[:, 1])

    df_ct = df[inside].copy()
    removed = len(df) - len(df_ct)
    print(f"  Kept {len(df_ct)} points inside CT")
    print(f"  Removed {removed} points outside CT")

    df_ct.to_csv(OUTPUT_CSV, index=False)
    print(f"Saved {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
