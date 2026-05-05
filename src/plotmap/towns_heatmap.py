"""
Generate individual heatmaps for each of Connecticut's 169 towns.

For each town, creates a distance-based heatmap showing walked coverage
(white=walked, green<1mi, orange 1-1.8mi, red>1.8mi) cropped to the town boundary.
Saves as towns/{Town_Name}_heatmap.png.
"""

import json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy import ndimage
from shapely.geometry import shape
from shapely import contains_xy
import glob
from pathlib import Path

# Configuration
LAT_STEP = 0.003
LON_STEP = 0.004
MILES_PER_DEGREE_LAT = 69.17
MILES_PER_DEGREE_LON = 52.0
CT_BBOX = {
    'lat_min': 41.00,
    'lat_max': 42.05,
    'lon_min': -73.73,
    'lon_max': -71.79,
}

BOUNDARY_CACHE = "ct_boundary.json"
TOWNS_CACHE = "ct_towns.json"


def get_ct_boundary():
    """Load cached CT state boundary as shapely polygon."""
    if Path(BOUNDARY_CACHE).exists():
        with open(BOUNDARY_CACHE, 'r') as f:
            geom = json.load(f)
        return shape(geom)
    raise FileNotFoundError(f"{BOUNDARY_CACHE} not found")


def round_to_nearest_multiple_of_002(value):
    """Round to nearest .002 thousandths."""
    scaled = value * 1000
    rounded_scaled = int(np.round(scaled / 2) * 2)
    return rounded_scaled / 1000


def load_walked_coordinates():
    """Load all 4-decimal parquet files and combine."""
    parquet_files = sorted(glob.glob("../../data/lat_long.4.*.parquet"))

    print(f"Loading {len(parquet_files)} parquet files...")
    dfs = []
    for pf in parquet_files:
        df = pd.read_parquet(pf)
        dfs.append(df)

    combined = pd.concat(dfs, ignore_index=True)

    # Round to nearest .002 thousandths
    combined['lat'] = combined['lat'].apply(round_to_nearest_multiple_of_002)
    combined['lon'] = combined['lon'].apply(round_to_nearest_multiple_of_002)

    combined = combined.drop_duplicates(subset=['lat', 'lon']).reset_index(drop=True)

    print(f"Total unique walked coordinates: {len(combined)}")
    return combined


def build_distance_grid(walked_coords, ct_boundary):
    """
    Build a grid where each cell contains Euclidean distance to nearest walk.
    Uses 3:4 latitude:longitude ratio for square-ish cells.
    """
    lat_min, lat_max = CT_BBOX['lat_min'], CT_BBOX['lat_max']
    lon_min, lon_max = CT_BBOX['lon_min'], CT_BBOX['lon_max']

    rows = int(round((lat_max - lat_min) / LAT_STEP)) + 1
    cols = int(round((lon_max - lon_min) / LON_STEP)) + 1

    print(f"Grid dimensions: {rows} rows × {cols} cols")

    # Create walked mask
    walked_mask = np.zeros((rows, cols), dtype=bool)

    for _, row in walked_coords.iterrows():
        lat, lon = row['lat'], row['lon']
        r = int(round((lat - lat_min) / LAT_STEP))
        c = int(round((lon - lon_min) / LON_STEP))
        if 0 <= r < rows and 0 <= c < cols:
            walked_mask[r, c] = True

    print(f"Walked cells marked: {walked_mask.sum()}")

    # Compute Euclidean distance
    sampling = [LAT_STEP * MILES_PER_DEGREE_LAT, LON_STEP * MILES_PER_DEGREE_LON]
    distance_grid = ndimage.distance_transform_edt(~walked_mask, sampling=sampling).astype(float)

    print(f"Distance range: {distance_grid.min():.2f} to {distance_grid.max():.2f} miles")

    # Mask to CT boundary
    lats = np.arange(rows) * LAT_STEP + lat_min
    lons = np.arange(cols) * LON_STEP + lon_min

    lon_grid, lat_grid = np.meshgrid(lons, lats)

    inside_ct = contains_xy(ct_boundary, lon_grid.ravel(), lat_grid.ravel())
    inside_ct = inside_ct.reshape(distance_grid.shape)

    distance_grid[~inside_ct] = np.nan

    extent = [lon_min, lon_max, lat_min, lat_max]
    return distance_grid, extent, rows, cols


def get_town_boundary_lines(town_names):
    """Extract boundary lines for specified towns from GeoJSON."""
    if not Path("ct_towns.geojson").exists():
        return []

    with open("ct_towns.geojson", 'r') as f:
        towns_geojson = json.load(f)

    boundary_lines = []
    for feature in towns_geojson.get('features', []):
        name = feature['properties'].get('name', '').strip()
        if name and 'not defined' not in name.lower() and name in town_names:
            geom = shape(feature['geometry'])
            boundary = geom.boundary

            # Extract coordinates from boundary
            if hasattr(boundary, 'geoms'):  # MultiLineString
                for line in boundary.geoms:
                    coords = list(line.coords)
                    if coords:
                        boundary_lines.append(coords)
            else:  # LineString
                coords = list(boundary.coords)
                if coords:
                    boundary_lines.append(coords)

    return boundary_lines


def render_town_heatmap(town_grid, extent, town_geom, town_name, output_path):
    """Render a single town's heatmap with distance color scheme."""
    fig, ax = plt.subplots(figsize=(12, 12))

    # Flip for display
    town_grid_flipped = town_grid[::-1]

    # Build RGB array with distance color scheme
    rgb_map = {
        'white': np.array([1.0, 1.0, 1.0]),      # distance=0
        'green': np.array([0.0, 0.502, 0.0]),    # <1.0
        'orange': np.array([1.0, 0.647, 0.0]),   # 1.0-1.8
        'red': np.array([1.0, 0.0, 0.0]),        # >1.8
    }

    rgb_grid = np.zeros((*town_grid.shape, 3))

    for i in range(town_grid.shape[0]):
        for j in range(town_grid.shape[1]):
            dist = town_grid[i, j]

            if np.isnan(dist):
                rgb_grid[i, j] = np.array([0.95, 0.95, 0.95])  # light gray outside town
            elif dist == 0:
                rgb_grid[i, j] = rgb_map['white']
            elif dist < 1.0:
                rgb_grid[i, j] = rgb_map['green']
            elif dist < 1.8:
                rgb_grid[i, j] = rgb_map['orange']
            else:
                rgb_grid[i, j] = rgb_map['red']

    # Flip for display
    rgb_grid = rgb_grid[::-1]

    im = ax.imshow(
        rgb_grid,
        extent=extent,
        aspect='equal',
        interpolation='nearest'
    )

    # Draw town boundary
    boundary_lines = get_town_boundary_lines([town_name])
    if boundary_lines:
        for coords in boundary_lines:
            lons = [c[0] for c in coords]
            lats = [c[1] for c in coords]
            ax.plot(lons, lats, color='black', linewidth=1.0, alpha=0.8)

    cbar = plt.colorbar(im, ax=ax, label='Euclidean distance (miles)')

    ax.set_xlabel('Longitude')
    ax.set_ylabel('Latitude')
    ax.set_title(f'{town_name} - Coverage Heatmap')

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()


def main():
    print("Generating per-town heatmaps...")

    # Load data once
    walked_coords = load_walked_coordinates()
    ct_boundary = get_ct_boundary()
    distance_grid, full_extent, rows, cols = build_distance_grid(walked_coords, ct_boundary)

    # Create output directory
    Path("towns").mkdir(exist_ok=True)

    # Load town geometries
    if not Path("ct_towns.geojson").exists():
        print("Error: ct_towns.geojson not found")
        return

    with open("ct_towns.geojson", 'r') as f:
        towns_geojson = json.load(f)

    # Process each town
    town_count = 0
    for feature in towns_geojson.get('features', []):
        name = feature['properties'].get('name', '').strip()
        if not name or 'not defined' in name.lower():
            continue

        town_count += 1
        geom = shape(feature['geometry'])
        minx, miny, maxx, maxy = geom.bounds  # lon_min, lat_min, lon_max, lat_max

        # Add padding (1 grid cell each side)
        r_min = max(0, int((miny - CT_BBOX['lat_min']) / LAT_STEP) - 1)
        r_max = min(rows - 1, int((maxy - CT_BBOX['lat_min']) / LAT_STEP) + 1)
        c_min = max(0, int((minx - CT_BBOX['lon_min']) / LON_STEP) - 1)
        c_max = min(cols - 1, int((maxx - CT_BBOX['lon_min']) / LON_STEP) + 1)

        # Slice distance grid to town area
        town_grid = distance_grid[r_min:r_max+1, c_min:c_max+1].copy()

        # Re-mask: NaN cells inside CT but outside this town
        lats = np.arange(r_min, r_max+1) * LAT_STEP + CT_BBOX['lat_min']
        lons = np.arange(c_min, c_max+1) * LON_STEP + CT_BBOX['lon_min']
        lon_grid, lat_grid = np.meshgrid(lons, lats)
        inside_town = contains_xy(geom, lon_grid.ravel(), lat_grid.ravel()).reshape(town_grid.shape)
        town_grid[~inside_town] = np.nan

        # Set extent for this town
        town_extent = [
            CT_BBOX['lon_min'] + c_min * LON_STEP,
            CT_BBOX['lon_min'] + (c_max + 1) * LON_STEP,
            CT_BBOX['lat_min'] + r_min * LAT_STEP,
            CT_BBOX['lat_min'] + (r_max + 1) * LAT_STEP,
        ]

        # Generate filename and render
        filename = name.replace(' ', '_').replace('/', '_')
        output_path = f"towns/{filename}_heatmap.png"

        print(f"  [{town_count:3d}] {name:30s} -> {filename}_heatmap.png")

        render_town_heatmap(town_grid, town_extent, geom, name, output_path)

    print(f"\nGenerated {town_count} town heatmaps in towns/ folder")


if __name__ == "__main__":
    main()
