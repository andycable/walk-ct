"""
Distance-from-walked, computed directly from the parquet activity data.

Replaces the SQL Server leg of the pipeline. Previously Distance_3_ct.csv came
from dbo.Distance_3_snapshot via get_data.bat + clip_to_ct.py, fed by
all.3.uniq.csv - a lineage that stalled in February 2026. This reads the
monthly parquet files that do_current_month.bat maintains and computes the same
quantity locally, so nothing depends on the obsolete database.

What Distance_3_snapshot actually held, verified against the Feb 2026 file:

  * A 0.001-degree lattice of cell centers (values of the form X.XXX5) clipped
    to Connecticut.
  * Cells containing a walked point are OMITTED entirely - there is not a
    single zero in the file, and the walked set and the grid share no cells.
  * Dist is the distance in miles from the cell center to the nearest walked
    point. Reproducing it with a KD-tree matched the stored values to r=0.99999
    with a worst case of 66 ft, the residual being geodesic-vs-planar.

This script reproduces that contract exactly, so it is a drop-in for the
downstream gerrymander scripts.

Usage:
  python distance_from_parquet.py                        # all months, 5-decimal
  python distance_from_parquet.py --until 2026-02 \
      --precision 3 --out Distance_3_ct.validate.csv     # replicate the SQL run
  python distance_from_parquet.py --boundary towns       # better CT outline
"""

import argparse
import glob
import json
from pathlib import Path

import numpy as np

import ct_outline
import pandas as pd
from matplotlib.path import Path as MplPath
from scipy.spatial import cKDTree

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"

GRID = 0.001                 # lattice spacing in degrees
STATE_BOUNDARY = "ct_boundary.json"
TOWNS_GEOJSON = "ct_towns.geojson"
DEFAULT_OUT = "Distance_3_ct.csv"


def miles_per_degree(lat_ref):
    """Miles per degree of latitude and of longitude at a given latitude.

    Standard WGS84 series expansion. Longitude shrinks by cos(lat), so a
    0.001-degree cell in Connecticut is 364 ft tall but only 274 ft wide;
    distances have to be computed in miles, never in degrees or cells.
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


def cell_center(values):
    """Snap coordinates to the center of their 0.001-degree cell (X.XXX5)."""
    return np.floor(values / GRID) * GRID + GRID / 2


def load_walked(until=None, precision=5):
    """Unique walked coordinates from the monthly lat_long parquet files.

    precision 5 uses the coordinates as recorded. precision 3 snaps them to the
    0.001 lattice first, which is what the old Lat_Long_3 table held and what
    the --until validation run needs to match.
    """
    files = sorted(glob.glob(str(DATA_DIR / "lat_long.5.*.parquet")))
    if not files:
        raise SystemExit(f"No lat_long.5.*.parquet under {DATA_DIR}. "
                         "Run do_current_month.bat first.")
    if until:
        cutoff = until.replace("-", "_")
        files = [f for f in files if Path(f).stem.split(".")[-1] <= cutoff]
    print(f"Reading {len(files)} monthly files"
          + (f" through {until}" if until else ""))

    frames = [pd.read_parquet(f) for f in files]
    walked = pd.concat(frames, ignore_index=True)
    print(f"  {len(walked)} points")

    if precision == 3:
        walked["lat"] = cell_center(walked["lat"].values)
        walked["lon"] = cell_center(walked["lon"].values)
    walked = walked.drop_duplicates()
    print(f"  {len(walked)} unique at {precision}-decimal precision")
    return walked


def load_boundary(which):
    """Connecticut outline as a list of (exterior, holes) ring arrays.

    The outline itself comes from ct_outline, so this script, heatmap.py and
    the squadrat exports all clip to the same Connecticut. It used to read the
    16-vertex ct_boundary.json, and its own "towns" option unioned every
    feature in ct_towns.geojson - Long Island Sound fillers included.
    """
    geom = ct_outline.ct_outline(which)

    polys = list(getattr(geom, "geoms", [geom]))
    rings = [(np.asarray(p.exterior.coords),
              [np.asarray(r.coords) for r in p.interiors]) for p in polys]

    print(f"Boundary: {which} outline -> {len(polys)} part(s), "
          f"{sum(len(e) for e, _ in rings)} vertices")
    return rings


def build_lattice(rings):
    """Every 0.001-degree cell center inside the boundary."""
    all_pts = np.vstack([e for e, _ in rings])
    lon_min, lat_min = all_pts.min(axis=0)
    lon_max, lat_max = all_pts.max(axis=0)

    lats = np.arange(cell_center(np.array(lat_min)), lat_max + GRID, GRID)
    lons = np.arange(cell_center(np.array(lon_min)), lon_max + GRID, GRID)
    lon_g, lat_g = np.meshgrid(lons, lats)
    pts = np.column_stack([lon_g.ravel(), lat_g.ravel()])
    print(f"Lattice: {len(lats)} x {len(lons)} = {len(pts)} candidate cells")

    inside = np.zeros(len(pts), dtype=bool)
    for exterior, holes in rings:
        inside |= MplPath(exterior).contains_points(pts)
        for hole in holes:
            inside &= ~MplPath(hole).contains_points(pts)
    pts = pts[inside]
    print(f"  {len(pts)} inside Connecticut")
    return pts[:, 1], pts[:, 0]      # lat, lon


def compute(lat, lon, walked):
    """Nearest walked point, in miles, for every lattice cell."""
    mi_lat, mi_lon = miles_per_degree(float(lat.mean()))
    tree = cKDTree(np.column_stack([walked["lat"].values * mi_lat,
                                    walked["lon"].values * mi_lon]))
    print(f"KD-tree over {len(walked)} walked points; "
          f"querying {len(lat)} cells...")
    dist, _ = tree.query(np.column_stack([lat * mi_lat, lon * mi_lon]),
                         k=1, workers=-1)
    return dist


def drop_walked_cells(lat, lon, dist, walked):
    """Omit cells that contain a walked point, matching the SQL snapshot."""
    def keys(la, lo):
        return (np.round(la * 10000).astype(np.int64) * 10_000_000
                + np.round(lo * 10000).astype(np.int64))

    walked_keys = np.unique(keys(cell_center(walked["lat"].values),
                                 cell_center(walked["lon"].values)))
    keep = ~np.isin(keys(lat, lon), walked_keys)
    print(f"Dropping {(~keep).sum()} walked cells, keeping {keep.sum()}")
    return lat[keep], lon[keep], dist[keep]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--until", help="only months <= YYYY-MM (for validation)")
    ap.add_argument("--precision", type=int, choices=(3, 5), default=5,
                    help="5 = coordinates as recorded (default); "
                         "3 = snapped to the 0.001 lattice, as the SQL did")
    ap.add_argument("--boundary", choices=("shoreline", "towns", "state"),
                    default="shoreline",
                    help="shoreline = town outlines clipped to the coast "
                         "(default, matches heatmap.py); towns = adds each "
                         "coastal town's water jurisdiction; state = the old "
                         "16-point outline")
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()

    walked = load_walked(args.until, args.precision)
    lat, lon = build_lattice(load_boundary(args.boundary))
    dist = compute(lat, lon, walked)
    lat, lon, dist = drop_walked_cells(lat, lon, dist, walked)

    out = pd.DataFrame({"lat": np.round(lat, 4),
                        "long": np.round(lon, 4),
                        "Dist": np.round(dist, 4)})
    out.to_csv(args.out, index=False, float_format="%.4f")
    print(f"\nSaved {args.out}: {len(out)} cells")
    print(f"  Dist min {out.Dist.min():.4f}  median {out.Dist.median():.4f}  "
          f"max {out.Dist.max():.4f}")
    for t in (0.25, 0.5):
        print(f"  cells >= {t} mi from walked: {(out.Dist >= t).sum()}")


if __name__ == "__main__":
    main()
