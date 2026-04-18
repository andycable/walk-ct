"""
Build a Euclidean distance heatmap from walked coordinates.

Loads all 3-decimal lat/long parquet files, builds a grid, and computes
the Euclidean distance from each grid cell to the nearest walked location.
Renders as a heatmap and saves as PNG.
"""

import json
import urllib.request
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy import ndimage
from shapely.geometry import shape, LineString, MultiLineString
from shapely import contains_xy
import glob
from pathlib import Path
from matplotlib.collections import LineCollection

# Configuration
GRID_STEP = 0.005  # Matches .005, .010, .015, etc. resolution
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

TOWNS_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
    "10m_cultural/ne_10m_admin_2_counties_lakes.zip"
)
TOWNS_CACHE = "ct_towns.json"
TOWN_BOUNDARIES_CSV = "town_boundaries.csv"

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


def get_town_boundaries():
    """
    Load town boundaries and classify as walked/unwalked.

    Returns:
        walked_lines: list of (coords) for walked boundaries
        unwalked_lines: list of (coords) for unwalked boundaries
    """
    if not Path(TOWN_BOUNDARIES_CSV).exists():
        print(f"Warning: {TOWN_BOUNDARIES_CSV} not found. Skipping town boundaries.")
        return [], []

    if not Path("ct_towns.geojson").exists():
        print("Note: ct_towns.geojson not found. To add town boundaries:")
        print("  1. Download Connecticut town boundaries as GeoJSON")
        print("  2. Save as ct_towns.geojson in src/plotmap/")
        print("  3. Re-run this script")
        return [], []

    # Load town boundaries from GeoJSON
    print("Loading town boundaries from ct_towns.geojson...")
    with open("ct_towns.geojson", 'r') as f:
        towns_geojson = json.load(f)

    # Parse town geometries
    towns = {}
    for feature in towns_geojson.get('features', []):
        name = feature['properties'].get('name', '').strip()
        geom = shape(feature['geometry'])
        if name:
            towns[name] = geom

    print(f"Loaded {len(towns)} towns")

    # Load town boundary pairs and their crossed status
    bounds_df = pd.read_csv(TOWN_BOUNDARIES_CSV)
    walked_lines = []
    unwalked_lines = []

    for _, row in bounds_df.iterrows():
        town1 = row['Town1'].strip()
        town2 = row['Town2'].strip()
        crossed = row['crossed']

        if town1 not in towns or town2 not in towns:
            continue

        # Get intersection boundary
        geom1 = towns[town1]
        geom2 = towns[town2]

        try:
            # Get the boundary line(s) between the two towns
            boundary = geom1.boundary.intersection(geom2.boundary)

            if boundary.is_empty:
                continue

            # Extract coordinates from boundary
            if hasattr(boundary, 'geoms'):  # MultiLineString
                for line in boundary.geoms:
                    coords = list(line.coords)
                    if crossed:
                        walked_lines.append(coords)
                    else:
                        unwalked_lines.append(coords)
            else:  # LineString
                coords = list(boundary.coords)
                if coords:
                    if crossed:
                        walked_lines.append(coords)
                    else:
                        unwalked_lines.append(coords)
        except Exception as e:
            pass  # Skip problematic boundaries

    print(f"Found {len(walked_lines)} walked town boundaries")
    print(f"Found {len(unwalked_lines)} unwalked town boundaries")

    return walked_lines, unwalked_lines


def round_to_nearest_multiple_of_005(value):
    """Round to nearest .005 thousandths (.005, .010, .015, .020, etc)"""
    scaled = value * 1000
    rounded_scaled = int(np.round(scaled / 5) * 5)
    return rounded_scaled / 1000


def load_walked_coordinates():
    """Load all 3-decimal parquet files and combine, then round to even thousandths."""
    parquet_files = sorted(glob.glob("../../data/lat_long.3.*.parquet"))

    print(f"Loading {len(parquet_files)} parquet files...")
    dfs = []
    for pf in parquet_files:
        df = pd.read_parquet(pf)
        dfs.append(df)

    combined = pd.concat(dfs, ignore_index=True)

    # Round to nearest .005 thousandths (.005, .010, .015, .020, etc.)
    combined['lat'] = combined['lat'].apply(round_to_nearest_multiple_of_005)
    combined['lon'] = combined['lon'].apply(round_to_nearest_multiple_of_005)

    combined = combined.drop_duplicates(subset=['lat', 'lon']).reset_index(drop=True)

    print(f"Total unique walked coordinates: {len(combined)}")
    return combined


def build_distance_grid(walked_coords, ct_boundary):
    """
    Build a grid where each cell contains Euclidean distance to nearest walk.

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

    # Compute Euclidean distance from each unwalked cell to nearest walked cell
    # distance_transform_edt expects 1=background, 0=feature
    # So we invert: True (walked) -> 0 (feature), False (unwalked) -> 1 (background)
    distance_grid = ndimage.distance_transform_edt(~walked_mask).astype(float)

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


def find_towns_with_largest_holes(distance_grid, ct_bbox=CT_BBOX, grid_step=GRID_STEP):
    """Find towns with largest maximum distances (biggest unwalked holes)."""
    if not Path("ct_towns.geojson").exists():
        print("Note: ct_towns.geojson not found. Skipping town analysis.")
        return

    print("Analyzing towns for largest unwalked holes...")
    with open("ct_towns.geojson", 'r') as f:
        towns_geojson = json.load(f)

    # Build lat/lon grids for distance lookups
    lat_min, lat_max = ct_bbox['lat_min'], ct_bbox['lat_max']
    lon_min, lon_max = ct_bbox['lon_min'], ct_bbox['lon_max']
    rows = int(round((lat_max - lat_min) / grid_step)) + 1
    cols = int(round((lon_max - lon_min) / grid_step)) + 1

    lats = np.linspace(lat_min, lat_max, rows)
    lons = np.linspace(lon_min, lon_max, cols)
    lon_grid, lat_grid = np.meshgrid(lons, lats)

    # Extract towns and compute max distance in each
    town_holes = []
    for feature in towns_geojson.get('features', []):
        name = feature['properties'].get('name', '').strip()
        if not name or 'not defined' in name.lower():
            continue

        geom = shape(feature['geometry'])

        # Find all grid cells within this town
        inside_town = contains_xy(geom, lon_grid.ravel(), lat_grid.ravel())
        inside_town = inside_town.reshape(distance_grid.shape)

        # Get distances within town (excluding NaN)
        town_distances = distance_grid[inside_town & ~np.isnan(distance_grid)]

        if len(town_distances) > 0:
            max_dist = np.nanmax(town_distances)
            town_holes.append((name, max_dist))

    # Sort by max distance descending
    town_holes.sort(key=lambda x: x[1], reverse=True)

    # Print top 9
    print("\n" + "="*60)
    print("Top 9 Towns with Largest Unwalked Holes")
    print("="*60)
    print(f"{'Town':30} | {'Max Distance':>12}")
    print("-"*60)

    top_9_towns = []
    for i, (town, max_dist) in enumerate(town_holes[:9], 1):
        print(f"{town:30} | {max_dist:>12.1f}")
        top_9_towns.append(town)

    print("="*60 + "\n")

    return top_9_towns


def print_distance_summary(distance_grid):
    """Print summary of number of grid cells at each Euclidean distance."""
    # Flatten and remove NaN values
    distances = distance_grid[~np.isnan(distance_grid)].flatten()

    if len(distances) == 0:
        print("No distance data to summarize")
        return

    # Count points at each distance
    unique_distances, counts = np.unique(distances, return_counts=True)

    print("\n" + "="*60)
    print("Euclidean Distance Summary")
    print("="*60)
    print(f"{'Distance':>10} | {'Cell Count':>15} | {'Cumulative %':>12}")
    print("-"*60)

    total = len(distances)
    cumulative = 0

    for dist, count in zip(unique_distances, counts):
        cumulative += count
        pct = (cumulative / total) * 100
        print(f"{dist:>10.1f} | {count:>15} | {pct:>11.1f}%")

    print("-"*60)
    print(f"{'TOTAL':>10} | {total:>15}")
    print("="*60 + "\n")


def add_town_labels(ax, highlight_towns=None):
    """Add town name labels to the heatmap."""
    if not Path("ct_towns.geojson").exists():
        return

    with open("ct_towns.geojson", 'r') as f:
        towns_geojson = json.load(f)

    for feature in towns_geojson.get('features', []):
        name = feature['properties'].get('name', '').strip()
        if not name or 'not defined' in name.lower():
            continue

        geom = shape(feature['geometry'])
        centroid = geom.centroid

        # Determine label color and size
        if highlight_towns and name in highlight_towns:
            color = 'red'
            fontsize = 8
            weight = 'bold'
        else:
            color = 'black'
            fontsize = 6
            weight = 'normal'

        ax.text(centroid.x, centroid.y, name, fontsize=fontsize,
                color=color, weight=weight, ha='center', va='center',
                alpha=0.7)


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


def render_heatmap(distance_grid, extent, walked_lines=None, unwalked_lines=None, highlight_towns=None):
    """Render distance grid as heatmap with optional town boundaries."""
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

    # Draw town boundaries if provided
    if walked_lines:
        for coords in walked_lines:
            lons = [c[0] for c in coords]
            lats = [c[1] for c in coords]
            ax.plot(lons, lats, color='gray', linewidth=0.5, alpha=0.7)

    if unwalked_lines:
        for coords in unwalked_lines:
            lons = [c[0] for c in coords]
            lats = [c[1] for c in coords]
            ax.plot(lons, lats, color='darkgray', linewidth=0.5, alpha=0.7)

    # Highlight top 9 towns with largest holes
    if highlight_towns:
        highlight_lines = get_town_boundary_lines(highlight_towns)
        for coords in highlight_lines:
            lons = [c[0] for c in coords]
            lats = [c[1] for c in coords]
            ax.plot(lons, lats, color='red', linewidth=2, alpha=0.9, label='Top 9 holes' if coords == highlight_lines[0] else '')

    # Add town name labels
    add_town_labels(ax, highlight_towns)

    cbar = plt.colorbar(im, ax=ax, label='Euclidean distance (grid cells)')

    ax.set_xlabel('Longitude')
    ax.set_ylabel('Latitude')
    ax.set_title('Andy Walks Connecticut - Coverage Heatmap')

    # Add legend if highlighting towns
    if highlight_towns:
        ax.legend(loc='upper right', fontsize=10)

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

    # Print distance summary
    print_distance_summary(distance_grid)

    # Find towns with largest holes
    top_5_towns = find_towns_with_largest_holes(distance_grid)

    # Load town boundaries (optional)
    walked_lines, unwalked_lines = get_town_boundaries()

    # Render with highlighted top 5 towns
    render_heatmap(distance_grid, extent, walked_lines, unwalked_lines, top_5_towns)

    print("Done!")


if __name__ == "__main__":
    main()
