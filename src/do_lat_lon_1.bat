pushd C:\export_55533644\activities
mkdir out
del out\all.1.txt
for %%f in (*.gpx) do findstr lat %%f |cut --bytes 16-19,33-37,43-43 --output-delimiter=5,|uniq|sort|uniq|findstr -v =|findstr -v F >>out\all.1.txt
echo lat,long,extra > C:\Repo\walk-ct\src\all.1.uniq.csv
sort out\all.1.txt|uniq >>C:\Repo\walk-ct\src\all.1.uniq.csv
popd
