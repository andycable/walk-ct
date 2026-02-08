# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Personal project to walk every street in all 169 towns in Connecticut. Tracks GPS activities from Strava, processes coordinates at multiple precision levels, stores them in SQL Server, and visualizes coverage on maps. Integrates with Strava, CityStrides (user 43318), and Wandrer.earth.

## Tech Stack

- **Windows Batch Scripts** (.bat) — orchestration and automation
- **Go** — GPX parsing and coordinate extraction (`src/go_gpx2latlong/`)
- **Python** — FIT-to-GPX conversion (`src/convert/convert.fit_to_gpx.py`, uses fit2gpx)
- **R** — map visualization (`src/plotmap/plotmap.R`, uses ggplot2/maps/osmdata)
- **SQL Server** — geospatial calculations (database "Weather", tables: Lat_Long_1/2/3/5, Distance_3_snapshot)

## Data Pipeline

1. Download Strava activities to `C:\export_55533644\activities\`
2. Run `src/update_csv_data.bat` — master script that:
   - Converts FIT→GPX via `reformat.bat` (calls `convert.fit_to_gpx.exe`)
   - Extracts coordinates via `do_lat_lon_go.bat` (calls `go_gpx2latlong.exe`)
   - Commits CSV changes to git
   - Loads data into SQL Server via `load_lat_long.bat` (uses `bcp` bulk copy)
3. Export distance data: `src/plotmap/get_data.bat` (bcp from Distance_3_snapshot)
4. Generate maps: run `src/plotmap/plotmap.R` in RStudio

Quick sync alternative: `src/SyncStrava.bat` (skips FIT conversion, runs steps 2b-2d)

## Key Data Files

- `src/all.{1,2,3,5}.uniq.csv` — walked coordinates at different precision levels (format: `lat,long,0`)
- `src/plotmap/Distance_3.csv` — distance-from-boundary calculations (format: `lat,long,Dist`)
- `src/history.csv` — town completion tracking (format: `Date,Town,Number,Status,Strava`)
- `src/Wandrer_data.csv` — road coverage percentages per location

## Building the Go Program

```bash
cd src/go_gpx2latlong
go build -o go_gpx2latlong.exe
```

## Building the Python Converter

Uses PyInstaller. The compiled exe lives at `src/convert/dist/convert.fit_to_gpx.exe`.

## Environment Requirements

- SQL Server connection requires env vars: `%DEV_SERVER%`, `%USER%`, `%PASS%`
- Strava export directory hardcoded to `C:\export_55533644\activities\`
- R packages: ggplot2, maps, ggmap, dplyr, sp, osmdata
- Windows environment with bash utilities (sed, cut, sort, uniq) available via MSYS/Git Bash
