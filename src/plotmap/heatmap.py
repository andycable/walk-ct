"""
Build a Manhattan distance heatmap from walked coordinates.

Loads all 2-decimal lat/long parquet files, builds a grid, and computes
the Manhattan distance from each grid cell to the nearest walked location.
Renders as a heatmap and saves as PNG.
"""

import json
import urllib.request
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy import ndimage
from shapely.geometry import shape
from shapely import contains_xy
import glob
from pathlib import Path

# Configuration
GRID_STEP = 0.01  # 2-decimal precision
CT_BBOX = {
    'lat_min': 41.00,
    'lat_max': 42.05,
    'lon_min': -73.73,
    'lon_max': -71.79,
}

BOUNDARY_URL = (
    "https://raw.githubusercontent.com/PublicaMundi/"
    "MappingAPI/master/data/geojson/us-states.json"
)
BOUNDARY_CACHE = "ct_boundary.json"

# Output
OUTPUT_PNG = "heatmap.png"


def get_ct_boundary():
    """Download or load cached CT state boundary as shapely polygon."""
    if Path(BOUNDARY_CACHE).exists():
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
            with open(BOUNDARY_CACHE, 'w') as f:
                json.dump(geom, f)
            print(f"Cached CT boundary to {BOUNDARY_CACHE}")
            return shape(geom)

    raise ValueError("Connecticut not found in GeoJSON")


def load_walked_coordinates():
    """Load all 2-decimal parquet files and combine."""
    parquet_files = sorted(glob.glob("../../data/lat_long.2.*.parquet"))

    print(f"Loading {len(parquet_files)} parquet files...")
    dfs = []
    for pf in parquet_files:
        df = pd.read_parquet(pf)
        dfs.append(df)

    combined = pd.concat(dfs, ignore_index=True)
    combined = combined.drop_duplicates(subset=['lat', 'lon']).reset_index(drop=True)

    print(f"Total unique walked coordinates: {len(combined)}")
    return combined


def build_distance_grid(walked_coords, ct_boundary):
    """
    Build a grid where each cell contains Manhattan distance to nearest walk.

    Returns:
        distance_grid: 2D array of distances (np.nan outside CT)
        extent: [lon_min, lon_max, lat_min, lat_max] for imshow
    """
    lat_min, lat_max = CT_BBOX['lat_min'], CT_BBOX['lat_max']
    lon_min, lon_max = CT_BBOX['lon_min'], CT_BBOX['lon_max']

    # Grid dimensions
    rows = int(round((lat_max - lat_min) / GRID_STEP)) + 1
    cols = int(round((lon_max - lon_min) / GRID_STEP)) + 1

    print(f"Grid dimensions: {rows} rows × {cols} cols")

    # Create walked mask: True where we walked, False elsewhere
    walked_mask = np.zeros((rows, cols), dtype=bool)

    for _, row in walked_coords.iterrows():
        lat, lon = row['lat'], row['lon']
        r = int(round((lat - lat_min) / GRID_STEP))
        c = int(round((lon - lon_min) / GRID_STEP))
        if 0 <= r < rows and 0 <= c < cols:
            walked_mask[r, c] = True

    print(f"Walked cells marked: {walked_mask.sum()}")

    # Compute Manhattan distance from each unwalked cell to nearest walked cell
    # distance_transform_cdt expects 1=background, 0=feature
    # So we invert: True (walked) -> 0 (feature), False (unwalked) -> 1 (background)
    distance_grid = ndimage.distance_transform_cdt(~walked_mask, metric='taxicab').astype(float)

    print(f"Distance range: {distance_grid.min():.0f} to {distance_grid.max():.0f}")

    # Mask to CT boundary
    # Create lat/lon coordinate arrays for each grid cell
    lats = np.linspace(lat_min, lat_max, rows)
    lons = np.linspace(lon_min, lon_max, cols)

    lon_grid, lat_grid = np.meshgrid(lons, lats)

    # Point-in-polygon check for all grid cells
    inside_ct = contains_xy(ct_boundary, lon_grid.ravel(), lat_grid.ravel())
    inside_ct = inside_ct.reshape(distance_grid.shape)

    # Set cells outside CT to NaN
    distance_grid[~inside_ct] = np.nan

    extent = [lon_min, lon_max, lat_min, lat_max]
    return distance_grid, extent


def render_heatmap(distance_grid, extent):
    """Render distance grid as heatmap and save PNG."""
    fig, ax = plt.subplots(figsize=(15, 12))

    # Flip vertically so north is up (matches find_largest_unwalked.py pattern)
    distance_grid_flipped = distance_grid[::-1]

    # Render with custom colormap: green (visited) to red (far)
    im = ax.imshow(
        distance_grid_flipped,
        extent=extent,
        aspect=1.4,
        cmap='RdYlGn_r',
        interpolation='nearest'
    )

    cbar = plt.colorbar(im, ax=ax, label='Manhattan distance (grid cells)')

    ax.set_xlabel('Longitude')
    ax.set_ylabel('Latitude')
    ax.set_title('Andy Walks Connecticut - Coverage Heatmap')

    plt.tight_layout()
    plt.savefig(OUTPUT_PNG, dpi=150, bbox_inches='tight')
    print(f"Saved {OUTPUT_PNG}")


def main():
    print("Building Manhattan distance heatmap...")

    # Load data
    walked_coords = load_walked_coordinates()

    # Get CT boundary
    ct_boundary = get_ct_boundary()

    # Build grid with distances
    distance_grid, extent = build_distance_grid(walked_coords, ct_boundary)

    # Render
    render_heatmap(distance_grid, extent)

    print("Done!")


if __name__ == "__main__":
    main()
