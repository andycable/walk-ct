"""
Gerrymander shape metrics for Connecticut.

Measures every interior unwalked pocket ("gerrymander") found by
gerrymander_map.py and ranks them five ways:

  area      - square miles of unwalked ground          -> red
  perimeter - miles of boundary around the pocket      -> green
  length    - north-south extent, in miles             -> blue
  width     - east-west extent, in miles               -> yellow
  diagonal  - longest straight line across it, miles   -> purple

Length and width come from the lat/lon bounding box: length is the N-S
extent, width the E-W extent.

Diagonal is the true maximum caliper - the longest straight line between
any two cells in the pocket, taken over its convex hull. It is the one
extent measure not tied to the axes, so a pocket that sprawls on a
diagonal reports its real reach instead of having it split between a
middling length and a middling width. It is always at least as large as
length or width, and at most the bounding box diagonal.

Everything is reported in miles, never in grid cells. The grid is 0.001
degrees on both axes, but at Connecticut's latitude that is ~111 m of
latitude against only ~83 m of longitude, so a cell is a third taller than
it is wide. Treating cells as square would inflate every E-W width by ~34%
and badly skew the width ranking.

Outputs:
  Gerrymander_Stats.csv           - every pocket, all metrics, all five ranks
  Gerrymander_Metrics_Map.png     - one CT map, each pocket in one color
  Gerrymander_Metrics_Panels.png  - one panel per metric except area, each
                                    with its true top 10 named by town
"""

import csv
from pathlib import Path

import numpy as np
from scipy import ndimage
from scipy.spatial import ConvexHull
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.patheffects as pe
from matplotlib.lines import Line2D

from gerrymander_map import (
    GRID,
    MIN_AREA,
    OPEN_ITERS,
    TOWNS_GEOJSON,
    UNWALKED_THRESHOLD,
    load_grid,
    load_town_labels,
    load_town_lines,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
STATS_CSV = "Gerrymander_Stats.csv"
MAP_PNG = "Gerrymander_Metrics_Map.png"
PANELS_PNG = "Gerrymander_Metrics_Panels.png"

TOP_K = 10                   # how many to highlight per metric

# Metric -> color. Order is also the priority order used on the single map:
# a pocket that ranks top 10 in several categories takes the first one here.
METRICS = [
    ("area",      "Area",      "sq mi", np.array([220,  30,  30])),
    ("perimeter", "Perimeter", "mi",    np.array([30,  170,  60])),
    ("length",    "Length",    "mi",    np.array([40,   90, 220])),
    ("width",     "Width",     "mi",    np.array([245, 210,  20])),
    ("diagonal",  "Diagonal",  "mi",    np.array([150,  60, 200])),
]

LAND_RGB = np.array([235, 235, 235])   # walked / measured land
BG_RGB = np.array([0, 0, 0])           # outside Connecticut


def miles_per_degree(lat_ref):
    """Miles per degree of latitude and of longitude at a given latitude.

    Standard WGS84 series expansion. Longitude shrinks by cos(lat), which is
    the whole reason this conversion has to happen before anything is measured.
    """
    phi = np.radians(lat_ref)
    m_lat = (111132.92
             - 559.82 * np.cos(2 * phi)
             + 1.175 * np.cos(4 * phi)
             - 0.0023 * np.cos(6 * phi))
    m_lon = (111412.84 * np.cos(phi)
             - 93.5 * np.cos(3 * phi)
             + 0.118 * np.cos(5 * phi))
    return m_lat / 1609.344, m_lon / 1609.344


def staircase_perimeter(mask, dx_mi, dy_mi):
    """Boundary length in miles, summed over exposed cell faces.

    Each cell face that borders a non-region cell contributes its real-world
    length: dy_mi for the east/west faces, dx_mi for the north/south faces.
    Interior holes count too, which is correct - a pocket wrapped around an
    already-walked cluster really does have that much edge.

    This is a raster staircase boundary, so it runs above a smoothed tracing
    of the same shape (up to ~27% for a diagonal edge). It is monotone with
    true perimeter, so the ranking holds.
    """
    p = np.pad(mask, 1)
    core = p[1:-1, 1:-1]
    vertical = (np.count_nonzero(core & ~p[1:-1, :-2])
                + np.count_nonzero(core & ~p[1:-1, 2:]))
    horizontal = (np.count_nonzero(core & ~p[:-2, 1:-1])
                  + np.count_nonzero(core & ~p[2:, 1:-1]))
    return vertical * dy_mi + horizontal * dx_mi


def max_caliper(mask, dx_mi, dy_mi):
    """Longest straight-line distance in miles, and the two points it runs between.

    Returns (miles, (col1, row1), (col2, row2)) with the endpoints in cell
    units relative to the mask, fractional because they sit on cell corners.
    The caller turns them into lon/lat so the segment can be drawn.

    Note this is a caliper, not a path: for a concave pocket the segment can
    leave the pocket and cross walked ground on its way between the two
    farthest-apart corners. That is what "longest diagonal" means - the
    longest line the shape spans, not the longest line fitting inside it.

    The farthest-apart pair of points in a set always lies on its convex
    hull, so the hull is taken first and the exhaustive pairwise search then
    runs over a few dozen vertices instead of the pocket's tens of thousands
    of cells. Cell indices are scaled to miles before any distance is taken,
    for the same reason the rest of this module does: a grid cell is a third
    taller than it is wide here, and treating it as square would tilt every
    diagonal toward the E-W axis.
    """
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return 0.0, None, None
    # Work in cell units so the endpoints can be mapped straight back onto the
    # grid; distances get scaled to miles before anything is compared. Hull
    # membership is unchanged by that scaling - it is an affine map - so the
    # hull can be taken on the raw indices.
    pts = np.column_stack([xs, ys]).astype(float)
    if len(pts) > 2:
        try:
            pts = pts[ConvexHull(pts).vertices]
        except Exception:
            # Degenerate hull (every cell collinear). The points are already
            # the answer set, and such a pocket is small by construction.
            pass

    # A cell is a rectangle, not a point. Length and width already count whole
    # cells, so the diagonal has to span cell footprints too, or it lands one
    # cell short on each axis and can come out below the very extents it is
    # supposed to dominate. Only hull cells can own an extreme corner - for a
    # fixed corner offset v, conv(S) + v = conv(S + v) - so expanding the hull
    # vertices alone is exact, and keeps this to a handful of points.
    ox = np.array([0.0, 1.0, 0.0, 1.0])
    oy = np.array([0.0, 0.0, 1.0, 1.0])
    corners = np.column_stack([(pts[:, 0, None] + ox).ravel(),
                               (pts[:, 1, None] + oy).ravel()])
    scaled = corners * np.array([dx_mi, dy_mi])
    diff = scaled[:, None, :] - scaled[None, :, :]
    d2 = (diff ** 2).sum(-1)
    i, j = np.unravel_index(np.argmax(d2), d2.shape)
    return float(np.sqrt(d2[i, j])), tuple(corners[i]), tuple(corners[j])


def find_border_labels(labeled, present_grid):
    """Labels touching the edge of the measured area - i.e. not interior pockets."""
    border_mask = np.zeros_like(present_grid)
    for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        shifted = np.roll(np.roll(present_grid.astype(int), dr, axis=0), dc, axis=1)
        border_mask |= present_grid & (shifted == 0)
    border_mask[0, :] = present_grid[0, :]
    border_mask[-1, :] = present_grid[-1, :]
    border_mask[:, 0] = present_grid[:, 0]
    border_mask[:, -1] = present_grid[:, -1]

    border_labels = set(np.unique(labeled[border_mask]).tolist())
    border_labels.discard(0)
    return border_labels


def build_town_lookup():
    """Return a fn(lon, lat) -> town name, or None if boundaries are unavailable."""
    if not Path(TOWNS_GEOJSON).exists():
        return None
    try:
        import json

        from shapely.geometry import Point, shape
        from shapely.strtree import STRtree
    except ImportError:
        print("Note: shapely not available - skipping town lookup.")
        return None

    with open(TOWNS_GEOJSON, "r") as f:
        gj = json.load(f)

    names, polys = [], []
    for feature in gj.get("features", []):
        name = feature.get("properties", {}).get("name")
        if not name or "not defined" in name.lower():
            continue
        try:
            geom = shape(feature["geometry"])
        except (KeyError, ValueError):
            continue
        if geom.is_empty:
            continue
        names.append(name)
        polys.append(geom)

    if not polys:
        return None
    tree = STRtree(polys)

    def lookup(lon, lat):
        pt = Point(lon, lat)
        for i in tree.query(pt):
            if polys[i].covers(pt):
                return names[i]
        return ""

    return lookup


def measure_gerrymanders(dist_grid, present_grid, extent):
    """Measure every interior unwalked pocket. Returns (labeled, regions)."""
    lon_min, lon_max, lat_min, lat_max = extent
    mi_per_lat, mi_per_lon = miles_per_degree((lat_min + lat_max) / 2)
    dy_mi = GRID * mi_per_lat          # cell height, N-S
    dx_mi = GRID * mi_per_lon          # cell width, E-W
    cell_sq_mi = dy_mi * dx_mi
    print(f"Cell size: {dy_mi * 5280:.0f} ft N-S x {dx_mi * 5280:.0f} ft E-W "
          f"({cell_sq_mi:.6f} sq mi)")

    unwalked = present_grid & (dist_grid >= UNWALKED_THRESHOLD)
    print(f"Unwalked cells: {unwalked.sum()}")
    if OPEN_ITERS > 0:
        unwalked = ndimage.binary_opening(unwalked, iterations=OPEN_ITERS)
        print(f"Unwalked cells after opening x{OPEN_ITERS}: {unwalked.sum()}")

    labeled, num_features = ndimage.label(unwalked)
    print(f"Found {num_features} unwalked regions")

    border_labels = find_border_labels(labeled, present_grid)
    town_of = build_town_lookup()

    regions = []
    for label_id, sl in enumerate(ndimage.find_objects(labeled), start=1):
        if sl is None or label_id in border_labels:
            continue
        sub = labeled[sl] == label_id
        area_cells = int(sub.sum())
        if area_cells < MIN_AREA:
            continue

        row_slice, col_slice = sl
        rows_span, cols_span = sub.shape
        ys, xs = np.nonzero(sub)
        row_center = row_slice.start + ys.mean()
        col_center = col_slice.start + xs.mean()

        area = area_cells * cell_sq_mi
        length = rows_span * dy_mi      # N-S extent
        width = cols_span * dx_mi       # E-W extent
        perimeter = staircase_perimeter(sub, dx_mi, dy_mi)
        diagonal, diag_a, diag_b = max_caliper(sub, dx_mi, dy_mi)
        diag_lon1 = lon_min + (col_slice.start + diag_a[0]) * GRID
        diag_lat1 = lat_min + (row_slice.start + diag_a[1]) * GRID
        diag_lon2 = lon_min + (col_slice.start + diag_b[0]) * GRID
        diag_lat2 = lat_min + (row_slice.start + diag_b[1]) * GRID

        centroid_lat = lat_min + row_center * GRID
        centroid_lon = lon_min + col_center * GRID

        regions.append({
            "label": label_id,
            "area": area,
            "area_cells": area_cells,
            "length": length,
            "width": width,
            "perimeter": perimeter,
            "diagonal": diagonal,
            "diag_lon1": diag_lon1,
            "diag_lat1": diag_lat1,
            "diag_lon2": diag_lon2,
            "diag_lat2": diag_lat2,
            "aspect": length / width if width else float("nan"),
            # Polsby-Popper: 1.0 is a perfect circle, near 0 is a straggly
            # tendril. The literal gerrymandering compactness score.
            "compactness": (4 * np.pi * area / perimeter ** 2) if perimeter else 0.0,
            "centroid_lat": centroid_lat,
            "centroid_lon": centroid_lon,
            "lat_min": lat_min + row_slice.start * GRID,
            "lat_max": lat_min + (row_slice.stop - 1) * GRID,
            "lon_min": lon_min + col_slice.start * GRID,
            "lon_max": lon_min + (col_slice.stop - 1) * GRID,
            "town": town_of(centroid_lon, centroid_lat) if town_of else "",
        })

    print(f"Interior gerrymanders (>= {MIN_AREA} cells): {len(regions)}")
    return labeled, regions


def rank_regions(regions):
    """Add rank_<metric> (1 = biggest) and top10_<metric> to every region.

    Ranking runs across all interior pockets, not a pre-trimmed subset, so
    the top 10 by width is the real top 10 and not just the widest of the
    biggest.
    """
    for key, _, _, _ in METRICS:
        order = sorted(regions, key=lambda r: r[key], reverse=True)
        for rank, r in enumerate(order, start=1):
            r[f"rank_{key}"] = rank
            r[f"top10_{key}"] = rank <= TOP_K


def assign_map_category(regions):
    """First-match category for the single map, in METRICS priority order."""
    for r in regions:
        r["map_category"] = ""
        for key, _, _, _ in METRICS:
            if r[f"top10_{key}"]:
                r["map_category"] = key
                break


def write_stats_csv(regions):
    columns = [
        "gid", "town",
        "area_sq_mi", "area_cells", "length_mi_ns", "width_mi_ew", "perimeter_mi",
        "diagonal_mi",
        "diag_lon1", "diag_lat1", "diag_lon2", "diag_lat2",
        "aspect_ratio_ns_ew", "polsby_popper",
        "centroid_lat", "centroid_lon",
        "lat_min", "lat_max", "lon_min", "lon_max",
        "rank_area", "rank_perimeter", "rank_length", "rank_width",
        "rank_diagonal",
        "top10_area", "top10_perimeter", "top10_length", "top10_width",
        "top10_diagonal",
        "map_category",
    ]
    ordered = sorted(regions, key=lambda r: r["area"], reverse=True)
    with open(STATS_CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(columns)
        for r in ordered:
            w.writerow([
                r["label"], r["town"],
                f"{r['area']:.6f}", r["area_cells"],
                f"{r['length']:.4f}", f"{r['width']:.4f}", f"{r['perimeter']:.4f}",
                f"{r['diagonal']:.4f}",
                f"{r['diag_lon1']:.5f}", f"{r['diag_lat1']:.5f}",
                f"{r['diag_lon2']:.5f}", f"{r['diag_lat2']:.5f}",
                f"{r['aspect']:.4f}", f"{r['compactness']:.4f}",
                f"{r['centroid_lat']:.5f}", f"{r['centroid_lon']:.5f}",
                f"{r['lat_min']:.4f}", f"{r['lat_max']:.4f}",
                f"{r['lon_min']:.4f}", f"{r['lon_max']:.4f}",
                r["rank_area"], r["rank_perimeter"], r["rank_length"],
                r["rank_width"], r["rank_diagonal"],
                int(r["top10_area"]), int(r["top10_perimeter"]),
                int(r["top10_length"]), int(r["top10_width"]),
                int(r["top10_diagonal"]),
                r["map_category"],
            ])
    print(f"Saved {STATS_CSV} ({len(ordered)} pockets)")


def print_top_tables(regions):
    for key, title, unit, _ in METRICS:
        top = sorted(regions, key=lambda r: r[key], reverse=True)[:TOP_K]
        print(f"\nTop {TOP_K} by {title.lower()} ({unit}):")
        print(f"  {'#':>2}  {'gid':>6}  {title:>10}  {'town':<20} {'also top10 in'}")
        for rank, r in enumerate(top, start=1):
            also = ", ".join(
                other_title.lower()
                for other_key, other_title, _, _ in METRICS
                if other_key != key and r[f"top10_{other_key}"]
            )
            print(f"  {rank:>2}  {r['label']:>6}  {r[key]:>10.3f}  "
                  f"{(r['town'] or '-'):<20} {also}")


def render_image(shape, present_grid, labeled, picks):
    """RGB image: black background, gray land, picked pockets in their color."""
    img = np.tile(BG_RGB.astype(np.uint8), (*shape, 1))
    img[present_grid] = LAND_RGB
    for label_id, rgb in picks:
        img[labeled == label_id] = rgb
    return img[::-1]   # flip so north is up


def draw_base(ax, img, extent, aspect, town_labels=False):
    lon_min, lon_max, lat_min, lat_max = extent
    ax.imshow(img, extent=[lon_min, lon_max, lat_min, lat_max], aspect=aspect,
              interpolation="nearest")
    for lons, lats in load_town_lines():
        ax.plot(lons, lats, color="#333333", linewidth=0.0625, alpha=0.7)
    if town_labels:
        for name, lon_c, lat_c in load_town_labels():
            ax.text(lon_c, lat_c, name, fontsize=4, ha="center", va="center",
                    color="black", alpha=0.85, clip_on=True)
    ax.set_xlim(lon_min, lon_max)
    ax.set_ylim(lat_min, lat_max)


def plot_single_map(labeled, regions, present_grid, extent, aspect):
    """One CT map. Each pocket gets exactly one color, by METRICS priority."""
    by_category = {key: [] for key, _, _, _ in METRICS}
    for r in regions:
        if r["map_category"]:
            by_category[r["map_category"]].append(r)

    picks = [(r["label"], rgb)
             for key, _, _, rgb in METRICS
             for r in by_category[key]]

    fig, ax = plt.subplots(1, 1, figsize=(16, 13))
    draw_base(ax, render_image(labeled.shape, present_grid, labeled, picks),
              extent, aspect, town_labels=True)
    draw_diagonals(ax, [r for key, _, _, _ in METRICS for r in by_category[key]])

    legend_items = []
    for key, title, unit, rgb in METRICS:
        shown = len(by_category[key])
        suffix = "" if shown == TOP_K else f" of {TOP_K}"
        legend_items.append(mpatches.Patch(
            color=rgb / 255,
            label=f"{title} ({unit}) - {shown}{suffix} shown"))
    legend_items.append(mpatches.Patch(color=LAND_RGB / 255, label="Walked land"))
    legend_items.append(Line2D([0], [0], color="black", linewidth=1.4,
                               label="Longest diagonal (mi)"))
    ax.legend(handles=legend_items, loc="lower right", fontsize=9,
              framealpha=0.95, title="Top 10 by metric")

    total = sum(len(v) for v in by_category.values())
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title(
        f"Andy Walks Connecticut - Largest Unwalked Pockets by Shape Metric\n"
        f"{total} distinct pockets; overlaps colored by priority "
        f"area > perimeter > length > width > diagonal",
        fontsize=14,
    )

    plt.tight_layout()
    plt.savefig(MAP_PNG, dpi=150, bbox_inches="tight", pad_inches=0,
                facecolor="white")
    plt.close(fig)
    print(f"Saved {MAP_PNG}")


def draw_diagonals(ax, regions, fontsize=7):
    """Draw each pocket's longest diagonal as a line, labelled with its miles.

    Stroked in white so a black line stays readable over red, green, blue,
    yellow and purple pockets alike, and over the gray land it may cross on
    the way between two corners of a concave pocket.

    The length sits at the midpoint of its own line. That puts it inside the
    pocket for a convex one and out over land for a straggly one, but always
    unambiguously on the line it measures, which matters on a map where
    twenty-one of these can be in view at once.
    """
    for r in regions:
        ax.plot([r["diag_lon1"], r["diag_lon2"]],
                [r["diag_lat1"], r["diag_lat2"]],
                color="black", linewidth=1.1, alpha=0.9,
                solid_capstyle="round", zorder=4, clip_on=True,
                path_effects=[pe.withStroke(linewidth=2.6, foreground="white")])
        ax.text((r["diag_lon1"] + r["diag_lon2"]) / 2,
                (r["diag_lat1"] + r["diag_lat2"]) / 2,
                f"{r['diagonal']:.2f}",
                fontsize=fontsize, fontweight="bold", ha="center", va="center",
                color="black", clip_on=True, zorder=6,
                path_effects=[pe.withStroke(linewidth=2.5, foreground="white")])


def label_pockets(ax, top):
    """Mark each pocket with its rank and the town its centroid falls in.

    The rank sits in a filled circle at the centroid and the town name goes
    just below it, stroked in white so it stays legible over both the colored
    pocket and the gray land behind it.
    """
    for rank, r in enumerate(top, start=1):
        ax.text(r["centroid_lon"], r["centroid_lat"], str(rank),
                fontsize=8, fontweight="bold", ha="center", va="center",
                color="white", clip_on=True, zorder=5,
                bbox=dict(boxstyle="circle,pad=0.15", facecolor="black",
                          edgecolor="none", alpha=0.75))
        if not r["town"]:
            continue
        ax.text(r["centroid_lon"], r["centroid_lat"] - 0.016, r["town"],
                fontsize=8.5, fontweight="bold", ha="center", va="top",
                color="black", clip_on=True, zorder=5,
                path_effects=[pe.withStroke(linewidth=2.5, foreground="white")])


def plot_panels(labeled, regions, present_grid, extent, aspect):
    """One full-width panel per metric, each with its own true top 10.

    Area is deliberately absent: it is the priority category on the single map
    and correlates so strongly with perimeter that its panel added little.
    """
    panels = [m for m in METRICS if m[0] != "area"]
    fig, axes = plt.subplots(len(panels), 1, figsize=(16, 11 * len(panels)))

    for ax, (key, title, unit, rgb) in zip(np.atleast_1d(axes), panels):
        top = sorted(regions, key=lambda r: r[key], reverse=True)[:TOP_K]
        picks = [(r["label"], rgb) for r in top]
        draw_base(ax, render_image(labeled.shape, present_grid, labeled, picks),
                  extent, aspect)
        draw_diagonals(ax, top, fontsize=8.5)
        label_pockets(ax, top)

        biggest, smallest = top[0][key], top[-1][key]
        ax.set_title(f"Top {TOP_K} by {title.lower()} - "
                     f"{biggest:.2f} down to {smallest:.2f} {unit}",
                     fontsize=15, color=tuple(rgb / 255 * 0.75))
        ax.set_xticks([])
        ax.set_yticks([])

    fig.suptitle("Andy Walks Connecticut - Unwalked Pockets by Perimeter, "
                 "Length, Width and Diagonal", fontsize=18, y=0.997, va="top")
    # A stacked figure is tall enough that the default suptitle slot lands on
    # top of the first panel's title, so carve the space out explicitly.
    plt.tight_layout(rect=[0, 0, 1, 1 - 0.55 / fig.get_figheight()])
    plt.savefig(PANELS_PNG, dpi=150, bbox_inches="tight", pad_inches=0.1,
                facecolor="white")
    plt.close(fig)
    print(f"Saved {PANELS_PNG}")


def main():
    dist_grid, present_grid, extent = load_grid()
    lon_min, lon_max, lat_min, lat_max = extent

    labeled, regions = measure_gerrymanders(dist_grid, present_grid, extent)
    if not regions:
        print("No interior gerrymanders found - nothing to plot.")
        return

    rank_regions(regions)
    assign_map_category(regions)

    write_stats_csv(regions)
    print_top_tables(regions)

    # True geographic aspect: latitude degrees are longer than longitude
    # degrees here, so the map has to be stretched vertically to match.
    mi_per_lat, mi_per_lon = miles_per_degree((lat_min + lat_max) / 2)
    aspect = mi_per_lat / mi_per_lon

    plot_single_map(labeled, regions, present_grid, extent, aspect)
    plot_panels(labeled, regions, present_grid, extent, aspect)


if __name__ == "__main__":
    main()
