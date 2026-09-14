"""
Export squadrats (zoom-14 slippy tiles) as GeoJSON for interactive maps.

A squadrat is "earned" if any walked GPS point falls inside it (see
squadrats.py for the tile math). This script computes the earned and unwalked
tiles overlapping Connecticut, tags each one with the town it mostly sits in,
and writes:

    squadrats_z14.geojson   tile polygons (unwalked by default)
    squadrats_by_town.csv   earned/unwalked counts per town

The GeoJSON loads directly into CalTopo, Gaia GPS, geojson.io or Google My
Maps, and is embedded into the standalone map by squadrats_map.py.

Run from src/plotmap (walked coordinates are globbed from ../../data).
"""

import argparse
import csv
import json
from collections import Counter

from shapely.geometry import shape, box
from shapely.strtree import STRtree

import ct_outline
import squadrats
from heatmap import load_walked_coordinates

TOWNS_GEOJSON = "ct_towns.geojson"
OUTPUT_GEOJSON = "squadrats_z14.geojson"
OUTPUT_CSV = "squadrats_by_town.csv"

# Tiles whose center falls outside every town polygon (offshore, or in the
# slivers where the town outlines and the state outline disagree).
NO_TOWN = "(no town)"


def load_towns(source="shoreline"):
    """Return [(town_name, polygon), ...] for the 169 towns.

    Labels come from whichever file the tiles were clipped to. Labelling with
    a different file than the clip leaves tiles that belong to no town at all:
    clipping to the shoreline while labelling from ct_towns.geojson stranded 14
    of them in "(no town)".
    """
    towns = (ct_outline.shoreline_polygons() if source == "shoreline"
             else ct_outline.town_polygons())
    print(f"Loaded {len(towns)} town boundaries for the {source} outline")
    return towns


def assign_towns(tiles, towns):
    """Map each (x, y) tile to the town it overlaps most.

    Tiles straddle town lines constantly at z14, so "which town is this
    square in" is decided by area of overlap, not by the center point.
    """
    geoms = [g for _, g in towns]
    names = [n for n, _ in towns]
    tree = STRtree(geoms)

    assigned = {}
    for (x, y) in tiles:
        lon_w, lon_e, lat_s, lat_n = squadrats.tile_bounds(x, y)
        rect = box(lon_w, lat_s, lon_e, lat_n)

        best_name, best_area = NO_TOWN, 0.0
        for i in tree.query(rect):
            area = rect.intersection(geoms[i]).area
            if area > best_area:
                best_name, best_area = names[i], area

        assigned[(x, y)] = best_name

    return assigned


def tile_feature(x, y, status, town):
    """Build a GeoJSON polygon feature for one tile."""
    lon_w, lon_e, lat_s, lat_n = squadrats.tile_bounds(x, y)
    return {
        "type": "Feature",
        "properties": {
            "x": x,
            "y": y,
            "z": squadrats.Z,
            "status": status,
            "town": town,
            "center_lat": round((lat_s + lat_n) / 2, 6),
            "center_lon": round((lon_w + lon_e) / 2, 6),
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [round(lon_w, 6), round(lat_s, 6)],
                [round(lon_e, 6), round(lat_s, 6)],
                [round(lon_e, 6), round(lat_n, 6)],
                [round(lon_w, 6), round(lat_n, 6)],
                [round(lon_w, 6), round(lat_s, 6)],
            ]]
        },
    }


def write_town_csv(earned_towns, unwalked_towns, path=OUTPUT_CSV):
    """Write per-town earned/unwalked squadrat counts, worst coverage first."""
    earned_counts = Counter(earned_towns.values())
    unwalked_counts = Counter(unwalked_towns.values())

    rows = []
    for town in sorted(set(earned_counts) | set(unwalked_counts)):
        earned = earned_counts[town]
        unwalked = unwalked_counts[town]
        total = earned + unwalked
        rows.append({
            "Town": town,
            "Earned": earned,
            "Unwalked": unwalked,
            "Total": total,
            "PctEarned": round(100.0 * earned / total, 1) if total else 0.0,
        })

    rows.sort(key=lambda r: (r["PctEarned"], -r["Unwalked"]))

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["Town", "Earned", "Unwalked", "Total", "PctEarned"]
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {path} ({len(rows)} towns)")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--boundary",
        choices=["shoreline", "towns", "state"],
        default="shoreline",
        help="Clip tiles to the shoreline-clipped town outlines (default, "
             "matches heatmap.py), the water-inclusive town union, or the old "
             "16-vertex state outline.",
    )
    parser.add_argument(
        "--include-earned",
        action="store_true",
        help="Also write earned tiles to the GeoJSON (default: unwalked only).",
    )
    parser.add_argument(
        "--output", default=OUTPUT_GEOJSON, help=f"GeoJSON path (default {OUTPUT_GEOJSON})"
    )
    args = parser.parse_args()

    towns = load_towns(args.boundary)
    geom = ct_outline.ct_outline(args.boundary)
    print(f"Clipping to the {args.boundary} outline")

    # snap=False: tile membership is decided at the raw coordinate, since a
    # z14 tile edge can fall anywhere and rounding can cross one.
    walked = load_walked_coordinates(snap=False)

    earned_all = squadrats.earned_tiles(walked["lat"], walked["lon"])
    region = squadrats.region_tiles(geom)
    earned = region & earned_all
    unwalked = region - earned_all

    pct = 100.0 * len(earned) / len(region) if region else 0.0
    print(f"z{squadrats.Z} tiles overlapping CT: {len(region):,}")
    print(f"  earned:   {len(earned):,} ({pct:.1f}%)")
    print(f"  unwalked: {len(unwalked):,}")

    earned_towns = assign_towns(earned, towns)
    unwalked_towns = assign_towns(unwalked, towns)

    features = [
        tile_feature(x, y, "unwalked", unwalked_towns[(x, y)])
        for (x, y) in sorted(unwalked)
    ]
    if args.include_earned:
        features += [
            tile_feature(x, y, "earned", earned_towns[(x, y)])
            for (x, y) in sorted(earned)
        ]

    fc = {
        "type": "FeatureCollection",
        "properties": {
            "zoom": squadrats.Z,
            "boundary": args.boundary,
            "tiles_in_region": len(region),
            "earned": len(earned),
            "unwalked": len(unwalked),
        },
        "features": features,
    }

    with open(args.output, "w") as f:
        json.dump(fc, f)

    print(f"Wrote {args.output} ({len(features):,} features)")
    write_town_csv(earned_towns, unwalked_towns)


if __name__ == "__main__":
    main()
