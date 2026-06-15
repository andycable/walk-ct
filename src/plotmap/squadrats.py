"""
Squadrats (squadrats.com) tile helpers.

A "squadrat" is a Web-Mercator slippy-map tile at zoom level 14. A tile is
"earned" if any walked GPS point falls inside it. Given a lat/lon point the
zoom-14 tile (x, y) is:

    x = floor((lon + 180) / 360 * 2^14)
    y = floor((1 - asinh(tan(lat_rad)) / pi) / 2 * 2^14)

(asinh(tan(lat)) == ln(tan(lat) + sec(lat)), the standard slippy-tile formula.)

This module computes earned tiles from walked coordinates, the unwalked tiles
that still overlap a region (e.g. the CT boundary or a single town), and draws
tile outlines onto a matplotlib axes so the heatmap colors show through.
"""

import numpy as np
from shapely import contains_xy
from matplotlib.patches import Rectangle, Patch
from matplotlib.collections import PatchCollection

# Zoom level for squadrats (squadratinhos would be 17).
Z = 14

# Outline styling.
SQUADRAT_COLOR = "#d000d0"  # magenta, stands out over the heatmap palette
SQUADRAT_LINEWIDTH = 1.5
SQUADRAT_ALPHA = 0.7


def earned_tiles(lats, lons, z=Z):
    """Return the set of (x, y) zoom-z tiles containing any of the given points."""
    lats = np.asarray(lats, dtype=float)
    lons = np.asarray(lons, dtype=float)
    n = 2 ** z

    lat_rad = np.radians(lats)
    x = np.floor((lons + 180.0) / 360.0 * n).astype(np.int64)
    y = np.floor((1.0 - np.arcsinh(np.tan(lat_rad)) / np.pi) / 2.0 * n).astype(np.int64)

    return set(zip(x.tolist(), y.tolist()))


def region_tiles(geom, z=Z, sample_step_deg=0.004):
    """Return the set of (x, y) z-tiles that overlap the given polygon.

    Overlap is approximated by densely sampling points inside the polygon and
    mapping each to its tile. sample_step_deg must be well below the tile size
    (~0.022 deg at z14) so every overlapping tile gets at least one hit.
    """
    minx, miny, maxx, maxy = geom.bounds
    lons = np.arange(minx, maxx + sample_step_deg, sample_step_deg)
    lats = np.arange(miny, maxy + sample_step_deg, sample_step_deg)
    lon_grid, lat_grid = np.meshgrid(lons, lats)

    inside = contains_xy(geom, lon_grid.ravel(), lat_grid.ravel())
    return earned_tiles(lat_grid.ravel()[inside], lon_grid.ravel()[inside], z)


def unwalked_tiles(walked_lats, walked_lons, geom, z=Z, sample_step_deg=0.004):
    """Return z-tiles overlapping geom that contain no walked point."""
    earned = earned_tiles(walked_lats, walked_lons, z)
    return region_tiles(geom, z, sample_step_deg) - earned


def _tile_lat(y, n):
    """North-edge latitude (degrees) of tile row y at 2^z = n."""
    lat_rad = np.arctan(np.sinh(np.pi * (1.0 - 2.0 * y / n)))
    return np.degrees(lat_rad)


def tile_bounds(x, y, z=Z):
    """Return (lon_west, lon_east, lat_south, lat_north) for tile (x, y)."""
    n = 2 ** z
    lon_west = x / n * 360.0 - 180.0
    lon_east = (x + 1) / n * 360.0 - 180.0
    lat_north = _tile_lat(y, n)
    lat_south = _tile_lat(y + 1, n)
    return lon_west, lon_east, lat_south, lat_north


def draw_squadrat_tiles(ax, tiles, z=Z, bbox=None,
                        edgecolor=SQUADRAT_COLOR, linewidth=SQUADRAT_LINEWIDTH,
                        alpha=SQUADRAT_ALPHA, zorder=20):
    """Draw the outlines of earned tiles onto ax.

    Args:
        ax: matplotlib axes.
        tiles: iterable of (x, y) tile coords (e.g. from earned_tiles()).
        bbox: optional (lon_min, lon_max, lat_min, lat_max) to cull tiles that
              fall entirely outside the visible area.

    Returns the number of tile outlines drawn.
    """
    n = 2 ** z
    patches = []

    for (x, y) in tiles:
        lon_w = x / n * 360.0 - 180.0
        lon_e = (x + 1) / n * 360.0 - 180.0
        lat_n = _tile_lat(y, n)
        lat_s = _tile_lat(y + 1, n)

        if bbox is not None:
            lon_min, lon_max, lat_min, lat_max = bbox
            if lon_e < lon_min or lon_w > lon_max or lat_n < lat_min or lat_s > lat_max:
                continue

        patches.append(Rectangle((lon_w, lat_s), lon_e - lon_w, lat_n - lat_s))

    if not patches:
        return 0

    pc = PatchCollection(
        patches, facecolor='none', edgecolor=edgecolor,
        linewidths=linewidth, alpha=alpha, zorder=zorder,
    )
    ax.add_collection(pc)
    return len(patches)


def legend_patch(label="Unwalked squadrat (z14)"):
    """A legend handle matching the squadrat outline style."""
    return Patch(facecolor='none', edgecolor=SQUADRAT_COLOR, label=label)
