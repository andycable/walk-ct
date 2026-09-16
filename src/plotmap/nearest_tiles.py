"""
Build the spatial tiles behind connecticut-ultrawalker/.

The page answers "how close have I walked to this address", which needs the
walked points themselves - a distance grid gives the distance from a CELL
CENTRE, which at the 0.001 degree lattice is up to 230 ft wrong, and the whole
question lives in the 0-500 ft range. So the points ship whole, cut into tiles
the browser can fetch a handful of.

Everything comes from activities/activities_*.parquet rather than
data/lat_long.5.*.parquet, because that is the copy that still carries
activity_id and activity_date - the "when, and on which walk" half of the
answer. The coordinates are the same points, rounded here to 4 decimals.

Layout, all of it little-endian:

    connecticut-ultrawalker/tiles/<t>.bin
        uint32  n
        n x uint8   dlat    0..199, steps of 1e-4 deg north of the tile origin
        n x uint8   dlon    0..199, steps of 1e-4 deg east of the tile origin
        n x uint16  act     index into index.json's activities array
        n x uint8   visits  distinct activities that touched the cell, capped

    connecticut-ultrawalker/tiles/index.json
        grid geometry, the list of non-empty tile numbers, and the activity
        table (id, date, name).

Points are deduped to 4 decimals - about 11 m, comfortably inside GPS noise -
and each surviving cell keeps its EARLIEST visit, so the page can say "first
walked on ..." rather than picking an arbitrary one of 40 passes.

Usage:
  python nearest_tiles.py
  python nearest_tiles.py --out ../../connecticut-ultrawalker/tiles
"""

import argparse
import glob
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
ACTIVITY_GLOB = str(REPO_ROOT / "activities" / "activities_*.parquet")
DEFAULT_OUT = REPO_ROOT / "connecticut-ultrawalker" / "tiles"

# Connecticut plus a buffer. The buffer is not cosmetic: the nearest walked
# point to a Greenwich or Enfield address is regularly over the state line, and
# clipping to the boundary would report a longer distance than the truth.
BBOX = (40.70, 42.30, -74.00, -71.50)   # south, north, west, east

STEP = 1e-4          # coordinate resolution, ~11 m
TILE = 0.02          # tile size in degrees, ~1.4 mi tall x 1.0 mi wide
CELLS = int(round(TILE / STEP))          # 200, so offsets fit in a uint8

# Strava ids are 10-11 digits. One activity in the set has a 4-digit id and no
# Strava page behind it; the page only links out above this.
MIN_STRAVA_ID = 1_000_000_000


def load_points():
    """Walked points inside the buffered bbox, with their activity and date."""
    files = sorted(glob.glob(ACTIVITY_GLOB))
    if not files:
        raise SystemExit(f"No activity parquet files matched {ACTIVITY_GLOB}")

    cols = ["activity_id", "activity_date", "lat", "lon", "activity_name"]
    frames = []
    for f in files:
        df = pd.read_parquet(f, columns=cols)
        south, north, west, east = BBOX
        m = ((df.lat >= south) & (df.lat <= north)
             & (df.lon >= west) & (df.lon <= east))
        frames.append(df[m])
    df = pd.concat(frames, ignore_index=True)
    df = df.dropna(subset=["activity_id", "lat", "lon"])
    print(f"{len(files)} monthly files -> {len(df):,} points in the bbox")
    return df


def activity_table(df):
    """One row per activity, and the per-point index into it.

    Sorted by date then id, so index order is chronological and 'earliest
    visit' is just the smallest index - which is what lets the dedupe below be
    a sort rather than a groupby.

    Chronological order also keeps next month's rebuild cheap in git: a new
    walk appends a new index and leaves every existing one alone, so only the
    tiles it actually crossed change bytes. BACKFILLING an old activity is the
    exception - it shifts every later index and rewrites all 3,343 tiles.
    """
    meta = (df[["activity_id", "activity_date", "activity_name"]]
            .drop_duplicates("activity_id")
            .sort_values(["activity_date", "activity_id"])
            .reset_index(drop=True))
    if len(meta) > 65535:
        raise SystemExit(f"{len(meta)} activities will not fit a uint16 index")

    code = pd.Series(meta.index.values, index=meta.activity_id.values)
    idx = df.activity_id.map(code).to_numpy(dtype=np.int64)

    rows = []
    for aid, date, name in meta.itertuples(index=False):
        name = "" if pd.isna(name) else str(name).strip()
        # The FIT half of the archive is named after the activity id, which
        # tells a reader nothing the date and the link do not already say.
        if name.endswith(".fit") and name[:-4].isdigit():
            name = ""
        rows.append([int(aid), str(date), name])
    print(f"{len(rows):,} activities, {rows[0][1]} to {rows[-1][1]}")
    return rows, idx


def dedupe(lat, lon, act):
    """Collapse to 4-decimal cells, keeping the earliest activity and a count.

    Returns (ilat, ilon, act, visits) with one entry per distinct cell, where
    ilat/ilon are integer counts of STEP.
    """
    ilat = np.rint(lat / STEP).astype(np.int64)
    ilon = np.rint(lon / STEP).astype(np.int64)

    # ilon is negative in Connecticut; the offset keeps the packed key
    # monotonic in ilon so sorting by key sorts by cell.
    key = (ilat << 24) | (ilon + 8_000_000)

    # Sort by cell, then by activity index - which is chronological - so the
    # first row of each run is the earliest visit to that cell.
    order = np.lexsort((act, key))
    key, act_s = key[order], act[order]

    starts = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
    first_act = act_s[starts]

    # Distinct activities per cell: a new (cell, activity) pair starts a run in
    # the same sorted order, so counting run starts per cell counts visits.
    new_pair = np.r_[True, (key[1:] != key[:-1]) | (act_s[1:] != act_s[:-1])]
    visits = np.add.reduceat(new_pair.astype(np.int64), starts)

    ukey = key[starts]
    out_lat = ukey >> 24
    out_lon = (ukey & 0xFFFFFF) - 8_000_000
    print(f"{len(lat):,} points -> {len(ukey):,} distinct cells at {STEP} deg")
    return out_lat, out_lon, first_act, visits


def write_tiles(ilat, ilon, act, visits, out_dir):
    """One file per non-empty tile, plus the geometry the page needs."""
    south, north, west, east = BBOX
    i0 = int(np.floor(south / TILE))
    j0 = int(np.floor(west / TILE))
    n_rows = int(np.floor(north / TILE)) - i0 + 1
    n_cols = int(np.floor(east / TILE)) - j0 + 1

    ti = ilat // CELLS - i0
    tj = ilon // CELLS - j0
    if ti.min() < 0 or tj.min() < 0 or ti.max() >= n_rows or tj.max() >= n_cols:
        raise SystemExit("a point fell outside the tile grid")
    tile = ti * n_cols + tj

    # Offsets within the tile. Both are 0..CELLS-1 by construction, so a uint8
    # holds them and a point costs 2 bytes of geometry instead of 8.
    dlat = (ilat - (ti + i0) * CELLS).astype(np.uint8)
    dlon = (ilon - (tj + j0) * CELLS).astype(np.uint8)

    order = np.argsort(tile, kind="stable")
    tile, dlat, dlon = tile[order], dlat[order], dlon[order]
    act, visits = act[order], visits[order]

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    starts = np.flatnonzero(np.r_[True, tile[1:] != tile[:-1]])
    ends = np.r_[starts[1:], len(tile)]
    total = 0
    for s, e in zip(starts, ends):
        n = e - s
        buf = (np.uint32(n).tobytes()
               + dlat[s:e].tobytes()
               + dlon[s:e].tobytes()
               + act[s:e].astype("<u2").tobytes()
               + np.minimum(visits[s:e], 255).astype(np.uint8).tobytes())
        (out_dir / f"{tile[s]}.bin").write_bytes(buf)
        total += len(buf)

    n_tiles = len(starts)
    print(f"{n_tiles:,} tiles, {total / 1e6:.1f} MB, "
          f"{total / n_tiles / 1024:.1f} KB average")
    return {
        "lat0": i0 * TILE, "lon0": j0 * TILE,
        "rows": n_rows, "cols": n_cols,
        "tile": TILE, "step": STEP, "cells": CELLS,
        "minStravaId": MIN_STRAVA_ID,
        "tiles": sorted(int(t) for t in tile[starts]),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(DEFAULT_OUT),
                    help="tile output directory")
    args = ap.parse_args()

    df = load_points()
    activities, act_idx = activity_table(df)
    ilat, ilon, act, visits = dedupe(
        df.lat.to_numpy(), df.lon.to_numpy(), act_idx)

    out_dir = Path(args.out)
    meta = write_tiles(ilat, ilon, act.astype(np.int64), visits, out_dir)
    meta["activities"] = activities
    meta["points"] = int(len(ilat))

    index = out_dir / "index.json"
    index.write_text(json.dumps(meta, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {index} ({index.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
