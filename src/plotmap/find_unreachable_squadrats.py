"""
Find squadrats you cannot actually reach on foot from Connecticut.

Two ways a tile can hold Connecticut ground that is no use to a walker:

  island      its only Connecticut is an island in Long Island Sound. The
              Norwalk Islands, the Greenwich islands, the Thimbles and
              Faulkners Island are all real land in real towns, and none of
              them connects to the mainland road network.

  stranded    its Connecticut roads exist, but staying inside Connecticut they
              go nowhere. These are the border slivers where the only tarmac is
              a Massachusetts, New York or Rhode Island road clipping the
              corner - you could stand on it, but not walk to it from
              Connecticut.

The island test is geometry, and it lives in ct_outline.mainland_and_islands:
the shoreline outline is a MultiPolygon and the mainland is simply its largest
part. ct_outline now drops the islands by default for everyone else, which
makes these rulings belt-and-braces rather than the only thing keeping the
Norwalk Islands out of the coverage numbers.

The stranded test is graph connectivity, done on OSM node ids rather than by
eye. Ways are cut to their runs of consecutive nodes inside Connecticut before
anything is joined up, so a road that leaves the state and comes back cannot
silently bridge two Connecticut fragments through another state. A tile is
reachable if its Connecticut roads share a component with ground already
walked - the right test here because the walks are themselves one connected
graph.

Writes proposed rulings for tile_votes.csv. Run from src/plotmap.
"""

import argparse
import csv
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
from shapely.geometry import box, Point
from shapely.strtree import STRtree
from shapely import union_all

import ct_outline
import squadrats

BORDER_CSV = "border_squadrats.csv"
ROADLESS_CSV = "roadless_squadrats.csv"
ROAD_CACHE = "road_network_cache.json"
# The main Overpass instance rate-limits and times out hard on a run of
# requests like this one, so rotate mirrors rather than hammering one.
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

# Buffer around each candidate tile, in degrees (~2 km). Wide enough that a
# genuinely connected road reaches walked ground inside the query area.
BUFFER_DEG = 0.02

# Roads nobody walks, or cannot.
SKIP_HIGHWAY = {"motorway", "motorway_link", "trunk_link", "construction",
                "proposed", "raceway"}
SKIP_ACCESS = {"private", "no"}

# How close an OSM node must be to a walked point to count as walked ground.
WALKED_SNAP_DEG = 0.0004      # ~40 m


def candidates(path=BORDER_CSV, earned=frozenset()):
    """Unwalked, unruled straddlers - the tiles still deciding themselves."""
    with open(path, newline="") as f:
        return [
            (int(r["x"]), int(r["y"]))
            for r in csv.DictReader(f)
            if not r["ruling"] and (int(r["x"]), int(r["y"])) not in earned
        ]


def query_regions(tiles, buffer_deg=BUFFER_DEG):
    """Merge buffered tile boxes so the border is fetched in a few requests."""
    boxes = []
    for x, y in tiles:
        lon_w, lon_e, lat_s, lat_n = squadrats.tile_bounds(x, y)
        boxes.append(box(lon_w - buffer_deg, lat_s - buffer_deg,
                         lon_e + buffer_deg, lat_n + buffer_deg))

    merged = union_all(boxes)
    return [g.bounds for g in getattr(merged, "geoms", [merged])]


def fetch_roads(regions, cache=ROAD_CACHE):
    """Walkable OSM ways over the given bboxes, cached on disk.

    One region per request. Batching eight at a time reliably drew a 504 from
    Overpass, and the cache is written after every region so a timeout costs
    one region rather than the whole run.
    """
    done, elements = {}, []
    if Path(cache).exists():
        with open(cache) as f:
            blob = json.load(f)
        done, elements = blob["done"], blob["elements"]
        print(f"Roads: {len(elements):,} ways cached from "
              f"{len(done)} region(s) in {cache}")

    for index, (w, s, e, n) in enumerate(regions):
        key = "{:.5f},{:.5f},{:.5f},{:.5f}".format(s, w, n, e)
        if key in done:
            continue

        query = ('[out:json][timeout:180];'
                 'way["highway"]({});out geom;'.format(key))
        print("  region {}/{}...".format(index + 1, len(regions)),
              end="", flush=True)

        attempts = 6
        for attempt in range(attempts):
            url = OVERPASS_URLS[attempt % len(OVERPASS_URLS)]
            try:
                req = urllib.request.Request(
                    url, data=query.encode(),
                    headers={"User-Agent": "walk-ct squadrat reachability"},
                )
                with urllib.request.urlopen(req, timeout=240) as resp:
                    got = json.loads(resp.read().decode())["elements"]
                elements += got
                done[key] = len(got)
                print(f" {len(got):,} ways")
                break
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt == attempts - 1:
                    raise
                wait = 10 * (attempt + 1)
                print(f" [{exc}] retry {attempt + 1} in {wait}s",
                      end="", flush=True)
                time.sleep(wait)

        with open(cache, "w") as f:
            json.dump({"done": done, "elements": elements}, f)
        time.sleep(2)          # be a good citizen on a shared public API

    print(f"Roads: {len(elements):,} ways over {len(done)} regions")
    return elements


class Components:
    """Union-find over OSM node ids."""

    def __init__(self):
        self.parent = {}

    def find(self, a):
        self.parent.setdefault(a, a)
        while self.parent[a] != a:
            self.parent[a] = self.parent[self.parent[a]]
            a = self.parent[a]
        return a

    def union(self, a, b):
        root_a, root_b = self.find(a), self.find(b)
        if root_a != root_b:
            self.parent[root_a] = root_b


def walkable(way):
    """Is this a way a person can walk, and is it drawn?"""
    tags = way.get("tags", {})
    return (
        "geometry" in way
        and "nodes" in way
        and tags.get("highway") not in SKIP_HIGHWAY
        and tags.get("access") not in SKIP_ACCESS
        and len(way["geometry"]) > 1
    )


def build_graph(ways, mainland):
    """Union node ids along each way, cut to its runs inside Connecticut.

    Returns (components, node_points), node_points mapping node id to (lon, lat)
    for the nodes that lie inside Connecticut.
    """
    comps = Components()
    node_points = {}

    for way in ways:
        if not walkable(way):
            continue

        ids = way["nodes"]
        pts = [(p["lon"], p["lat"]) for p in way["geometry"]]
        if len(ids) != len(pts):
            continue

        previous = None
        for node_id, pt in zip(ids, pts):
            if not mainland.covers(Point(pt)):
                previous = None          # the run breaks at the state line
                continue
            node_points[node_id] = pt
            if previous is not None:
                comps.union(previous, node_id)
            previous = node_id

    return comps, node_points


def walked_components(comps, node_points, walked_lat, walked_lon):
    """Component roots that contain ground already walked.

    A KD-tree over the walked points, queried for every Connecticut node in one
    vectorised call. Doing this as an STRtree of 1.75M shapely Points with a
    buffered query per node instead took long enough to look hung.
    """
    from scipy.spatial import cKDTree

    tree = cKDTree(np.column_stack([walked_lon, walked_lat]))
    ids = list(node_points)
    coords = np.array([node_points[n] for n in ids])

    near = tree.query_ball_point(coords, WALKED_SNAP_DEG, return_length=True)
    return {comps.find(ids[i]) for i in np.nonzero(near)[0]}


def write_roadless(tiles, path=ROADLESS_CSV):
    """Record tiles whose Connecticut part holds no walkable road at all.

    Not a ruling. These are still counted as squadrats - they are written out
    so the maps can draw them apart from the ordinary unwalked ones, because
    "nothing here to walk" is a different problem from "not walked yet".
    """
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["x", "y", "z", "center_lat", "center_lon"])
        for x, y in sorted(tiles):
            lon_w, lon_e, lat_s, lat_n = squadrats.tile_bounds(x, y)
            writer.writerow([x, y, squadrats.Z,
                             f"{(lat_s + lat_n) / 2:.6f}",
                             f"{(lon_w + lon_e) / 2:.6f}"])
    print(f"\nWrote {path} ({len(tiles)} tiles with no walkable road in CT)")
    return tiles


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true",
                        help="Append the rulings to tile_votes.csv "
                             "(default: report them and change nothing).")
    parser.add_argument("--boundary", default="shoreline",
                        choices=("shoreline", "towns", "state"))
    args = parser.parse_args()

    from heatmap import load_walked_coordinates

    # islands=True: every other caller wants them gone, but this script has
    # to see an island before it can rule a tile out for being one.
    outline = ct_outline.ct_outline(args.boundary, islands=True)
    mainland, islands = ct_outline.mainland_and_islands(outline)

    walked = load_walked_coordinates(snap=False)   # tile edges fall anywhere
    walked_lat = walked["lat"].to_numpy()
    walked_lon = walked["lon"].to_numpy()
    earned = squadrats.earned_tiles(walked_lat, walked_lon)
    existing = squadrats.load_votes()

    # --- island tiles: pure geometry, no road data needed -------------------
    island_tiles = []
    if islands is not None:
        for tile in squadrats.region_tiles(outline, votes={}):
            if tile in earned or tile in existing:
                continue
            lon_w, lon_e, lat_s, lat_n = squadrats.tile_bounds(*tile)
            rect = box(lon_w, lat_s, lon_e, lat_n)
            if rect.intersection(mainland).area <= 0 and rect.intersects(islands):
                island_tiles.append(tile)
    print(f"{len(island_tiles)} tiles whose only Connecticut is island")

    # --- stranded tiles: graph connectivity ---------------------------------
    tiles = [t for t in candidates(earned=earned)
             if t not in existing and t not in island_tiles]
    print(f"{len(tiles)} unwalked straddlers to test for road access")

    regions = query_regions(tiles)
    print(f"Fetching roads over {len(regions)} merged regions")
    ways = fetch_roads(regions)

    print("Building the Connecticut-only road graph...")
    comps, node_points = build_graph(ways, mainland)
    print(f"  {len(node_points):,} nodes inside Connecticut")

    reachable_roots = walked_components(comps, node_points, walked_lat, walked_lon)
    print(f"  {len(reachable_roots):,} components touch ground you have walked")

    node_ids = list(node_points)
    node_tree = STRtree([Point(node_points[n]) for n in node_ids])

    # Everything outside the queried area is invisible, so a component that
    # runs off the edge of it might reconnect just beyond and only LOOKS
    # stranded. Components that dead-end inside the area really do dead-end.
    queried = union_all([box(w, s, e, n) for w, s, e, n in regions])
    edge = queried.boundary.buffer(0.002)          # ~200 m inside the rim
    members = {}
    for node_id, pt in node_points.items():
        members.setdefault(comps.find(node_id), []).append(pt)

    stranded, reachable, roadless, unproven = [], [], [], []
    for tile in tiles:
        lon_w, lon_e, lat_s, lat_n = squadrats.tile_bounds(*tile)
        sliver = box(lon_w, lat_s, lon_e, lat_n).intersection(mainland)
        if sliver.is_empty:
            roadless.append(tile)
            continue

        in_sliver = [node_ids[i] for i in node_tree.query(sliver)
                     if sliver.covers(Point(node_points[node_ids[i]]))]
        if not in_sliver:
            roadless.append(tile)
            continue
        if any(comps.find(n) in reachable_roots for n in in_sliver):
            reachable.append(tile)
            continue

        roots = {comps.find(n) for n in in_sliver}
        if any(edge.covers(Point(p)) for r in roots for p in members[r]):
            unproven.append(tile)      # leaves the queried area; cannot say
        else:
            stranded.append(tile)

    print(f"\n  reachable from your network : {len(reachable)}")
    print(f"  stranded (no CT road access): {len(stranded)}")
    print(f"  no road in the CT part      : {len(roadless)}")
    print(f"  unproven (runs off the edge): {len(unproven)}")
    for tile in unproven:
        print(f"      {tile} - widen BUFFER_DEG and rerun to settle it")

    write_roadless(roadless)

    rulings = ([(t, "island in Long Island Sound, no mainland road access")
                for t in island_tiles]
               + [(t, "border sliver: roads here reach no Connecticut road")
                  for t in stranded])

    print(f"\n{len(rulings)} tiles to exclude:")
    for tile, why in rulings:
        lon_w, lon_e, lat_s, lat_n = squadrats.tile_bounds(*tile)
        print(f"  {str(tile):>14}  {(lat_s + lat_n) / 2:.5f},"
              f"{(lon_w + lon_e) / 2:.5f}  {why}")

    if not args.write:
        print("\n(reporting only - pass --write to record these in tile_votes.csv)")
        return

    with open(squadrats.VOTES_CSV, "a", newline="") as f:
        f.write("#\n# Unreachable on foot from Connecticut: islands in Long\n"
                "# Island Sound, and border slivers whose only roads belong to\n"
                "# another state. Found by find_unreachable_squadrats.py.\n")
        writer = csv.writer(f)
        for tile, why in rulings:
            lon_w, lon_e, lat_s, lat_n = squadrats.tile_bounds(*tile)
            writer.writerow([tile[0], tile[1], squadrats.Z, 0,
                             f"{(lat_s + lat_n) / 2:.6f}",
                             f"{(lon_w + lon_e) / 2:.6f}", why])
    print(f"\nAppended {len(rulings)} rulings to {squadrats.VOTES_CSV}")


if __name__ == "__main__":
    main()
