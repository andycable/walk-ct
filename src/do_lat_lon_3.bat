pushd C:\export_55533644\activities
mkdir out
del out\all.3.txt
for %%f in (*.gpx) do findstr lat %%f |cut --bytes 16-21,33-39,43-43 --output-delimiter=5,|uniq|sort|uniq >>out\all.3.txt
echo lat,long,extra > C:\Repo\walk-ct\src\all.3.uniq.csv
sort out\all.3.txt|uniq >>C:\Repo\walk-ct\src\all.3.uniq.csv
popd
