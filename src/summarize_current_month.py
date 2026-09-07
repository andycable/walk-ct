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

# Target year and month: the current month by default, or an explicit
# YYYY_MM passed on the command line (used to rebuild an earlier month).
EXPLICIT_MONTH = len(sys.argv) > 1
if EXPLICIT_MONTH:
    CURRENT_YEAR, CURRENT_MONTH = (int(part) for part in sys.argv[1].split("_"))
else:
    now = datetime.now()
    CURRENT_YEAR = now.year
    CURRENT_MONTH = now.month

# Config
STRAVA_EXPORT_DIR = Path("C:\\export_55533644\\activities")
METADATA_CSV = Path("C:\\export_55533644\\activities.csv")
DOWNLOADS_DIR = Path("C:\\Users\\AndrewCable_kau4dpf\\Downloads")
OUTPUT_DIR = Path("C:\\Repo\\walk-ct\\activities")
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


def in_target_month(points: List[Dict]) -> bool:
    """True if a parsed file belongs to the target month.

    Every point from one file shares a single activity_date, so this is one
    check per file -- done before the points are accumulated, which keeps the
    whole archive from being held in memory during a rebuild.
    """
    activity_date = points[0]["activity_date"]
    parsed = pd.to_datetime(activity_date, errors="coerce")
    if pd.isna(parsed):
        return False
    return parsed.year == CURRENT_YEAR and parsed.month == CURRENT_MONTH


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

    print(f"Target month: {CURRENT_YEAR}-{CURRENT_MONTH:02d}")
    print(f"Loading metadata from {METADATA_CSV}...")
    metadata = load_activity_metadata(METADATA_CSV)
    print(f"  Found {len(metadata)} activities in metadata")

    # Speed optimization: skip activities already covered by the previous
    # month's file. It can only under-include, so it is disabled for an
    # explicit rebuild -- there the date filter does all the work.
    if EXPLICIT_MONTH:
        min_activity_id = 0
        print("  Rebuilding an explicit month; scanning all activities")
    else:
        min_activity_id = get_previous_month_max_activity_id()
        if min_activity_id > 0:
            print(f"  Only processing activities with ID > {min_activity_id}")

    all_points = []
    files_processed = 0
    files_skipped = 0
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
                    if not in_target_month(points):
                        files_skipped += 1
                        continue
                    all_points.extend(points)
                    files_processed += 1
                    print(f"  {filepath.name}: {len(points)} points")
    else:
        print(f"  Warning: {STRAVA_EXPORT_DIR} not found")

    # Process all GPX files from Downloads
    print(f"\nScanning {DOWNLOADS_DIR} for GPX files...")
    for filepath in sorted(DOWNLOADS_DIR.glob("*.gpx")):
        points = parse_gpx(filepath, None, {})

        if points:
            total_points += len(points)
            if not in_target_month(points):
                files_skipped += 1
                continue
            all_points.extend(points)
            files_processed += 1
            print(f"  {filepath.name}: {len(points)} points")

    # Write parquet file
    if all_points:
        df = pd.DataFrame(all_points)

        # activity_date decides which month a point belongs to. The
        # activity_id cutoff above is only a speed optimization -- it breaks
        # whenever the ID chain is interrupted (a gap month, a Downloads-only
        # month, a manual upload), and without this filter a broken chain
        # dumps the entire archive into the current month's file.
        activity_dates = pd.to_datetime(df["activity_date"], errors="coerce")
        in_month = (
            (activity_dates.dt.year == CURRENT_YEAR)
            & (activity_dates.dt.month == CURRENT_MONTH)
        )
        dropped = int((~in_month).sum())
        if dropped:
            print(f"\nDropping {dropped:,} trackpoints outside "
                  f"{CURRENT_YEAR}-{CURRENT_MONTH:02d}")
        df = df[in_month].reset_index(drop=True)

        if len(df) == 0:
            print(f"\nNo points found for {CURRENT_YEAR}-{CURRENT_MONTH:02d}")
            return

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
        print(f"Files outside {CURRENT_YEAR}-{CURRENT_MONTH:02d}: {files_skipped}")
        print(f"Trackpoints parsed: {total_points:,}")
        print(f"Trackpoints written: {len(df):,}")
        print(f"Output: {OUTPUT_FILE}")
    else:
        print("No points found")


if __name__ == "__main__":
    main()
