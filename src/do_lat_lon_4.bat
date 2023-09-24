pushd C:\export_55533644\activities
mkdir out
del out\all.4.txt
for %%f in (*.gpx) do findstr lat %%f |cut --bytes 16-22,33-40,43-43 --output-delimiter=5,|uniq|sort|uniq >>out\all.4.txt

echo lat,long,extra > C:\Repo\walk-ct\src\all.4.uniq.csv
sort out\all.4.txt|uniq >>C:\Repo\walk-ct\src\all.4.uniq.csv
popd
