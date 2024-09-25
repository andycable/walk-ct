call reformat.bat
call do_lat_lon_go.bat

git add *.csv
git commit -m "updated lat/long csv files"
git push

call load_lat_long.bat
