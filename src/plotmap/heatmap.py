"""
Build a Euclidean distance heatmap from walked coordinates.

Loads all 4-decimal lat/long parquet files, builds a grid, and computes
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
from matplotlib.patches import Circle, Ellipse

# Configuration
LAT_STEP = 0.003  # Latitude grid spacing (3 units in 3:4 ratio)
LON_STEP = 0.004  # Longitude grid spacing (4 units in 3:4 ratio)
MILES_PER_DEGREE_LAT = 69.17  # Constant everywhere
MILES_PER_DEGREE_LON = 52.0   # At CT's latitude (~41-42°N)
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


def round_to_nearest_multiple_of_002(value):
    """Round to nearest .002 thousandths (.002, .004, .006, .008, etc)"""
    scaled = value * 1000
    rounded_scaled = int(np.round(scaled / 2) * 2)
    return rounded_scaled / 1000


def load_walked_coordinates():
    """Load all 4-decimal parquet files and combine, then round to even thousandths."""
    parquet_files = sorted(glob.glob("../../data/lat_long.4.*.parquet"))

    print(f"Loading {len(parquet_files)} parquet files...")
    dfs = []
    for pf in parquet_files:
        df = pd.read_parquet(pf)
        dfs.append(df)

    combined = pd.concat(dfs, ignore_index=True)

    # Round to nearest .002 thousandths (.002, .004, .006, .008, etc.)
    combined['lat'] = combined['lat'].apply(round_to_nearest_multiple_of_002)
    combined['lon'] = combined['lon'].apply(round_to_nearest_multiple_of_002)

    combined = combined.drop_duplicates(subset=['lat', 'lon']).reset_index(drop=True)

    print(f"Total unique walked coordinates: {len(combined)}")
    return combined


def build_distance_grid(walked_coords, ct_boundary):
    """
    Build a grid where each cell contains Euclidean distance to nearest walk.
    Uses 3:4 latitude:longitude ratio for square-ish cells.

    Returns:
        distance_grid: 2D array of distances in miles (np.nan outside CT)
        extent: [lon_min, lon_max, lat_min, lat_max] for imshow
    """
    lat_min, lat_max = CT_BBOX['lat_min'], CT_BBOX['lat_max']
    lon_min, lon_max = CT_BBOX['lon_min'], CT_BBOX['lon_max']

    # Grid dimensions using 3:4 latitude:longitude ratio
    rows = int(round((lat_max - lat_min) / LAT_STEP)) + 1
    cols = int(round((lon_max - lon_min) / LON_STEP)) + 1

    print(f"Grid dimensions: {rows} rows × {cols} cols (using 3:4 lat:lon ratio)")

    # Create walked mask: True where we walked, False elsewhere
    walked_mask = np.zeros((rows, cols), dtype=bool)

    for _, row in walked_coords.iterrows():
        lat, lon = row['lat'], row['lon']
        r = int(round((lat - lat_min) / LAT_STEP))
        c = int(round((lon - lon_min) / LON_STEP))
        if 0 <= r < rows and 0 <= c < cols:
            walked_mask[r, c] = True

    print(f"Walked cells marked: {walked_mask.sum()}")

    # Compute Euclidean distance from each unwalked cell to nearest walked cell
    # distance_transform_edt expects 1=background, 0=feature
    # So we invert: True (walked) -> 0 (feature), False (unwalked) -> 1 (background)
    # Use sampling to account for different lat/lon grid steps and mile conversions
    sampling = [LAT_STEP * MILES_PER_DEGREE_LAT, LON_STEP * MILES_PER_DEGREE_LON]
    distance_grid = ndimage.distance_transform_edt(~walked_mask, sampling=sampling).astype(float)

    print(f"Distance range: {distance_grid.min():.2f} to {distance_grid.max():.2f} miles")

    # Mask to CT boundary
    # Create lat/lon coordinate arrays for each grid cell using appropriate steps
    lats = np.arange(rows) * LAT_STEP + lat_min
    lons = np.arange(cols) * LON_STEP + lon_min

    lon_grid, lat_grid = np.meshgrid(lons, lats)

    # Point-in-polygon check for all grid cells
    inside_ct = contains_xy(ct_boundary, lon_grid.ravel(), lat_grid.ravel())
    inside_ct = inside_ct.reshape(distance_grid.shape)

    # Set cells outside CT to NaN
    distance_grid[~inside_ct] = np.nan

    extent = [lon_min, lon_max, lat_min, lat_max]
    return distance_grid, extent


def grid_cells_to_miles(distance_miles):
    """Pass-through function for distance values already in miles.

    The distance_transform_edt now uses sampling parameter with the 3:4 lat:lon ratio,
    so distances are already computed in miles. This function is kept for compatibility.
    """
    return distance_miles


def find_towns_with_largest_holes(distance_grid, ct_bbox=CT_BBOX):
    """Find towns with largest maximum distances (biggest unwalked holes)."""
    if not Path("ct_towns.geojson").exists():
        print("Note: ct_towns.geojson not found. Skipping town analysis.")
        return

    print("Analyzing towns for largest unwalked holes...")
    with open("ct_towns.geojson", 'r') as f:
        towns_geojson = json.load(f)

    # Build lat/lon grids for distance lookups using 3:4 ratio
    lat_min, lat_max = ct_bbox['lat_min'], ct_bbox['lat_max']
    lon_min, lon_max = ct_bbox['lon_min'], ct_bbox['lon_max']
    rows = int(round((lat_max - lat_min) / LAT_STEP)) + 1
    cols = int(round((lon_max - lon_min) / LON_STEP)) + 1

    lats = np.arange(rows) * LAT_STEP + lat_min
    lons = np.arange(cols) * LON_STEP + lon_min
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
            # Find the grid cell with the max distance
            max_idx = np.nanargmax(distance_grid[inside_town])
            max_row, max_col = np.where(inside_town)
            max_row = max_row[max_idx]
            max_col = max_col[max_idx]
            hole_lat = lats[max_row]
            hole_lon = lons[max_col]
            town_holes.append((name, max_dist, hole_lat, hole_lon))

    # Sort by max distance descending
    town_holes.sort(key=lambda x: x[1], reverse=True)

    # Print top 25
    print("\n" + "="*70)
    print("Top 25 Towns with Largest Unwalked Holes")
    print("="*70)
    print(f"{'Town':30} | {'Max Distance (miles)':>20}")
    print("-"*70)

    top_25_towns = []
    hole_centers = []
    for i, (town, max_dist_cells, hole_lat, hole_lon) in enumerate(town_holes[:25], 1):
        max_dist_miles = grid_cells_to_miles(max_dist_cells)
        print(f"{town:30} | {max_dist_miles:>20.2f}")
        top_25_towns.append(town)
        hole_centers.append((hole_lat, hole_lon, max_dist_cells))

    print("="*70 + "\n")

    return top_25_towns, hole_centers


def print_distance_summary(distance_grid):
    """Print summary of number of grid cells at each Euclidean distance (in miles)."""
    # Flatten and remove NaN values
    distances = distance_grid[~np.isnan(distance_grid)].flatten()

    if len(distances) == 0:
        print("No distance data to summarize")
        return

    # Round to 0.1 mile precision for summary
    distances_rounded = np.round(distances, 1)
    unique_distances, counts = np.unique(distances_rounded, return_counts=True)

    print("\n" + "="*65)
    print("Euclidean Distance Summary (in miles)")
    print("="*65)
    print(f"{'Distance (mi)':>15} | {'Cell Count':>15} | {'Cumulative %':>12}")
    print("-"*65)

    total = len(distances)
    cumulative = 0

    for dist, count in zip(unique_distances, counts):
        cumulative += count
        pct = (cumulative / total) * 100
        print(f"{dist:>15.1f} | {count:>15} | {pct:>11.1f}%")

    print("-"*65)
    print(f"{'TOTAL':>15} | {total:>15}")
    print("="*65 + "\n")


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


def render_heatmap(distance_grid, extent, walked_lines=None, unwalked_lines=None, highlight_towns=None, hole_centers=None):
    """Render distance grid as heatmap with optional town boundaries and hole centers."""
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

    # Highlight towns with largest holes
    if highlight_towns:
        highlight_lines = get_town_boundary_lines(highlight_towns)
        for coords in highlight_lines:
            lons = [c[0] for c in coords]
            lats = [c[1] for c in coords]
            ax.plot(lons, lats, color='red', linewidth=2, alpha=0.9, label='Top holes' if coords == highlight_lines[0] else '')

    # Mark centers of largest holes with black dots and circles
    if hole_centers:
        for hole_lat, hole_lon, max_dist_miles in hole_centers:
            # Convert distance in miles to degrees for each direction separately
            # Account for different mile-per-degree conversions
            radius_lat = max_dist_miles / MILES_PER_DEGREE_LAT
            radius_lon = max_dist_miles / MILES_PER_DEGREE_LON
            # Draw ellipse that appears as a circle on the map (accounting for 3:4 ratio)
            ellipse = Ellipse((hole_lon, hole_lat), width=2*radius_lon, height=2*radius_lat,
                            fill=False, edgecolor='black', linewidth=1.0, zorder=10)
            ax.add_patch(ellipse)
            # Draw black dot at center
            ax.plot(hole_lon, hole_lat, 'ko', markersize=4, markerfacecolor='black', markeredgecolor='black', zorder=11)

    # Add town name labels
    add_town_labels(ax, highlight_towns)

    cbar = plt.colorbar(im, ax=ax, label='Euclidean distance (miles)')

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
    print("Building Euclidean distance heatmap with 3:4 latitude:longitude ratio...")

    # Load data
    walked_coords = load_walked_coordinates()

    # Get CT boundary
    ct_boundary = get_ct_boundary()

    # Build grid with distances
    distance_grid, extent = build_distance_grid(walked_coords, ct_boundary)

    # Print distance summary
    print_distance_summary(distance_grid)

    # Find towns with largest holes
    top_towns, hole_centers = find_towns_with_largest_holes(distance_grid)

    # Load town boundaries (optional)
    walked_lines, unwalked_lines = get_town_boundaries()

    # Render with highlighted top towns and black dots at hole centers
    render_heatmap(distance_grid, extent, walked_lines, unwalked_lines, top_towns, hole_centers)

    print("Done!")


if __name__ == "__main__":
    main()
