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

import csv
import os

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

# Fill styling for contiguous regions of 2+ unwalked tiles.
CLUSTER_FILL_COLOR = "#d000d0"  # same hue as the outlines, translucent fill
CLUSTER_FILL_ALPHA = 0.22       # low enough that the heatmap reads through
CLUSTER_LABEL_FONTSIZE = 7

# Subjective per-tile include/exclude decisions, resolved next to this module
# so it is found no matter what the working directory is.
VOTES_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tile_votes.csv")


def earned_tiles(lats, lons, z=Z):
    """Return the set of (x, y) zoom-z tiles containing any of the given points."""
    lats = np.asarray(lats, dtype=float)
    lons = np.asarray(lons, dtype=float)
    n = 2 ** z

    lat_rad = np.radians(lats)
    x = np.floor((lons + 180.0) / 360.0 * n).astype(np.int64)
    y = np.floor((1.0 - np.arcsinh(np.tan(lat_rad)) / np.pi) / 2.0 * n).astype(np.int64)

    return set(zip(x.tolist(), y.tolist()))


def region_tiles(geom, z=Z, sample_step_deg=0.004, votes=None):
    """Return the set of (x, y) z-tiles that overlap the given polygon.

    A tile counts if any part of it overlaps geom, measured exactly.
    sample_step_deg is accepted for backwards compatibility and ignored.

    votes overrides the geometry for tiles a human has ruled on. It defaults to
    whatever load_votes() finds in VOTES_CSV, so every caller gets the rulings
    without asking; pass votes={} to ignore the file and see the raw geometry.
    """
    tiles = {t for t, _ in _overlapping(geom, z).items()}

    return apply_votes(tiles, load_votes(z=z) if votes is None else votes)


def _overlapping(geom, z=Z):
    """{(x, y): fraction_inside} for every tile with any overlap with geom.

    Measured exactly. This used to sample points on a 0.004 deg lattice, which
    silently dropped 39 tiles whose sliver of Connecticut happened to contain
    no sample point -- tiles that border_squadrats.csv listed for adjudication
    but that never appeared on any map, so ruling on them did nothing.
    """
    from shapely.geometry import box

    minx, miny, maxx, maxy = geom.bounds
    x_lo, y_lo = tile_at(maxy, minx, z)
    x_hi, y_hi = tile_at(miny, maxx, z)

    found = {}
    for x in range(x_lo, x_hi + 1):
        for y in range(y_lo, y_hi + 1):
            lon_w, lon_e, lat_s, lat_n = tile_bounds(x, y, z)
            rect = box(lon_w, lat_s, lon_e, lat_n)
            overlap = rect.intersection(geom).area
            if overlap > 0:
                found[(x, y)] = overlap / rect.area

    return found


def unwalked_tiles(walked_lats, walked_lons, geom, z=Z, sample_step_deg=0.004,
                   votes=None):
    """Return z-tiles overlapping geom that contain no walked point."""
    earned = earned_tiles(walked_lats, walked_lons, z)
    return region_tiles(geom, z, sample_step_deg, votes) - earned


def load_votes(path=VOTES_CSV, z=Z):
    """Load subjective include/exclude decisions as {(x, y): bool}.

    The geometric clip cannot settle every border tile -- the Southwick Jog is
    Massachusetts sticking into Connecticut, and the tile south of Millstone
    Point is 100% inside Waterford's polygon but is open water plus restricted
    plant grounds. Those are judgment calls, so they live in a file a human
    edits rather than in geometry.

    A missing file is not an error: it just means no overrides.
    """
    if not os.path.exists(path):
        return {}

    votes = {}
    with open(path, "r", newline="") as f:
        rows = csv.DictReader(line for line in f if not line.lstrip().startswith("#"))
        for row in rows:
            if int(row["z"]) != z:
                continue
            votes[(int(row["x"]), int(row["y"]))] = bool(int(row["include"]))

    return votes


def apply_votes(tiles, votes):
    """Apply include/exclude votes to a geometrically-derived tile set.

    Votes win over the geometry in both directions: a tile voted out is dropped
    even if the polygon contains it, and a tile voted in is added even if the
    polygon does not.
    """
    tiles = set(tiles)
    tiles -= {t for t, include in votes.items() if not include}
    tiles |= {t for t, include in votes.items() if include}
    return tiles


def tile_at(lat, lon, z=Z):
    """Return the (x, y) tile containing a single lat/lon point."""
    return next(iter(earned_tiles([lat], [lon], z)))


def border_tiles(geom, z=Z, full=0.999999):
    """Return {(x, y): fraction_inside} for tiles that straddle geom's edge.

    A straddler is a tile that is partly inside Connecticut and partly outside
    it -- the tiles where "is this square in CT?" has no automatic answer and a
    human ruling in tile_votes.csv may be needed.

    Unlike region_tiles(), which samples points, this measures each tile's
    overlap exactly, so tiles that only clip a corner of the boundary are not
    missed. Tiles at or above `full` are counted as wholly inside and omitted,
    as are tiles with no overlap at all.
    """
    return {t: f for t, f in _overlapping(geom, z).items() if f < full}


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


def legend_patch(label="Unwalked tile"):
    """A legend handle matching the squadrat outline style."""
    return Patch(facecolor='none', edgecolor=SQUADRAT_COLOR, label=label)


def cluster_tiles(tiles, min_size=2):
    """Group tiles into contiguous (edge-connected) regions.

    Tiles touching only at a corner are not contiguous. Returns a list of tile
    lists, largest region first, keeping only regions of at least min_size
    tiles.
    """
    remaining = set(tiles)
    regions = []

    while remaining:
        region = [remaining.pop()]
        stack = list(region)
        while stack:
            x, y = stack.pop()
            for neighbor in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    region.append(neighbor)
                    stack.append(neighbor)

        if len(region) >= min_size:
            regions.append(region)

    regions.sort(key=len, reverse=True)
    return regions


def draw_squadrat_clusters(ax, regions, z=Z, bbox=None,
                           facecolor=CLUSTER_FILL_COLOR, alpha=CLUSTER_FILL_ALPHA,
                           fontsize=CLUSTER_LABEL_FONTSIZE, zorder=19):
    """Fill each contiguous region and label it with its tile count.

    Args:
        ax: matplotlib axes.
        regions: iterable of tile lists (e.g. from cluster_tiles()).
        bbox: optional (lon_min, lon_max, lat_min, lat_max) to cull regions
              that fall entirely outside the visible area.

    Returns the number of regions drawn.
    """
    patches = []
    drawn = 0

    for region in regions:
        boxes = [tile_bounds(x, y, z) for (x, y) in region]

        if bbox is not None:
            lon_min, lon_max, lat_min, lat_max = bbox
            if all(lon_e < lon_min or lon_w > lon_max or lat_n < lat_min or lat_s > lat_max
                   for lon_w, lon_e, lat_s, lat_n in boxes):
                continue

        for lon_w, lon_e, lat_s, lat_n in boxes:
            patches.append(Rectangle((lon_w, lat_s), lon_e - lon_w, lat_n - lat_s))

        # Place the count on the tile nearest the region centroid rather than at
        # the centroid itself -- for an L- or U-shaped region the centroid can
        # land on tiles that are not part of it.
        centers = [((lon_w + lon_e) / 2.0, (lat_s + lat_n) / 2.0)
                   for lon_w, lon_e, lat_s, lat_n in boxes]
        cx = sum(c[0] for c in centers) / len(centers)
        cy = sum(c[1] for c in centers) / len(centers)
        label_lon, label_lat = min(
            centers, key=lambda c: (c[0] - cx) ** 2 + (c[1] - cy) ** 2
        )

        ax.text(label_lon, label_lat, str(len(region)), fontsize=fontsize,
                color='black', weight='bold', ha='center', va='center',
                bbox=dict(boxstyle='round,pad=0.15', facecolor='white',
                          alpha=0.75, edgecolor='none'),
                zorder=zorder + 2)
        drawn += 1

    if patches:
        ax.add_collection(PatchCollection(
            patches, facecolor=facecolor, edgecolor='none',
            alpha=alpha, zorder=zorder,
        ))

    return drawn


def cluster_legend_patch(label="Unwalked grid"):
    """A legend handle matching the cluster fill style."""
    return Patch(facecolor=CLUSTER_FILL_COLOR, alpha=CLUSTER_FILL_ALPHA,
                 edgecolor=SQUADRAT_COLOR, label=label)


def _main():
    """Look up the tile for a point and print a ready-to-paste vote row."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--at", nargs=2, type=float, metavar=("LAT", "LON"),
                        required=True, help="Point to look up.")
    parser.add_argument("--include", type=int, choices=(0, 1), default=0,
                        help="Vote to emit: 0 excludes the tile (default), 1 includes it.")
    parser.add_argument("--note", default="", help="Reason, recorded in the CSV row.")
    args = parser.parse_args()

    lat, lon = args.at
    x, y = tile_at(lat, lon)
    lon_w, lon_e, lat_s, lat_n = tile_bounds(x, y)

    votes = load_votes()
    current = votes.get((x, y))
    print(f"tile ({x}, {y}) at z{Z}")
    print(f"  lon {lon_w:.6f} .. {lon_e:.6f}")
    print(f"  lat {lat_s:.6f} .. {lat_n:.6f}")
    print(f"  existing vote: {'include' if current else 'exclude' if current is not None else 'none'}")
    print("\nrow for tile_votes.csv:")
    print(f'{x},{y},{Z},{args.include},'
          f'{(lat_s + lat_n) / 2:.6f},{(lon_w + lon_e) / 2:.6f},"{args.note}"')


if __name__ == "__main__":
    _main()
