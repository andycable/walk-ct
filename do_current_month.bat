: src\plotmap\heatmap.png
python src\summarize_current_month.py
python src\generate_4decimal_files.py
pushd src\plotmap
python heatmap.py
python towns_heatmap.py --current-month
REM Rebuild the distance-from-walked grid before the gerrymander map;
REM gerrymander_metrics.py reads Distance_3_ct.csv and will otherwise
REM draw pockets from a stale snapshot.
python distance_from_parquet.py
python gerrymander_metrics.py
python export_squadrats.py
python squadrats_map.py
REM Tiles first, then the page: nearest_map.py bakes the tile geometry and the
REM activity table into index.html, so rebuilding one without the other leaves
REM the page pointing at tiles that no longer match it.
python nearest_tiles.py
python nearest_map.py

: heatmap.png
: squadrats_map.html
: connecticut-ultrawalker\index.html
