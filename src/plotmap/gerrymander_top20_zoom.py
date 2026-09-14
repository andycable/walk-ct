"""
Zoomed panel view of the top 20 Connecticut gerrymanders.

Companion to gerrymander_map.py. Detects the same interior unwalked pockets,
takes the 20 largest by area, 4-colors them, and renders a 5x4 grid of panels
- each cropped to one gerrymander's bounding box (with padding) so its shape
and the surrounding town boundaries are clearly visible.

Output: Gerrymander_Top20_Zoom.png
"""

import numpy as np

import grid_extent
import matplotlib.pyplot as plt

from gerrymander_map import (
    GRID,
    PRIMARY_COLORS,
    load_grid,
    find_gerrymanders,
    build_adjacency,
    color_gerrymanders,
    load_town_lines,
    load_town_labels,
)

TOP_N = 20
N_COLS = 4
N_ROWS = 5
OUTPUT_PNG = "Gerrymander_Top20_Zoom.png"


def main():
    dist_grid, present_grid, extent = load_grid()
    rows, cols = dist_grid.shape
    # Cell centers - the origin for the row/column arithmetic below. The
    # picture itself is drawn on the cell edges.
    lon_min, lon_max, lat_min, lat_max = extent
    img_extent = grid_extent.cell_extent(lon_min, lat_min, cols, rows,
                                         GRID, GRID)

    labeled, regions = find_gerrymanders(dist_grid, present_grid)
    regions = regions[:TOP_N]
    print(f"Zooming into top {len(regions)} gerrymanders by area")

    adjacency = build_adjacency(regions)
    colors = color_gerrymanders(regions, adjacency)

    # Build the full colored image once; each panel reuses it with cropped axes.
    img = np.zeros((rows, cols, 3), dtype=np.uint8)   # black background
    img[present_grid] = [235, 235, 235]               # light gray = CT land
    for r in regions:
        img[labeled == r["label"]] = PRIMARY_COLORS[colors[r["label"]]][1]
    img = img[::-1]  # flip so north is up

    town_lines = load_town_lines()
    town_labels = load_town_labels()

    fig, axes = plt.subplots(N_ROWS, N_COLS, figsize=(16, 20))
    axes = axes.ravel()

    for i, r in enumerate(regions):
        ax = axes[i]
        ax.imshow(img, extent=img_extent, aspect=1.4, interpolation="nearest")

        # Bounding box of this gerrymander in lat/lon.
        r_lat_min = lat_min + r["row_min"] * GRID
        r_lat_max = lat_min + r["row_max"] * GRID
        r_lon_min = lon_min + r["col_min"] * GRID
        r_lon_max = lon_min + r["col_max"] * GRID

        # Pad by 40% of the larger span so context towns are visible.
        span = max(r_lat_max - r_lat_min, r_lon_max - r_lon_min)
        pad = max(0.008, span * 0.4)

        for lons, lats in town_lines:
            ax.plot(lons, lats, color="#333333", linewidth=0.075, alpha=0.75)

        x_lo, x_hi = r_lon_min - pad, r_lon_max + pad
        y_lo, y_hi = r_lat_min - pad, r_lat_max + pad
        ax.set_xlim(x_lo, x_hi)
        ax.set_ylim(y_lo, y_hi)

        # Label towns whose centroid falls within this panel's view.
        for name, lon_t, lat_t in town_labels:
            if x_lo <= lon_t <= x_hi and y_lo <= lat_t <= y_hi:
                ax.text(lon_t, lat_t, name, fontsize=6, ha="center", va="center",
                        color="black", alpha=0.85, clip_on=True)

        lat_c = lat_min + r["row_center"] * GRID
        lon_c = lon_min + r["col_center"] * GRID
        color_name = PRIMARY_COLORS[colors[r["label"]]][0]
        ax.set_title(f"#{i+1}  area={r['area']} cells  [{color_name}]\n"
                     f"({lat_c:.3f}, {lon_c:.3f})", fontsize=9)
        ax.tick_params(labelsize=7)

    # Hide any unused panels (there are none for 20 into 5x4, but be safe).
    for j in range(len(regions), len(axes)):
        axes[j].axis("off")

    fig.suptitle(
        "Andy Walks Connecticut - Top 20 Gerrymanders (Largest Unwalked Pockets), Zoomed",
        fontsize=16, y=0.995,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.99])
    plt.savefig(OUTPUT_PNG, dpi=140, bbox_inches="tight", facecolor="white")
    print(f"Saved {OUTPUT_PNG}")


if __name__ == "__main__":
    main()
