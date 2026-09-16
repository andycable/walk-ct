"""
The Connecticut outline, in one place.

Three outlines of the state live here and they disagree materially:

  shoreline  ct_towns_shoreline.geojson, the Census cartographic boundary
             file, CLIPPED TO THE SHORELINE. 169 towns, land only. The
             default, and the only one of the three that is right at the coast.
  towns      the union of the 169 town polygons in ct_towns.geojson. A real
             land border, but coastal towns hold jurisdiction out to the state
             line in mid-Sound, so Stamford's polygon contains open water three
             miles offshore and this outline pulls in ~55 tiles of Long Island
             Sound.
  state      ct_boundary.json, from the PublicaMundi us-states file. SIXTEEN
             vertices. The entire south coast is five straight lines, so it
             runs out into the Sound in places and cuts inland in others.

Measured at zoom 14, the cartoon includes 31 tiles lying in no Connecticut town
and omits 127 that do - wrong in both directions, and the larger error is the
one that silently hides unwalked ground. Switching to "towns" fixes the land
border but trades that error for open water. "shoreline" has neither problem,
so it is the default and the others must be asked for by name.

ISLANDS ARE EXCLUDED BY DEFAULT. The shoreline outline is a MultiPolygon of
eleven parts: the mainland, at 5,000 sq mi, and ten islands totalling 1.8 -
the Norwalk Islands, the Greenwich islands, the Thimbles, Charles Island and a
handful of specks. They are real Connecticut land in real Connecticut towns and
not one of them connects to the mainland road network, so no walker can reach
them and nothing that measures walking progress should count them. Left in,
they put 498 cells into the 0.001-degree distance lattice and hand the "how far
is Connecticut from somewhere I have walked" answer to Chimon Island, 2.38 mi
out in the Sound, when the true mainland answer is 1.67.

Pass islands=True to get them back. find_unreachable_squadrats.py does, because
it has to see an island before it can rule a tile out for being one.

The island test is geometry: the mainland is simply the largest part. That
works because the gap is unambiguous - the nearest island is 0.07 mi offshore
and the mainland is four orders of magnitude larger than the biggest of them.

Four traps this module exists to keep in one place:

  - ct_towns.geojson holds five features named "County subdivisions not
    defined". They are Long Island Sound, not towns. Unioning them in adds
    325 tiles of open water.
  - the town polygons in that same file still cover each coastal town's water
    jurisdiction, which is why "towns" is not the default.
  - a plain union of those polygons raises TopologyException; the geometries
    need buffer(0) first.
  - islands have to be dropped from the UNION, never town by town. A town's
    own largest part is not the mainland: clip each town separately and any
    town the generalized boundary happens to split in two loses its smaller
    half, which is dry land. So the mainland is found once, globally, and the
    coastal towns are intersected with it.
  - ct_towns.geojson IS MISSING MADISON. The file carries a feature named
    Madison, but it is a 0.005 sq mi sliver at -72.601, 41.266, and nothing in
    the file covers the actual town - the shoreline file has it correctly at
    36.7 sq mi. Clipping to the mainland would therefore delete Madison from
    the "towns" source outright, so _drop_islands keeps a town it cannot clip
    and says so. Another reason "towns" is not the default.
"""

import json
import os

from shapely.geometry import shape
from shapely import union_all

_HERE = os.path.dirname(os.path.abspath(__file__))

STATE_CACHE = os.path.join(_HERE, "ct_boundary.json")
TOWNS_GEOJSON = os.path.join(_HERE, "ct_towns.geojson")
SHORELINE_GEOJSON = os.path.join(_HERE, "ct_towns_shoreline.geojson")

# Source for SHORELINE_GEOJSON, should it ever need refreshing:
#   import geopandas as gpd
#   gpd.read_file(SHORELINE_URL).to_crs(4326)[["NAME", "geometry"]] \
#      .rename(columns={"NAME": "name"}).to_file(SHORELINE_GEOJSON, driver="GeoJSON")
SHORELINE_URL = (
    "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_09_cousub_500k.zip"
)

# Census filler polygons covering Long Island Sound. Named, but not towns.
NOT_A_TOWN = "County subdivisions not defined"

_cache = {}


def _named_polygons(path, skip=()):
    """[(name, polygon), ...] from a GeoJSON of named town features."""
    with open(path, "r") as f:
        fc = json.load(f)

    return [
        (feat["properties"]["name"], shape(feat["geometry"]).buffer(0))
        for feat in fc["features"]
        if feat["properties"].get("name") and feat["properties"]["name"] not in skip
    ]


def _union(named):
    """Union of [(name, polygon), ...]. buffer(0) was applied on load."""
    return union_all([g for _, g in named])


def state_outline(path=STATE_CACHE):
    """The 16-vertex state polygon. Kept for comparison; prefer the default."""
    with open(path, "r") as f:
        return shape(json.load(f))


def mainland_and_islands(outline):
    """Split an outline into (mainland polygon, union of the islands or None).

    The mainland is the largest part. See the module docstring for why that
    crude-looking test is the right one here.
    """
    parts = sorted(getattr(outline, "geoms", [outline]), key=lambda p: -p.area)
    return parts[0], (union_all(parts[1:]) if len(parts) > 1 else None)


def _drop_islands(named, outline):
    """Clip [(name, polygon), ...] to the mainland of `outline`.

    Only the towns that actually touch an island are intersected - the other
    160-odd are returned untouched, which keeps this off the critical path for
    every inland town, and keeps their geometry bit-for-bit what it was.

    A town with no mainland at all is KEPT, with a warning. Connecticut has no
    island-only town, so that case means the town list and the geometry
    disagree, and silently returning 168 towns would bury it. See the fifth
    trap in the module docstring.
    """
    mainland, islands = mainland_and_islands(outline)
    if islands is None:
        return named

    clipped = []
    for name, g in named:
        if g.intersects(islands):
            land = g.intersection(mainland)
            if land.is_empty:
                print(f"WARNING: {name} has no mainland in this outline - "
                      f"keeping it unclipped. Its polygon is wrong, not its "
                      f"island-ness; no Connecticut town is all island.")
            else:
                g = land
        clipped.append((name, g))
    return clipped


def town_polygons(path=TOWNS_GEOJSON, islands=False):
    """[(name, polygon), ...] for the 169 real towns, Sound fillers excluded.

    These polygons include each coastal town's water jurisdiction. For a land
    outline use shoreline_polygons().

    islands=False, the default, clips the coastal towns to the mainland. On
    this source that is very nearly a no-op: the water jurisdiction already
    joins the islands to the shore, so there is barely an island left to drop.
    """
    named = _named_polygons(path, skip=(NOT_A_TOWN,))
    return named if islands else _drop_islands(named, _union(named))


def shoreline_polygons(path=SHORELINE_GEOJSON, islands=False):
    """[(name, polygon), ...] for the 169 towns, clipped to the shoreline.

    islands=False, the default, also clips them to the mainland, so Norwalk
    stops carrying Chimon and Sheffield and Greenwich stops carrying Great
    Captain. No town disappears: every one of the ten has mainland too.
    """
    named = _named_polygons(path)
    return named if islands else _drop_islands(named, _union(named))


def towns_outline(path=TOWNS_GEOJSON, islands=False):
    """Connecticut as the union of its towns, water jurisdiction included.

    Union first, then take the mainland - never the other way round. See the
    fourth trap in the module docstring.
    """
    key = (path, islands)
    if key not in _cache:
        outline = _union(_named_polygons(path, skip=(NOT_A_TOWN,)))
        _cache[key] = outline if islands else mainland_and_islands(outline)[0]
    return _cache[key]


def shoreline_outline(path=SHORELINE_GEOJSON, islands=False):
    """Connecticut as land only. Cached per process.

    islands=False, the default, returns the mainland alone - a single Polygon
    rather than the eleven-part MultiPolygon of the raw file.
    """
    key = (path, islands)
    if key not in _cache:
        outline = _union(_named_polygons(path))
        _cache[key] = outline if islands else mainland_and_islands(outline)[0]
    return _cache[key]


def ct_outline(source="shoreline", islands=False):
    """The Connecticut outline.

    source is "shoreline" (default, land only), "towns" (adds each coastal
    town's water jurisdiction) or "state" (the 16-vertex cartoon).

    islands=False, the default, drops the ten offshore parts: they are land
    nobody can walk to, and counting them distorts every coverage and distance
    number downstream. Pass islands=True only if you need to reason ABOUT the
    islands - the "state" cartoon has none either way.
    """
    if source == "shoreline":
        return shoreline_outline(islands=islands)
    if source == "towns":
        return towns_outline(islands=islands)
    if source == "state":
        return state_outline()
    raise ValueError(f"unknown outline source: {source!r}")
