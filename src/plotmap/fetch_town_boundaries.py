"""
Fetch Connecticut town (county subdivision) boundaries from Census Bureau.

Downloads TIGER/Line data and converts to GeoJSON format.
Saves as ct_towns.geojson for use in heatmap.py
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
    """Download Census TIGER/Line file and convert to GeoJSON."""
    try:
        import shapefile
    except ImportError:
        print("ERROR: pyshp not installed. Install with: pip install pyshp")
        print("Alternative: Download ct_towns.geojson from GitHub manually")
        return False

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

            # Convert shapefile geometry to GeoJSON
            geom_type = shape.shapeType
            if geom_type in (5, 15):  # Polygon or PolygonM
                # Build coordinates from parts
                parts = list(shape.parts) + [len(shape.points)]
                coords = []
                for start, end in zip(parts[:-1], parts[1:]):
                    ring = [[pt[0], pt[1]] for pt in shape.points[start:end]]
                    coords.append(ring)
                geom = {"type": "Polygon", "coordinates": coords}
            else:
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
        # Cleanup temp files
        import glob
        import os
        for pattern in [f"{TEMP_SHAPEFILE}.*"]:
            for f in glob.glob(pattern):
                try:
                    os.remove(f)
                except:
                    pass


if __name__ == "__main__":
    if Path(OUTPUT_GEOJSON).exists():
        print(f"{OUTPUT_GEOJSON} already exists. Skipping download.")
    else:
        success = fetch_and_convert()
        if not success:
            print("\nFallback: You can manually download Connecticut town boundaries:")
            print("  1. Visit: https://www2.census.gov/geo/tiger/TIGER2023/COUSUB/")
            print("  2. Download: tl_2023_09_cousub.zip")
            print("  3. Convert shapefile to GeoJSON using ogr2ogr or online tools")
            print("  4. Save as ct_towns.geojson in this directory")
