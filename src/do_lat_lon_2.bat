pushd C:\export_55533644\activities
mkdir out
del out\all.2.txt
for %%f in (*.gpx) do findstr lat %%f |cut --bytes 16-20,33-38,43-43 --output-delimiter=5,|uniq|sort|uniq >>out\all.2.txt
echo lat,long,extra > C:\Repo\walk-ct\src\all.2.uniq.csv
sort out\all.2.txt|uniq >>C:\Repo\walk-ct\src\all.2.uniq.csv
popd
