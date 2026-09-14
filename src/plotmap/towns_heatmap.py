"""
Generate individual heatmaps for each of Connecticut's 169 towns.

For each town, creates a distance-based heatmap showing walked coverage
(white=walked, green<1mi, orange 1-1.8mi, red>1.8mi) cropped to the town boundary.
Saves as towns/{Town_Name}_heatmap.png.
"""

import argparse
import json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy import ndimage
from shapely.geometry import shape
from shapely import contains_xy
import glob
from pathlib import Path
import logging
from datetime import datetime
import osmnx as ox
from matplotlib.patches import Patch
import squadrats

import coverage_bands
import ct_outline
import grid_extent

# Configuration (5x5 grid subdivision)
LAT_STEP = 0.0006
LON_STEP = 0.0008
MILES_PER_DEGREE_LAT = 69.17
MILES_PER_DEGREE_LON = 52.0
CT_BBOX = {
    'lat_min': 41.00,
    'lat_max': 42.05,
    'lon_min': -73.73,
    'lon_max': -71.79,
}



def get_ct_boundary(source="shoreline"):
    """The Connecticut outline used to clip the grid and the squadrat tiles.

    Defaults to the shoreline-clipped town outlines, matching heatmap.py. This
    used to read the 16-vertex ct_boundary.json, whose straight-line coast cut
    inland of the real shore in places - which mattered most for exactly the
    coastal towns this script draws one by one.
    """
    return ct_outline.ct_outline(source)


def round_to_nearest_multiple_of_0001(value):
    """Round to nearest .0001 (5-digit precision)."""
    scaled = value * 10000
    rounded_scaled = int(np.round(scaled))
    return rounded_scaled / 10000


def snap_coordinates(walked):
    """Round a walked frame to the 0.0001-degree lattice and de-duplicate."""
    out = pd.DataFrame({'lat': np.round(walked['lat'], 4),
                        'lon': np.round(walked['lon'], 4)})
    return out.drop_duplicates(subset=['lat', 'lon']).reset_index(drop=True)


def load_walked_coordinates(snap=True):
    """Every walked coordinate from the monthly parquet files, de-duplicated.

    snap=True rounds to the nearest 0.0001 degree, which is safe for the
    distance grid (cells are 0.0012 x 0.0016 degrees, so a point cannot leave
    its own cell) and collapses 6.9M points to 1.8M. Squadrat callers pass
    snap=False: a z14 tile edge can fall anywhere, so the rounding can carry a
    point across one. See heatmap.load_walked_coordinates.
    """
    parquet_files = sorted(glob.glob("../../data/lat_long.5.*.parquet"))

    print(f"Loading {len(parquet_files)} parquet files...")
    dfs = []
    for pf in parquet_files:
        df = pd.read_parquet(pf)
        dfs.append(df)

    combined = pd.concat(dfs, ignore_index=True)

    if snap:
        combined['lat'] = np.round(combined['lat'], 4)
        combined['lon'] = np.round(combined['lon'], 4)

    combined = combined.drop_duplicates(subset=['lat', 'lon']).reset_index(drop=True)

    print(f"Total unique walked coordinates: {len(combined)}")
    return combined


def load_month_coordinates(month_str):
    """Load the 5-decimal parquet file for a single month (e.g. '2026_06').

    Returns a DataFrame of unique rounded lat/lon for that month, or None if
    no parquet file exists for the month.
    """
    parquet_path = f"../../data/lat_long.5.{month_str}.parquet"
    if not Path(parquet_path).exists():
        return None

    df = pd.read_parquet(parquet_path)
    df['lat'] = df['lat'].apply(round_to_nearest_multiple_of_0001)
    df['lon'] = df['lon'].apply(round_to_nearest_multiple_of_0001)
    df = df.drop_duplicates(subset=['lat', 'lon']).reset_index(drop=True)

    print(f"Loaded {len(df)} unique coordinates for {month_str} from {parquet_path}")
    return df


def towns_with_new_activity(month_coords, towns_geojson):
    """Return the set of town names that contain at least one of month_coords."""
    if month_coords is None or len(month_coords) == 0:
        return set()

    lon_pts = month_coords['lon'].to_numpy()
    lat_pts = month_coords['lat'].to_numpy()

    changed = set()
    for feature in towns_geojson.get('features', []):
        name = feature['properties'].get('name', '').strip()
        if not name or 'not defined' in name.lower():
            continue
        geom = shape(feature['geometry'])
        if contains_xy(geom, lon_pts, lat_pts).any():
            changed.add(name)

    return changed


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

    # Cell edges, not the bbox this grid was cut from. See grid_extent.
    extent = grid_extent.cell_extent(lon_min, lat_min, cols, rows,
                                     LON_STEP, LAT_STEP)
    return distance_grid, extent, rows, cols


def get_town_streets(town_geom, town_name, logger):
    """Fetch street network for a town from OpenStreetMap."""
    try:
        import time
        logger.info(f"  [START] Fetching streets for {town_name}")
        start_time = time.time()

        # Fetch street network from geometry polygon
        logger.info(f"  [QUERY] graph_from_polygon() starting")
        G = ox.graph_from_polygon(town_geom, network_type='all', simplify=True)
        query_time = time.time()
        logger.info(f"  [QUERY] graph_from_polygon() completed in {query_time - start_time:.2f}s")

        # Extract street edges as line coordinates
        logger.info(f"  [EXTRACT] Extracting street coordinates")
        streets = []
        for u, v, data in G.edges(data=True):
            if 'geometry' in data:
                coords = list(data['geometry'].coords)
            else:
                coords = [(G.nodes[u]['x'], G.nodes[u]['y']), (G.nodes[v]['x'], G.nodes[v]['y'])]
            if len(coords) >= 2:
                streets.append(coords)

        elapsed = time.time() - start_time
        logger.info(f"  [END] Found {len(streets)} street segments in {elapsed:.2f}s")
        return streets
    except Exception as e:
        logger.warning(f"  [ERROR] Could not fetch streets: {e}")
        return []


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


def render_town_heatmap(town_grid, extent, town_geom, town_name, output_path, streets=None, squadrat_tiles=None):
    """Render a single town's heatmap with quarter-mile color bands and street overlay."""
    fig, ax = plt.subplots(figsize=(12, 12))

    # Flip for display
    town_grid_flipped = town_grid[::-1]

    # Same quarter-mile bands as the statewide map, from coverage_bands.
    rgb_grid = coverage_bands.rgb_grid(town_grid)

    # Flip for display
    rgb_grid = rgb_grid[::-1]

    im = ax.imshow(
        rgb_grid,
        extent=extent,
        aspect='equal',
        interpolation='nearest'
    )

    # Draw streets if available
    if streets:
        for coords in streets:
            if len(coords) >= 2:
                lons = [c[0] for c in coords]
                lats = [c[1] for c in coords]
                ax.plot(lons, lats, color='darkgray', linewidth=0.7, alpha=0.8)

    # Draw town boundary
    boundary_lines = get_town_boundary_lines([town_name])
    if boundary_lines:
        for coords in boundary_lines:
            lons = [c[0] for c in coords]
            lats = [c[1] for c in coords]
            ax.plot(lons, lats, color='black', linewidth=1.0, alpha=0.8)

    # Draw unwalked squadrats tile outlines, culled to this town's extent
    if squadrat_tiles:
        squadrats.draw_squadrat_tiles(ax, squadrat_tiles, bbox=extent)

    # Create custom legend for distance bands
    legend_elements = coverage_bands.legend_patches()
    if squadrat_tiles:
        legend_elements.append(squadrats.legend_patch())
    # Place the color key in a single row along the top, above the plot,
    # so it never covers the town.
    ax.legend(handles=legend_elements, loc='lower center',
              bbox_to_anchor=(0.5, 1.02), ncol=len(legend_elements),
              fontsize=8, framealpha=0.95, columnspacing=1.0,
              handletextpad=0.4, borderaxespad=0.0)

    ax.set_xlabel('Longitude')
    ax.set_ylabel('Latitude')
    ax.set_title(f'{town_name} - Coverage Heatmap', pad=28)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()


def main():
    parser = argparse.ArgumentParser(
        description="Generate per-town coverage heatmaps for Connecticut."
    )
    parser.add_argument(
        "--current-month",
        action="store_true",
        help="Only regenerate heatmaps for towns with new activity in the "
             "current month's data (lat_long.5.YYYY_MM.parquet).",
    )
    parser.add_argument(
        "--month",
        metavar="YYYY_MM",
        default=None,
        help="With --current-month, use this month instead of today's month "
             "(e.g. 2026_05).",
    )
    parser.add_argument(
        "--no-squadrats",
        action="store_true",
        help="Do not overlay earned squadrats (z14) tile outlines.",
    )
    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    logger = logging.getLogger(__name__)

    logger.info("Starting per-town heatmap generation...")
    print("Generating per-town heatmaps...")

    # Load data once
    logger.info("Loading walked coordinates...")
    walked_raw = load_walked_coordinates(snap=False)
    ct_boundary = get_ct_boundary()

    # Compute UNWALKED squadrats (z14) once: tiles overlapping CT with no walked
    # point. Drawn per town by culling to each town's extent. Decided on the
    # unsnapped coordinates, since a tile edge can fall anywhere.
    squadrat_tiles = None
    if not args.no_squadrats:
        squadrat_tiles = squadrats.unwalked_tiles(
            walked_raw['lat'].to_numpy(), walked_raw['lon'].to_numpy(),
            ct_boundary,
        )
        logger.info(f"{len(squadrat_tiles)} unwalked squadrat (z{squadrats.Z}) tiles in CT")
    logger.info("Building distance grid...")
    walked_coords = snap_coordinates(walked_raw)
    distance_grid, full_extent, rows, cols = build_distance_grid(walked_coords, ct_boundary)
    logger.info("Distance grid complete")

    # Create output directory
    Path("towns").mkdir(exist_ok=True)

    # Load town geometries
    if not Path("ct_towns.geojson").exists():
        print("Error: ct_towns.geojson not found")
        return

    with open("ct_towns.geojson", 'r') as f:
        towns_geojson = json.load(f)

    # Optionally restrict to towns with new activity this month.
    changed_towns = None
    if args.current_month:
        month_str = args.month or datetime.now().strftime("%Y_%m")
        logger.info(f"Filtering to towns with new activity in {month_str}...")
        month_coords = load_month_coordinates(month_str)
        if month_coords is None:
            logger.warning(
                f"No parquet file found for {month_str}; nothing to regenerate."
            )
            print(f"No data file for {month_str}; nothing to do.")
            return
        changed_towns = towns_with_new_activity(month_coords, towns_geojson)
        logger.info(f"{len(changed_towns)} town(s) have new activity in {month_str}")
        print(f"{len(changed_towns)} town(s) with new activity in {month_str}: "
              f"{', '.join(sorted(changed_towns)) if changed_towns else '(none)'}")
        if not changed_towns:
            return

    # Process each town
    town_count = 0
    rendered_count = 0
    for feature in towns_geojson.get('features', []):
        name = feature['properties'].get('name', '').strip()
        if not name or 'not defined' in name.lower():
            continue

        # Skip towns without new activity when filtering by current month.
        if changed_towns is not None and name not in changed_towns:
            continue

        town_count += 1
        logger.info(f"[{town_count:3d}] Starting {name}")

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

        # Edges of the sliced block. This used to run from the center of the
        # first cell to one whole step past the center of the last: the right
        # width, but half a cell too far north and east.
        town_extent = grid_extent.cell_extent(
            CT_BBOX['lon_min'] + c_min * LON_STEP,
            CT_BBOX['lat_min'] + r_min * LAT_STEP,
            c_max - c_min + 1, r_max - r_min + 1, LON_STEP, LAT_STEP)

        # Fetch streets for this town
        streets = get_town_streets(geom, name, logger)

        # Generate filename and render
        filename = name.replace(' ', '_').replace('/', '_')
        output_path = f"towns/{filename}_heatmap.png"

        print(f"  [{town_count:3d}] {name:30s} -> {filename}_heatmap.png")

        render_town_heatmap(town_grid, town_extent, geom, name, output_path, streets, squadrat_tiles)
        rendered_count += 1
        logger.info(f"[{town_count:3d}] Completed {name}")

    logger.info(f"Completed! Generated {rendered_count} town heatmaps in towns/ folder")
    print(f"\nGenerated {rendered_count} town heatmaps in towns/ folder")


if __name__ == "__main__":
    main()
