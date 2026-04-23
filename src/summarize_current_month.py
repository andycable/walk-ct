#!/usr/bin/env python3
"""
Extract current month activities from Strava export + Downloads GPX files.
Creates c:\walking\activities_YYYY_MM.parquet based on system clock.
"""

import os
import gzip
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd
import gpxpy
import gpxpy.gpx
from fitparse import FitFile

# Get current year and month
now = datetime.now()
CURRENT_YEAR = now.year
CURRENT_MONTH = now.month

# Config
STRAVA_EXPORT_DIR = Path("C:\\export_55533644\\activities")
METADATA_CSV = Path("C:\\export_55533644\\activities.csv")
DOWNLOADS_DIR = Path("C:\\Users\\AndrewCable_kau4dpf\\Downloads")
OUTPUT_DIR = Path("C:\\walking")
OUTPUT_FILE = OUTPUT_DIR / f"activities_{CURRENT_YEAR}_{CURRENT_MONTH:02d}.parquet"

SEMICIRCLES_TO_DEGREES = (2**31) / 180

def load_activity_metadata(csv_path: Path) -> Dict[int, Dict]:
    """Load activity metadata from activities.csv."""
    if not csv_path.exists():
        print(f"Warning: {csv_path} not found")
        return {}

    try:
        df = pd.read_csv(csv_path, usecols=["Activity ID", "Activity Date", "Activity Name", "Activity Type"])
        metadata = {}

        for _, row in df.iterrows():
            activity_id = int(row["Activity ID"])
            try:
                date_str = row["Activity Date"].split(",")[0] + ", " + row["Activity Date"].split(",")[1]
                activity_date = pd.to_datetime(date_str).date()
            except:
                activity_date = None

            meta = {
                "name": row["Activity Name"],
                "type": row["Activity Type"],
                "date": activity_date,
            }
            metadata[activity_id] = meta

        return metadata
    except Exception as e:
        print(f"Warning: Failed to load metadata: {e}")
        return {}


def semicircles_to_degrees(semicircles: int) -> float:
    """Convert FIT semicircles to degrees."""
    if semicircles is None:
        return None
    return semicircles / SEMICIRCLES_TO_DEGREES


def parse_gpx(filepath: Path, activity_id: Optional[int], metadata: Dict) -> List[Dict]:
    """Parse GPX file and extract trackpoints."""
    points = []

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            gpx = gpxpy.parse(f)

        meta = metadata.get(activity_id, {})
        activity_date = meta.get("date")
        if activity_date is None:
            activity_date = datetime.fromtimestamp(filepath.stat().st_mtime).date()

        for track in gpx.tracks:
            for segment in track.segments:
                for point in segment.points:
                    points.append({
                        "activity_id": activity_id,
                        "source": "gpx",
                        "activity_name": meta.get("name", filepath.stem),
                        "activity_type": meta.get("type"),
                        "activity_date": activity_date,
                        "lat": float(point.latitude),
                        "lon": float(point.longitude),
                        "elevation": float(point.elevation) if point.elevation else None,
                        "point_timestamp": point.time,
                        "heart_rate": None,
                        "cadence": None,
                        "temperature": None,
                        "speed": None,
                        "distance_m": None,
                    })
    except Exception as e:
        print(f"Error parsing {filepath}: {e}")

    return points


def parse_fit_gz(filepath: Path, activity_id: Optional[int], metadata: Dict) -> List[Dict]:
    """Parse gzipped FIT file and extract trackpoints."""
    points = []

    try:
        with gzip.open(filepath, 'rb') as f:
            fit_data = f.read()

        fit = FitFile(fit_data)

        meta = metadata.get(activity_id, {})
        activity_date = meta.get("date")
        if activity_date is None:
            activity_date = datetime.fromtimestamp(filepath.stat().st_mtime).date()

        for record in fit.get_messages("record"):
            lat = record.get_value("position_lat")
            lon = record.get_value("position_long")

            if lat is None or lon is None:
                continue

            lat = semicircles_to_degrees(lat)
            lon = semicircles_to_degrees(lon)

            timestamp = record.get_value("timestamp")
            if timestamp and hasattr(timestamp, 'tz_localize'):
                timestamp = timestamp.tz_localize(None) if timestamp.tz else timestamp
            elif timestamp and hasattr(timestamp, 'replace'):
                timestamp = timestamp.replace(tzinfo=None)

            points.append({
                "activity_id": activity_id,
                "source": "fit",
                "activity_name": meta.get("name", filepath.stem),
                "activity_type": meta.get("type"),
                "activity_date": activity_date,
                "lat": lat,
                "lon": lon,
                "elevation": record.get_value("altitude"),
                "point_timestamp": timestamp,
                "heart_rate": record.get_value("heart_rate"),
                "cadence": record.get_value("cadence"),
                "temperature": record.get_value("temperature"),
                "speed": record.get_value("speed"),
                "distance_m": record.get_value("distance"),
            })
    except Exception as e:
        print(f"Error parsing {filepath}: {e}")

    return points


def main():
    """Extract 2026-04 activities."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Loading metadata from {METADATA_CSV}...")
    metadata = load_activity_metadata(METADATA_CSV)
    print(f"  Found {len(metadata)} activities in metadata")

    all_points = []
    files_processed = 0
    total_points = 0

    # Process Strava export for current month only
    print(f"\nScanning {STRAVA_EXPORT_DIR} for {CURRENT_YEAR}-{CURRENT_MONTH:02d} activities...")
    if STRAVA_EXPORT_DIR.exists():
        for filepath in sorted(STRAVA_EXPORT_DIR.iterdir()):
            if filepath.is_file():
                try:
                    activity_id = int(filepath.stem.split('.')[0])
                except ValueError:
                    continue

                # Check if this activity is from current month
                meta = metadata.get(activity_id, {})
                activity_date = meta.get("date")
                if activity_date is None or activity_date.year != CURRENT_YEAR or activity_date.month != CURRENT_MONTH:
                    continue

                points = []

                if filepath.suffix == ".gpx":
                    points = parse_gpx(filepath, activity_id, metadata)
                elif filepath.suffix == ".gz" and filepath.stem.endswith(".fit"):
                    points = parse_fit_gz(filepath, activity_id, metadata)

                if points:
                    all_points.extend(points)
                    files_processed += 1
                    total_points += len(points)
                    print(f"  {filepath.name}: {len(points)} points")
    else:
        print(f"  Warning: {STRAVA_EXPORT_DIR} not found")

    # Process all GPX files from Downloads
    print(f"\nScanning {DOWNLOADS_DIR} for GPX files...")
    for filepath in sorted(DOWNLOADS_DIR.glob("*.gpx")):
        points = parse_gpx(filepath, None, {})

        if points:
            all_points.extend(points)
            files_processed += 1
            total_points += len(points)
            print(f"  {filepath.name}: {len(points)} points")

    # Write parquet file
    if all_points:
        df = pd.DataFrame(all_points)

        df = df.astype({
            "activity_id": "Int64",
            "source": "string",
            "activity_name": "string",
            "activity_type": "string",
            "activity_date": "object",
            "lat": "float64",
            "lon": "float64",
            "elevation": "float32",
            "point_timestamp": "string",
            "heart_rate": "Int16",
            "cadence": "Int16",
            "temperature": "float32",
            "speed": "float32",
            "distance_m": "float32",
        })

        df["point_timestamp"] = df["point_timestamp"].apply(
            lambda x: str(x) if pd.notna(x) else None
        )

        df.to_parquet(OUTPUT_FILE, compression="snappy", index=False)

        print(f"\n=== Summary ===")
        print(f"Files processed: {files_processed}")
        print(f"Total trackpoints: {total_points:,}")
        print(f"Output: {OUTPUT_FILE}")
    else:
        print("No points found")


if __name__ == "__main__":
    main()
