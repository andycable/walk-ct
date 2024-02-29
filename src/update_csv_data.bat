copy gpx\*.gpx \export_55533644\activities
for %%f in (\export_55533644\activities\*.gz) do gzip.exe -d %%f
for %%f in (\export_55533644\activities\*.fit) do convert\dist\convert.fit_to_gpx.exe %%f %%f.gpx

call do_lat_lon_go.bat

:call do_lat_lon_1.bat
:call do_lat_lon_2.bat
:call do_lat_lon_3.bat
:call do_lat_lon_4.bat

git add *.csv
git commit -m "updated lat/long csv files"
git push
