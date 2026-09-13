"""
List every squadrat that straddles the Connecticut border.

A straddler is a z14 tile that is partly inside the state and partly outside
it. Those are the tiles where "is this square in Connecticut?" has no automatic
answer -- the Southwick Jog belongs to Massachusetts, the tile south of
Millstone Point is water plus restricted plant grounds -- so they are the
candidates for a hand ruling in tile_votes.csv.

Writes border_squadrats.csv, worst-overlap first, with the ruling (if any)
already recorded for each tile. Tiles wholly inside CT are settled and are not
listed; tiles wholly outside it are not Connecticut's problem.

This list is derived from the border geometry, so REGENERATE IT whenever the
boundary improves -- the straddler set changes with the outline. Rulings live
in tile_votes.csv and are never rewritten by this script.

Run from src/plotmap.
"""

import argparse
import csv

from shapely.geometry import box
from shapely.strtree import STRtree

import ct_outline
import squadrats

OUTPUT_CSV = "border_squadrats.csv"


def nearest_towns(tiles, source):
    """Map each tile to the town(s) it overlaps, most overlap first.

    A straddler is unadjudicable as a bare pair of tile numbers. Naming the
    town it clips makes each row a question a person can actually answer.
    """
    towns = (ct_outline.shoreline_polygons() if source == "shoreline"
             else ct_outline.town_polygons())
    names = [n for n, _ in towns]
    geoms = [g for _, g in towns]
    tree = STRtree(geoms)

    labels = {}
    for (x, y) in tiles:
        lon_w, lon_e, lat_s, lat_n = squadrats.tile_bounds(x, y)
        rect = box(lon_w, lat_s, lon_e, lat_n)

        hits = []
        for i in tree.query(rect):
            area = rect.intersection(geoms[i]).area
            if area > 0:
                hits.append((area, names[i]))

        hits.sort(reverse=True)
        labels[(x, y)] = "; ".join(n for _, n in hits[:3])

    return labels


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--boundary",
        choices=["shoreline", "towns", "state"],
        default="shoreline",
        help="Border to measure against: the shoreline-clipped town outlines "
             "(default, matches heatmap.py), the water-inclusive town union, "
             "or the old 16-vertex state outline.",
    )
    parser.add_argument("--output", default=OUTPUT_CSV,
                        help=f"CSV path (default {OUTPUT_CSV})")
    args = parser.parse_args()

    geom = ct_outline.ct_outline(args.boundary)

    straddlers = squadrats.border_tiles(geom)
    votes = squadrats.load_votes()
    towns = nearest_towns(straddlers, args.boundary)
    print(f"{len(straddlers)} tiles straddle the {args.boundary} border")

    rows = []
    for (x, y), fraction in straddlers.items():
        lon_w, lon_e, lat_s, lat_n = squadrats.tile_bounds(x, y)
        vote = votes.get((x, y))
        rows.append({
            "x": x,
            "y": y,
            "z": squadrats.Z,
            "pct_inside": round(100.0 * fraction, 2),
            "center_lat": round((lat_s + lat_n) / 2, 6),
            "center_lon": round((lon_w + lon_e) / 2, 6),
            "towns": towns[(x, y)],
            "ruling": "" if vote is None else ("in" if vote else "out"),
        })

    # Least-inside first: those are the ones most likely to deserve a ruling.
    rows.sort(key=lambda r: (r["pct_inside"], r["x"], r["y"]))

    with open(args.output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "x", "y", "z", "pct_inside", "center_lat", "center_lon", "towns",
            "ruling",
        ])
        writer.writeheader()
        writer.writerows(rows)

    ruled = sum(1 for r in rows if r["ruling"])
    print(f"Wrote {args.output} ({len(rows)} tiles, {ruled} ruled, "
          f"{len(rows) - ruled} still on geometry alone)")

    for label, lo, hi in [("under 5% inside", 0, 5), ("5-25% inside", 5, 25),
                          ("25-50% inside", 25, 50), ("over 50% inside", 50, 101)]:
        n = sum(1 for r in rows if lo <= r["pct_inside"] < hi)
        print(f"  {label:>16}: {n}")

    report_rulings_off_the_list(straddlers, votes, geom)


def report_rulings_off_the_list(straddlers, votes, geom):
    """Flag rulings on tiles this border does not consider borderline.

    A ruling is not wrong just because its tile is not a straddler -- the tile
    south of Millstone Point is 100% inside Waterford and still needs to be
    voted out. But a ruling that merely repeats what the geometry already says
    is dead weight, and one that contradicts it is worth seeing. Either way it
    will not appear in the CSV, so say so here.
    """
    off_list = [t for t in votes if t not in straddlers]
    if not off_list:
        return

    print()
    print(f"{len(off_list)} ruling(s) on tiles this border does not call borderline:")
    for (x, y) in sorted(off_list):
        lon_w, lon_e, lat_s, lat_n = squadrats.tile_bounds(x, y)
        rect = box(lon_w, lat_s, lon_e, lat_n)
        pct = 100.0 * rect.intersection(geom).area / rect.area
        ruling = "in" if votes[(x, y)] else "out"
        if pct >= 99.9999:
            verdict = "geometry says fully IN -- the ruling is doing real work"
        elif pct <= 0.0001:
            verdict = "geometry says fully OUT -- the ruling is redundant"
        else:
            verdict = "unexpected: partial overlap but not listed"
        print(f"  ({x},{y}) ruled {ruling:>3}, {pct:6.2f}% inside: {verdict}")


if __name__ == "__main__":
    main()
