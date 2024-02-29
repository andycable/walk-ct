pushd C:\export_55533644\activities
mkdir out
del out\all.3.txt

C:\Repo\walk-ct\src\go_gpx2latlong\go_gpx2latlong.exe> out\all.3.txt
echo lat,long,extra > C:\Repo\walk-ct\src\all.3.uniq.csv
sort out\all.3.txt|uniq >>C:\Repo\walk-ct\src\all.3.uniq.csv
popd
