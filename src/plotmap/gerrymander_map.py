"""
Gerrymander plotmap of Connecticut.

A "gerrymander" is a connected component of unwalked cells (Dist >= threshold)
that does NOT touch the Connecticut border - an enclosed, irregularly shaped
pocket of streets not yet walked, resembling a gerrymandered district.

This script:
  1. Finds all interior unwalked regions (gerrymanders).
  2. Keeps the largest 100 by area.
  3. Colors them with the 4 primary colors (red, green, blue, yellow) using a
     proper greedy graph coloring so that no two nearby gerrymanders share a
     color (the "four-color map" look).
  4. Overlays the 169 Connecticut town boundaries.

Output: Gerrymander_Map.png
"""

import grid_extent

import ct_outline
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import ndimage
from scipy.spatial import Delaunay
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DISTANCE_CSV = "Distance_3_ct.csv"
# The same outlines the distance grid is clipped to. Drawing the
# water-inclusive ct_towns.geojson here instead ran the town borders out
# into Long Island Sound, past the edge of the grid they annotate.
TOWNS_GEOJSON = ct_outline.SHORELINE_GEOJSON
OUTPUT_PNG = "Gerrymander_Map.png"

GRID = 0.001                 # precision level 3 grid spacing (degrees)
UNWALKED_THRESHOLD = 0.25    # Dist >= this = unwalked (miles from nearest walked street)
TOP_N = 50                   # number of gerrymanders to show
MIN_AREA = 5                 # ignore tiny specks below this many cells
OPEN_ITERS = 1               # morphological opening passes to sever hairline bridges
                             # between otherwise-separate pockets before labeling

# The 4 primary colors (RGB 0-255)
PRIMARY_COLORS = [
    ("red",    np.array([220,  30,  30])),
    ("green",  np.array([30,  170,  60])),
    ("blue",   np.array([40,   90, 220])),
    ("yellow", np.array([245, 210,  20])),
]


def load_grid():
    """Load Distance_3 data into a distance grid and a presence mask."""
    print("Loading data...")
    df = pd.read_csv(DISTANCE_CSV, low_memory=False)
    df = df.dropna(subset=["lat", "long", "Dist"])
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["long"] = pd.to_numeric(df["long"], errors="coerce")
    df["Dist"] = pd.to_numeric(df["Dist"], errors="coerce")
    df = df.dropna()
    print(f"Loaded {len(df)} points")

    lat_min, lat_max = df["lat"].min(), df["lat"].max()
    lon_min, lon_max = df["long"].min(), df["long"].max()

    rows = int(round((lat_max - lat_min) / GRID)) + 1
    cols = int(round((lon_max - lon_min) / GRID)) + 1
    print(f"Grid size: {rows} x {cols}")

    dist_grid = np.full((rows, cols), np.nan)
    present_grid = np.zeros((rows, cols), dtype=bool)

    row_idx = np.round((df["lat"].values - lat_min) / GRID).astype(int)
    col_idx = np.round((df["long"].values - lon_min) / GRID).astype(int)
    dist_grid[row_idx, col_idx] = df["Dist"].values
    present_grid[row_idx, col_idx] = True

    extent = (lon_min, lon_max, lat_min, lat_max)
    return dist_grid, present_grid, extent


def find_gerrymanders(dist_grid, present_grid):
    """Return labeled grid plus a list of interior unwalked regions, sorted by area desc."""
    unwalked = present_grid & (dist_grid >= UNWALKED_THRESHOLD)
    print(f"Unwalked cells: {unwalked.sum()}")

    # Morphological opening (erode then dilate) severs 1-cell-wide filaments so
    # that pockets merely touching at hairline pinch points are separated into
    # distinct regions instead of one sprawling blob.
    if OPEN_ITERS > 0:
        opened = ndimage.binary_opening(unwalked, iterations=OPEN_ITERS)
        print(f"Unwalked cells after opening x{OPEN_ITERS}: {opened.sum()}")
        unwalked = opened

    labeled, num_features = ndimage.label(unwalked)
    print(f"Found {num_features} unwalked regions")

    # Border cells: present cells adjacent to a non-present cell, plus grid edges.
    border_mask = np.zeros_like(present_grid)
    for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        shifted = np.roll(np.roll(present_grid.astype(int), dr, axis=0), dc, axis=1)
        border_mask |= present_grid & (shifted == 0)
    border_mask[0, :] = present_grid[0, :]
    border_mask[-1, :] = present_grid[-1, :]
    border_mask[:, 0] = present_grid[:, 0]
    border_mask[:, -1] = present_grid[:, -1]

    border_labels = set(np.unique(labeled[border_mask]))
    border_labels.discard(0)

    regions = []
    for label_id in range(1, num_features + 1):
        if label_id in border_labels:
            continue  # interior only
        component = labeled == label_id
        area = int(component.sum())
        if area < MIN_AREA:
            continue
        ys, xs = np.where(component)
        regions.append({
            "label": label_id,
            "area": area,
            "row_center": ys.mean(),
            "col_center": xs.mean(),
            "row_min": int(ys.min()),
            "row_max": int(ys.max()),
            "col_min": int(xs.min()),
            "col_max": int(xs.max()),
        })

    regions.sort(key=lambda r: r["area"], reverse=True)
    print(f"Interior gerrymanders (>= {MIN_AREA} cells): {len(regions)}")
    return labeled, regions


def build_adjacency(regions):
    """Adjacency via Delaunay triangulation of region centroids.

    This gives each gerrymander its natural set of spatial neighbors (a planar
    graph, so 4 colors always suffice), which is what makes a proper 4-coloring
    produce an evenly varied map instead of collapsing to one color when the
    pockets are far apart.
    """
    adjacency = {r["label"]: set() for r in regions}
    if len(regions) < 3:
        # Too few points to triangulate: treat them all as mutual neighbors.
        labels = [r["label"] for r in regions]
        for a in labels:
            adjacency[a] = {b for b in labels if b != a}
        return adjacency

    pts = np.array([[r["col_center"], r["row_center"]] for r in regions])
    labels = [r["label"] for r in regions]
    tri = Delaunay(pts)
    for simplex in tri.simplices:
        for i in range(3):
            for j in range(i + 1, 3):
                a, b = labels[simplex[i]], labels[simplex[j]]
                adjacency[a].add(b)
                adjacency[b].add(a)
    return adjacency


def color_gerrymanders(regions, adjacency):
    """Greedy 4-coloring (Welsh-Powell order: highest degree first)."""
    order = sorted(regions, key=lambda r: len(adjacency[r["label"]]), reverse=True)
    assigned = {}
    n_colors = len(PRIMARY_COLORS)
    conflicts = 0
    for r in order:
        used = {assigned[n] for n in adjacency[r["label"]] if n in assigned}
        choice = next((c for c in range(n_colors) if c not in used), None)
        if choice is None:
            # More than 4 mutually-near regions; pick the least-used neighbor color.
            counts = [0] * n_colors
            for n in adjacency[r["label"]]:
                if n in assigned:
                    counts[assigned[n]] += 1
            choice = int(np.argmin(counts))
            conflicts += 1
        assigned[r["label"]] = choice
    if conflicts:
        print(f"Note: {conflicts} region(s) could not avoid all neighbor colors "
              f"(more than {n_colors} crowded together).")
    return assigned


def _rings(geom):
    """Every ring, exterior and interior, of a Polygon or MultiPolygon."""
    for part in getattr(geom, "geoms", [geom]):
        yield list(part.exterior.coords)
        for hole in part.interiors:
            yield list(hole.coords)


def load_town_lines():
    """Return list of (lons, lats) polygon rings for every CT town boundary.

    Via ct_outline, so the islands are gone: drawing them put a scatter of
    specks in Long Island Sound on a map about unwalked pockets on land.
    """
    if not Path(TOWNS_GEOJSON).exists():
        print(f"Warning: {TOWNS_GEOJSON} not found - skipping town boundaries.")
        return []
    lines = []
    for _, geom in ct_outline.shoreline_polygons(TOWNS_GEOJSON):
        for ring in _rings(geom):
            lines.append(([pt[0] for pt in ring], [pt[1] for pt in ring]))
    return lines


def _ring_centroid(ring):
    """Area-weighted (shoelace) centroid of a polygon ring; falls back to the
    vertex mean for degenerate rings."""
    pts = np.asarray(ring, dtype=float)
    if len(pts) < 3:
        return pts[:, 0].mean(), pts[:, 1].mean()
    x, y = pts[:, 0], pts[:, 1]
    x1, y1 = np.roll(x, -1), np.roll(y, -1)
    cross = x * y1 - x1 * y
    area = cross.sum() / 2.0
    if abs(area) < 1e-12:
        return x.mean(), y.mean()
    cx = ((x + x1) * cross).sum() / (6.0 * area)
    cy = ((y + y1) * cross).sum() / (6.0 * area)
    return cx, cy


def load_town_labels():
    """Return list of (name, lon, lat) at each CT town's centroid (its largest ring)."""
    if not Path(TOWNS_GEOJSON).exists():
        return []
    labels = []
    for name, geom in ct_outline.shoreline_polygons(TOWNS_GEOJSON):
        # The exterior ring of the largest-perimeter part. Islands are already
        # clipped off upstream, so this no longer has to out-vote them.
        best_ring, best_len = None, -1
        for part in getattr(geom, "geoms", [geom]):
            ring = list(part.exterior.coords)
            if len(ring) > best_len:
                best_ring, best_len = ring, len(ring)
        if best_ring is None:
            continue
        cx, cy = _ring_centroid(best_ring)
        labels.append((name, cx, cy))
    return labels


def main():
    dist_grid, present_grid, extent = load_grid()
    rows, cols = dist_grid.shape
    # load_grid returns cell CENTERS: lon_min/lat_min are the origin the row
    # and column indices are measured from, so they stay as they are. The
    # picture needs cell edges.
    lon_min, lon_max, lat_min, lat_max = extent
    img_extent = grid_extent.cell_extent(lon_min, lat_min, cols, rows,
                                         GRID, GRID)

    labeled, regions = find_gerrymanders(dist_grid, present_grid)
    regions = regions[:TOP_N]
    print(f"Showing top {len(regions)} gerrymanders by area")

    adjacency = build_adjacency(regions)
    colors = color_gerrymanders(regions, adjacency)

    # Build RGB image: white walked land, black background, colored gerrymanders.
    img = np.full((rows, cols, 3), 0, dtype=np.uint8)          # black background
    img[present_grid] = [235, 235, 235]                        # light gray = CT land
    for r in regions:
        img[labeled == r["label"]] = PRIMARY_COLORS[colors[r["label"]]][1]

    img = img[::-1]  # flip so north is up

    fig, ax = plt.subplots(1, 1, figsize=(16, 13))
    ax.imshow(img, extent=img_extent, aspect=1.4, interpolation="nearest")

    # Overlay town boundaries.
    for lons, lats in load_town_lines():
        ax.plot(lons, lats, color="#333333", linewidth=0.0625, alpha=0.7)

    # Label each town at its centroid.
    for name, lon_c, lat_c in load_town_labels():
        ax.text(lon_c, lat_c, name, fontsize=4, ha="center", va="center",
                color="black", alpha=0.85, clip_on=True)

    ax.set_xlim(img_extent[0], img_extent[1])
    ax.set_ylim(img_extent[2], img_extent[3])

    color_counts = {name: 0 for name, _ in PRIMARY_COLORS}
    for r in regions:
        color_counts[PRIMARY_COLORS[colors[r["label"]]][0]] += 1

    legend_items = [
        mpatches.Patch(color=rgb / 255, label=f"{name} ({color_counts[name]})")
        for name, rgb in PRIMARY_COLORS
    ]
    legend_items.append(mpatches.Patch(color=[235/255]*3, label="Walked land"))
    ax.legend(handles=legend_items, loc="lower right", fontsize=9,
              framealpha=0.95, title="Gerrymander color")

    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title(
        f"Andy Walks Connecticut - Top {len(regions)} Gerrymanders (Largest Unwalked Pockets)\n"
        f"4-colored so no two neighbors match",
        fontsize=14,
    )

    plt.tight_layout()
    plt.savefig(OUTPUT_PNG, dpi=150, bbox_inches="tight", pad_inches=0, facecolor="white")
    print(f"Saved {OUTPUT_PNG}")


if __name__ == "__main__":
    main()
