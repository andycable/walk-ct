"""
Fetch Connecticut town (county subdivision) boundaries from Census Bureau.

Downloads TIGER/Line data and converts to GeoJSON format.
Saves as ct_towns.geojson for use in heatmap.py

A SHAPEFILE PART IS NOT A GEOJSON RING. This script used to assume it was:
it walked shape.parts and appended every one to a single Polygon's coordinate
list. In GeoJSON the rings after the first are HOLES, so any record with more
than one part came out as its first part with the rest punched out of it.

Connecticut has exactly one town that this wrecks, and it wrecked it totally.
Madison is two parts in TIGER 2023 - a 0.005 sq mi sliver at -72.601, 41.266
and the actual 36.6 sq mi town - and both rings are clockwise, which in the
shapefile convention means both are EXTERIOR. It is a MultiPolygon. Treating
part 1 as a hole in part 0 left ct_towns.geojson with a Madison that was only
the sliver, and no feature in the file covering the town at all: every point
lookup over downtown Madison landed in no town.

pyshp already gets this right, so the parts loop is gone and the geometry now
comes from shape.__geo_interface__, which returns Polygon or MultiPolygon as
the record actually warrants.
"""

import json
import zipfile
import urllib.request
import io
from pathlib import Path

# Census Bureau TIGER/Line 2023 county subdivisions (towns) for Connecticut (09)
# File structure: tl_2023_09_cousub.zip (09 = Connecticut FIPS code)
CENSUS_URL = (
    "https://www2.census.gov/geo/tiger/TIGER2023/COUSUB/"
    "tl_2023_09_cousub.zip"
)
TEMP_SHAPEFILE = "tl_2023_09_cousub"
OUTPUT_GEOJSON = "ct_towns.geojson"


def fetch_and_convert():
    """Convert the Census TIGER/Line county subdivisions to GeoJSON.

    Uses tl_2023_09_cousub.* if it is already here - those three files are
    committed - and only goes to the Census when it is not. Re-downloading a
    file the repo already carries is a slow way to get the same bytes.
    """
    try:
        import shapefile
    except ImportError:
        print("ERROR: pyshp not installed. Install with: pip install pyshp")
        print("Alternative: Download ct_towns.geojson from GitHub manually")
        return False

    downloaded = False
    if Path(f"{TEMP_SHAPEFILE}.shp").exists():
        print(f"Using the local {TEMP_SHAPEFILE}.shp")
    else:
        print(f"Downloading Census TIGER/Line data from {CENSUS_URL}...")
        try:
            with urllib.request.urlopen(CENSUS_URL) as resp:
                zip_data = io.BytesIO(resp.read())
        except Exception as e:
            print(f"Failed to download: {e}")
            return False

        print("Extracting shapefile...")
        try:
            with zipfile.ZipFile(zip_data, 'r') as zf:
                zf.extractall(".")
            downloaded = True
        except Exception as e:
            print(f"Failed to extract: {e}")
            return False

    print("Converting to GeoJSON...")
    try:
        # Read shapefile
        sf = shapefile.Reader(TEMP_SHAPEFILE)

        features = []
        # pyshp 2.x uses iterShapeRecords() not shaperecords()
        for shaperec in sf.iterShapeRecords():
            shape = shaperec.shape
            record = shaperec.record

            # Get town name from NAME field
            town_name = None
            for field_idx, field in enumerate(sf.fields[1:]):
                if field[0] == 'NAME':
                    town_name = record[field_idx]
                    break

            if not town_name:
                continue

            # Geometry straight from pyshp, which groups parts into rings and
            # polygons by their orientation. Do NOT hand-roll this from
            # shape.parts - see the module docstring for what that cost.
            if shape.shapeType not in (5, 15):      # Polygon, PolygonM
                continue
            geom = shape.__geo_interface__
            if geom["type"] not in ("Polygon", "MultiPolygon"):
                continue

            feature = {
                "type": "Feature",
                "properties": {"name": town_name},
                "geometry": geom
            }
            features.append(feature)

        # Write GeoJSON
        geojson = {
            "type": "FeatureCollection",
            "features": features
        }

        with open(OUTPUT_GEOJSON, 'w') as f:
            json.dump(geojson, f)

        print(f"Saved {len(features)} towns to {OUTPUT_GEOJSON}")
        return True

    except Exception as e:
        print(f"Conversion failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # Only ever delete a shapefile THIS RUN downloaded. tl_2023_09_cousub.*
        # is committed to the repo, and the old unconditional cleanup deleted
        # all three tracked files on every run.
        if downloaded:
            import glob
            import os
            for f in glob.glob(f"{TEMP_SHAPEFILE}.*"):
                try:
                    os.remove(f)
                except OSError:
                    pass


if __name__ == "__main__":
    import sys

    force = "--force" in sys.argv
    if Path(OUTPUT_GEOJSON).exists() and not force:
        print(f"{OUTPUT_GEOJSON} already exists. Skipping download.")
        print("Pass --force to rebuild it from the shapefile.")
    else:
        success = fetch_and_convert()
        if not success:
            print("\nFallback: You can manually download Connecticut town boundaries:")
            print("  1. Visit: https://www2.census.gov/geo/tiger/TIGER2023/COUSUB/")
            print("  2. Download: tl_2023_09_cousub.zip")
            print("  3. Convert shapefile to GeoJSON using ogr2ogr or online tools")
            print("  4. Save as ct_towns.geojson in this directory")
