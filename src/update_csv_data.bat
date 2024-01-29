copy gpx\*.gpx \export_55533644\activities
for %%f in (\export_55533644\activities\*.gz) do gzip.exe -d %%f
call do_lat_lon_1.bat
call do_lat_lon_2.bat
call do_lat_lon_3.bat
call do_lat_lon_4.bat
git add *.csv
git commit -m "updated lat/long csv files"
git push
