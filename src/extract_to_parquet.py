#!/usr/bin/env python3
r"""
Extract GPS/FIT activities from a single month to Parquet.

Reads all GPX and FIT files from Strava export for the specified month,
extracts trackpoints with lat/lon/elevation/timestamp and FIT-specific fields,
and writes to C:\Repo\walk-ct\activities\activities_YYYY_MM.parquet.
"""

import os
import gzip
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd
import gpxpy
import gpxpy.gpx
from fitparse import FitFile

# Config
YEAR = 2026
MONTH = 5
STRAVA_EXPORT_DIR = Path("C:\\export_55533644\\activities")
METADATA_CSV = Path("C:\\export_55533644\\activities.csv")
OUTPUT_DIR = Path("C:\\Repo\\walk-ct\\activities")

# Semicircles to degrees conversion for FIT format
SEMICIRCLES_TO_DEGREES = (2**31) / 180


def load_activity_metadata(csv_path: Path, target_year: int, target_month: int) -> Dict[int, Dict]:
    """Load activity metadata from activities.csv, filtered to target month only."""
    if not csv_path.exists():
        print(f"Warning: {csv_path} not found, using minimal metadata")
        return {}

    try:
        df = pd.read_csv(csv_path, usecols=["Activity ID", "Activity Date", "Activity Name", "Activity Type", "Filename"])
        metadata = {}
        filename_to_meta = {}

        for _, row in df.iterrows():
            activity_id = int(row["Activity ID"])
            # Parse date format: "Apr 13, 2026, 10:33:14 AM"
            try:
                date_str = row["Activity Date"].split(",")[0] + ", " + row["Activity Date"].split(",")[1]
                activity_date = pd.to_datetime(date_str).date()
            except:
                activity_date = None

            # Skip activities not in the target month
            if activity_date is None or activity_date.year != target_year or activity_date.month != target_month:
                continue

            meta = {
                "name": row["Activity Name"],
                "type": row["Activity Type"],
                "date": activity_date,
            }

            # Key by Activity ID
            metadata[activity_id] = meta

            # Also key by filename stem (for .fit.gz files with mismatched IDs)
            if pd.notna(row["Filename"]):
                filename_stem = Path(row["Filename"]).stem.split('.')[0]
                try:
                    filename_id = int(filename_stem)
                    filename_to_meta[filename_id] = meta
                except ValueError:
                    pass

        return {**metadata, **filename_to_meta}
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

        # Get activity metadata
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

        # Get activity metadata
        meta = metadata.get(activity_id, {})
        activity_date = meta.get("date")
        if activity_date is None:
            activity_date = datetime.fromtimestamp(filepath.stat().st_mtime).date()

        for record in fit.get_messages("record"):
            lat = record.get_value("position_lat")
            lon = record.get_value("position_long")

            # Skip records without position data
            if lat is None or lon is None:
                continue

            lat = semicircles_to_degrees(lat)
            lon = semicircles_to_degrees(lon)

            timestamp = record.get_value("timestamp")
            # Strip timezone if present (FIT files come with timezone-aware datetime)
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


def parse_fit(filepath: Path, activity_id: Optional[int], metadata: Dict) -> List[Dict]:
    """Parse uncompressed FIT file and extract trackpoints."""
    points = []

    try:
        fit = FitFile(str(filepath))

        # Get activity metadata
        meta = metadata.get(activity_id, {})
        activity_date = meta.get("date")
        if activity_date is None:
            activity_date = datetime.fromtimestamp(filepath.stat().st_mtime).date()

        for record in fit.get_messages("record"):
            lat = record.get_value("position_lat")
            lon = record.get_value("position_long")

            # Skip records without position data
            if lat is None or lon is None:
                continue

            lat = semicircles_to_degrees(lat)
            lon = semicircles_to_degrees(lon)

            timestamp = record.get_value("timestamp")
            # Strip timezone if present (FIT files come with timezone-aware datetime)
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
    """Extract activities for specified month to parquet."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Loading metadata from {METADATA_CSV}...")
    metadata = load_activity_metadata(METADATA_CSV, YEAR, MONTH)
    print(f"  Found {len(metadata)} activities in {YEAR}-{MONTH:02d}")

    all_points = []
    files_processed = 0
    total_points = 0

    # Process Strava export for the target month only
    print(f"\nScanning {STRAVA_EXPORT_DIR} for {YEAR}-{MONTH:02d} activities...")
    if STRAVA_EXPORT_DIR.exists():
        for filepath in sorted(STRAVA_EXPORT_DIR.iterdir()):
            if filepath.is_file():
                try:
                    activity_id = int(filepath.stem.split('.')[0])
                except ValueError:
                    # Skip non-numeric filenames
                    continue

                # Skip if activity is not in target month metadata
                if activity_id not in metadata:
                    continue

                points = []

                if filepath.suffix == ".gpx":
                    points = parse_gpx(filepath, activity_id, metadata)
                elif filepath.suffix == ".gz":
                    # Only process if it's likely FIT (by checking file extension before .gz)
                    if filepath.stem.endswith(".fit"):
                        points = parse_fit_gz(filepath, activity_id, metadata)
                    # else: skip TCX, GPX.gz, and other formats
                elif filepath.suffix == ".fit":
                    points = parse_fit(filepath, activity_id, metadata)

                if points:
                    all_points.extend(points)
                    files_processed += 1
                    total_points += len(points)

                    if files_processed % 100 == 0:
                        print(f"  Processed {files_processed} files ({total_points} points)")
    else:
        print(f"  Warning: {STRAVA_EXPORT_DIR} not found")

    # Write parquet file for target month
    print(f"\nWriting {YEAR}-{MONTH:02d} parquet file to {OUTPUT_DIR}...")

    if all_points:
        df = pd.DataFrame(all_points)

        df = df.astype({
            "activity_id": "Int64",  # nullable int
            "source": "string",
            "activity_name": "string",
            "activity_type": "string",
            "activity_date": "object",  # date objects, converted to parquet date32
            "lat": "float64",
            "lon": "float64",
            "elevation": "float32",
            "point_timestamp": "string",  # Convert to ISO string to avoid timezone issues
            "heart_rate": "Int16",  # nullable int
            "cadence": "Int16",
            "temperature": "float32",
            "speed": "float32",
            "distance_m": "float32",
        })

        # Convert timestamps to ISO strings (easier than fighting parquet timezones)
        df["point_timestamp"] = df["point_timestamp"].apply(
            lambda x: str(x) if pd.notna(x) else None
        )

        output_path = OUTPUT_DIR / f"activities_{YEAR:04d}_{MONTH:02d}.parquet"
        df.to_parquet(output_path, compression="snappy", index=False)

        print(f"\n=== Summary ===")
        print(f"Files processed: {files_processed}")
        print(f"Total trackpoints: {total_points:,}")
        print(f"Output: {output_path}")
    else:
        print(f"No activities found for {YEAR}-{MONTH:02d}")


if __name__ == "__main__":
    main()
