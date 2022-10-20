copy gpx\*.gpx \export_55533644\activities
call do_lat_lon_1.bat
call do_lat_lon_2.bat
call do_lat_lon_3.bat
git add *.csv
git commit -m "updated lat/long csv files"
git push
