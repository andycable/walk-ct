pushd C:\export_55533644\activities
mkdir out
del out\all.4.txt
for %%f in (*.gpx) do findstr lat %%f |cut --bytes 16-22,33-40,43-43 --output-delimiter=5,|uniq|sort|uniq >>out\all.4.txt

echo lat,long,extra > C:\Repo\walk-ct\src\all.4.uniq.csv
sort out\all.4.txt|uniq >>C:\Repo\walk-ct\src\all.4.uniq.csv

copy out\all.4.txt out\all.44.txt

sed -i -b s/05,/10,/g out\all.44.txt
sed -i -b s/15,/10,/g out\all.44.txt
sed -i -b s/25,/30,/g out\all.44.txt
sed -i -b s/35,/30,/g out\all.44.txt
sed -i -b s/45,/50,/g out\all.44.txt
sed -i -b s/55,/50,/g out\all.44.txt
sed -i -b s/65,/70,/g out\all.44.txt
sed -i -b s/75,/70,/g out\all.44.txt
sed -i -b s/85,/90,/g out\all.44.txt
sed -i -b s/95,/90,/g out\all.44.txt


echo lat,long,extra > C:\Repo\walk-ct\src\all.44.uniq.csv
sort out\all.44.txt|uniq >>C:\Repo\walk-ct\src\all.44.uniq.csv
popd
