pushd C:\export_55533644\activities
mkdir out
del out\all.3.txt
del out\all.2.txt

C:\Repo\walk-ct\src\go_gpx2latlong\go_gpx2latlong.exe> out\all.3.txt
cat out\all.3.txt|cut --bytes 1-5,7-14,16-18 >out\all.2.txt

echo lat,long,extra > C:\Repo\walk-ct\src\all.3.uniq.csv
sort out\all.3.txt|uniq >>C:\Repo\walk-ct\src\all.3.uniq.csv

echo lat,long,extra > C:\Repo\walk-ct\src\all.2.uniq.csv
sort out\all.2.txt|uniq >>C:\Repo\walk-ct\src\all.2.uniq.csv

popd
