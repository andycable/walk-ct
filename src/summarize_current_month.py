#!/usr/bin/env python3
r"""
Extract current month activities from Strava export + Downloads GPX files.
Creates c:\walking\activities_YYYY_MM.parquet based on system clock.
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

# Target months: the current month by default, or one or more explicit
# YYYY_MM arguments. Several months are resolved in a single pass over the
# export, so backfilling five months costs one scan rather than five.
EXPLICIT_MONTH = len(sys.argv) > 1
if EXPLICIT_MONTH:
    TARGET_MONTHS = []
    for arg in sys.argv[1:]:
        year, month = (int(part) for part in arg.split("_"))
        if (year, month) not in TARGET_MONTHS:
            TARGET_MONTHS.append((year, month))
    TARGET_MONTHS.sort()
else:
    now = datetime.now()
    TARGET_MONTHS = [(now.year, now.month)]

# The previous-month ID cutoff applies only to the default single-month run.
CURRENT_YEAR, CURRENT_MONTH = TARGET_MONTHS[0]
TARGET_MONTH_LABEL = ", ".join(f"{y}-{m:02d}" for y, m in TARGET_MONTHS)

# Config
STRAVA_EXPORT_DIR = Path("C:\\export_55533644\\activities")
METADATA_CSV = Path("C:\\export_55533644\\activities.csv")
DOWNLOADS_DIR = Path("C:\\Users\\AndrewCable_kau4dpf\\Downloads")
OUTPUT_DIR = Path("C:\\Repo\\walk-ct\\activities")


def output_path(year: int, month: int) -> Path:
    return OUTPUT_DIR / f"activities_{year}_{month:02d}.parquet"

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


def resolve_activity_date(points: List[Dict], filepath: Path):
    """Best-known date for an activity whose metadata row is missing.

    Prefers the earliest trackpoint timestamp -- the only date that travels
    with the file itself. File mtime is a last resort: a freshly unpacked
    Strava export stamps every file with today, which would pile the whole
    archive into the current month.
    """
    timestamps = [p["point_timestamp"] for p in points if p["point_timestamp"]]
    if timestamps:
        earliest = pd.to_datetime(min(timestamps), errors="coerce", utc=True)
        if pd.notna(earliest):
            return earliest.date()
    return datetime.fromtimestamp(filepath.stat().st_mtime).date()


def parse_gpx(filepath: Path, activity_id: Optional[int], metadata: Dict) -> List[Dict]:
    """Parse GPX file and extract trackpoints."""
    points = []

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            gpx = gpxpy.parse(f)

        meta = metadata.get(activity_id, {})
        activity_date = meta.get("date")

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

    if points and points[0]["activity_date"] is None:
        resolved = resolve_activity_date(points, filepath)
        for point in points:
            point["activity_date"] = resolved

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

    if points and points[0]["activity_date"] is None:
        resolved = resolve_activity_date(points, filepath)
        for point in points:
            point["activity_date"] = resolved

    return points


def month_of(points: List[Dict]) -> Optional[tuple]:
    """The target month a parsed file belongs to, or None if it is not wanted.

    Every point from one file shares a single activity_date, so this is one
    check per file -- done before the points are accumulated, which keeps the
    whole archive from being held in memory during a rebuild.
    """
    parsed = pd.to_datetime(points[0]["activity_date"], errors="coerce")
    if pd.isna(parsed):
        return None
    key = (parsed.year, parsed.month)
    return key if key in TARGET_MONTHS else None


def get_previous_month_max_activity_id() -> int:
    """Get max activity_id from previous month's parquet file."""
    prev_year = CURRENT_YEAR
    prev_month = CURRENT_MONTH - 1
    if prev_month == 0:
        prev_year -= 1
        prev_month = 12

    prev_file = OUTPUT_DIR / f"activities_{prev_year}_{prev_month:02d}.parquet"
    if prev_file.exists():
        try:
            df = pd.read_parquet(prev_file, columns=["activity_id"])
            max_id = df["activity_id"].max()
            if pd.isna(max_id):
                print(f"  Warning: {prev_file.name} has no activity IDs; "
                      "relying on the date filter instead")
                return 0
            return int(max_id)
        except Exception as e:
            print(f"  Warning: Could not read previous month file: {e}")
            return 0
    return 0


def main():
    """Extract current month activities."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Target month(s): {TARGET_MONTH_LABEL}")
    print(f"Loading metadata from {METADATA_CSV}...")
    metadata = load_activity_metadata(METADATA_CSV)
    print(f"  Found {len(metadata)} activities in metadata")

    # Speed optimization: skip activities already covered by the previous
    # month's file. It can only under-include, so it is disabled for an
    # explicit rebuild -- there the date filter does all the work.
    if EXPLICIT_MONTH:
        min_activity_id = 0
        print("  Rebuilding explicit month(s); scanning all activities")
    else:
        min_activity_id = get_previous_month_max_activity_id()
        if min_activity_id > 0:
            print(f"  Only processing activities with ID > {min_activity_id}")

    points_by_month = {key: [] for key in TARGET_MONTHS}
    files_processed = 0
    files_skipped = 0
    total_points = 0

    # Process Strava export for current month only
    print(f"\nScanning {STRAVA_EXPORT_DIR} for {TARGET_MONTH_LABEL} activities...")
    if STRAVA_EXPORT_DIR.exists():
        for filepath in sorted(STRAVA_EXPORT_DIR.iterdir()):
            if filepath.is_file():
                try:
                    activity_id = int(filepath.stem.split('.')[0])
                except ValueError:
                    continue

                # Skip activities that were already processed in a previous month
                if activity_id <= min_activity_id:
                    continue

                points = []

                if filepath.suffix == ".gpx":
                    points = parse_gpx(filepath, activity_id, metadata)
                elif filepath.suffix == ".gz" and filepath.stem.endswith(".fit"):
                    points = parse_fit_gz(filepath, activity_id, metadata)

                if points:
                    total_points += len(points)
                    key = month_of(points)
                    if key is None:
                        files_skipped += 1
                        continue
                    points_by_month[key].extend(points)
                    files_processed += 1
                    print(f"  {filepath.name}: {len(points)} points "
                          f"({key[0]}-{key[1]:02d})")
    else:
        print(f"  Warning: {STRAVA_EXPORT_DIR} not found")

    # Process all GPX files from Downloads
    print(f"\nScanning {DOWNLOADS_DIR} for GPX files...")
    for filepath in sorted(DOWNLOADS_DIR.glob("*.gpx")):
        points = parse_gpx(filepath, None, {})

        if points:
            total_points += len(points)
            key = month_of(points)
            if key is None:
                files_skipped += 1
                continue
            points_by_month[key].extend(points)
            files_processed += 1
            print(f"  {filepath.name}: {len(points)} points "
                  f"({key[0]}-{key[1]:02d})")

    # Write one parquet per target month. Each month's points were bucketed
    # during the scan, so a five-month backfill costs a single pass.
    print(f"\n=== Summary ===")
    print(f"Files matched: {files_processed}")
    print(f"Files outside {TARGET_MONTH_LABEL}: {files_skipped}")
    print(f"Trackpoints parsed: {total_points:,}")

    for year, month in TARGET_MONTHS:
        points = points_by_month[(year, month)]
        if not points:
            print(f"  {year}-{month:02d}: no activities found, nothing written")
            continue

        df = pd.DataFrame(points)

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

        out = output_path(year, month)
        df.to_parquet(out, compression="snappy", index=False)
        print(f"  {year}-{month:02d}: {len(df):,} trackpoints, "
              f"{df['activity_id'].nunique()} activities -> {out.name}")


if __name__ == "__main__":
    main()
