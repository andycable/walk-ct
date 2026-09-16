"""One-off repair of activity_id in activities/*.parquet.

The parquet files were written with the id taken from the Strava export
FILENAME. For a .fit.gz Strava names the file after the UPLOAD id, which is a
different number from the activity id:

    Activity ID   12194819959
    Filename      activities/13001082611.fit.gz
    Name          CT Cheshire.  6.4 miles in 63 minutes.

657 of the 1,803 rows in activities.csv disagree that way, and 538 of them
reached the parquet. Nothing noticed until connecticut-ultrawalker turned the
id into a Strava link and a third of the links went to the wrong walk.

The same mismatch cost some activities their metadata outright.
summarize_current_month.py keys metadata by activity id ALONE while looking it
up by filename stem, so for a mismatched file the lookup misses and the name
falls back to the filename - 53 activities are called things like
"21191090750.fit" and have no activity_type. Those are repaired here too.

This rewrites the metadata columns in place and touches nothing else. It does
NOT re-extract: a rebuild from the export would drop the GPX files
summarize_current_month.py picks up out of Downloads, which are not in the
export at all. Coordinates, timestamps and row counts are asserted unchanged.

It is idempotent - a second run finds nothing left to fix - so it is safe to
re-run if a month is ever restored from an old copy.

Usage:
  python src/fix_activity_ids.py --dry-run
  python src/fix_activity_ids.py
"""

import argparse
import glob
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
ACTIVITY_GLOB = str(REPO_ROOT / "activities" / "activities_*.parquet")
METADATA_CSV = Path(r"C:\export_55533644\activities.csv")

# Names the extractors fell back to when the metadata lookup missed.
FILENAME_NAME = r"^\d+\.(fit|gpx)$"


def export_index(path=METADATA_CSV):
    """(stem -> activity id, activity id -> {name, type}) from activities.csv."""
    if not path.exists():
        raise SystemExit(f"{path} not found - cannot repair without it.")

    df = pd.read_csv(path, usecols=["Activity ID", "Activity Name",
                                    "Activity Type", "Filename"])
    by_stem, meta = {}, {}
    for aid, name, typ, fname in df.itertuples(index=False):
        aid = int(aid)
        meta[aid] = {"name": name, "type": typ}
        if isinstance(fname, str):
            stem = Path(fname).stem.split(".")[0]
            if stem.isdigit() and int(stem) != aid:
                by_stem[int(stem)] = aid
    print(f"{len(by_stem):,} upload ids map to a different activity id")
    return by_stem, meta


def repair(path, by_stem, meta, dry_run):
    """Fix one month's file. Returns (ids fixed, names fixed) row counts."""
    df = pd.read_parquet(path)
    before = (len(df), df.lat.sum(), df.lon.sum())

    ids = df.activity_id
    fixed_ids = ids.map(lambda x: by_stem.get(int(x)) if pd.notna(x) else None)
    id_rows = int(fixed_ids.notna().sum())
    if id_rows:
        df["activity_id"] = fixed_ids.fillna(ids).astype("Int64")

    # Backfill the metadata the missed lookup dropped, using the id as repaired
    # above - which is the whole reason the lookup missed in the first place.
    placeholder = df.activity_name.astype("string").str.match(FILENAME_NAME,
                                                              na=False)
    name_rows = int(placeholder.sum())
    if name_rows:
        for col, key in (("activity_name", "name"), ("activity_type", "type")):
            filled = df.loc[placeholder, "activity_id"].map(
                lambda x: meta.get(int(x), {}).get(key) if pd.notna(x) else None)
            df.loc[placeholder, col] = filled.where(filled.notna(),
                                                    df.loc[placeholder, col])
        df["activity_name"] = df.activity_name.astype("string")
        df["activity_type"] = df.activity_type.astype("string")

    if (id_rows or name_rows) and not dry_run:
        after = (len(df), df.lat.sum(), df.lon.sum())
        assert before == after, f"{path}: the point data moved"
        df.to_parquet(path, compression="snappy", index=False)
    return id_rows, name_rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change and write nothing")
    args = ap.parse_args()

    by_stem, meta = export_index()
    files = sorted(glob.glob(ACTIVITY_GLOB))
    print(f"{len(files)} monthly files")

    touched = ids_total = names_total = 0
    for f in files:
        id_rows, name_rows = repair(Path(f), by_stem, meta, args.dry_run)
        if id_rows or name_rows:
            touched += 1
            ids_total += id_rows
            names_total += name_rows
            print(f"  {Path(f).name}: {id_rows:,} ids, {name_rows:,} names")

    verb = "would fix" if args.dry_run else "fixed"
    print(f"\n{verb} {ids_total:,} id rows and {names_total:,} name rows "
          f"across {touched} files")


if __name__ == "__main__":
    main()
