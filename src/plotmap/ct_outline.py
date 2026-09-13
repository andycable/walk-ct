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

Three traps this module exists to keep in one place:

  - ct_towns.geojson holds five features named "County subdivisions not
    defined". They are Long Island Sound, not towns. Unioning them in adds
    325 tiles of open water.
  - the town polygons in that same file still cover each coastal town's water
    jurisdiction, which is why "towns" is not the default.
  - a plain union of those polygons raises TopologyException; the geometries
    need buffer(0) first.
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


def state_outline(path=STATE_CACHE):
    """The 16-vertex state polygon. Kept for comparison; prefer the default."""
    with open(path, "r") as f:
        return shape(json.load(f))


def town_polygons(path=TOWNS_GEOJSON):
    """[(name, polygon), ...] for the 169 real towns, Sound fillers excluded.

    These polygons include each coastal town's water jurisdiction. For a land
    outline use shoreline_polygons().
    """
    return _named_polygons(path, skip=(NOT_A_TOWN,))


def shoreline_polygons(path=SHORELINE_GEOJSON):
    """[(name, polygon), ...] for the 169 towns, clipped to the shoreline."""
    return _named_polygons(path)


def towns_outline(path=TOWNS_GEOJSON):
    """Connecticut as the union of its towns, water jurisdiction included."""
    if path not in _cache:
        _cache[path] = union_all([g for _, g in town_polygons(path)])
    return _cache[path]


def shoreline_outline(path=SHORELINE_GEOJSON):
    """Connecticut as land only. Cached per process."""
    if path not in _cache:
        _cache[path] = union_all([g for _, g in shoreline_polygons(path)])
    return _cache[path]


def ct_outline(source="shoreline"):
    """The Connecticut outline.

    source is "shoreline" (default, land only), "towns" (adds each coastal
    town's water jurisdiction) or "state" (the 16-vertex cartoon).
    """
    if source == "shoreline":
        return shoreline_outline()
    if source == "towns":
        return towns_outline()
    if source == "state":
        return state_outline()
    raise ValueError(f"unknown outline source: {source!r}")
