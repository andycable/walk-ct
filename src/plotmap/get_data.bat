echo lat,long,Dist>header.csv
bcp "select convert(decimal(10,4),no_lat),convert(decimal(10,4),no_long),convert(decimal(10,4),Dist) from dbo.Distance_3_snapshot" queryout Distance_3_noheader.csv -c -t, -S %DEV_SERVER% -U %USER% -P %PASS% -d Weather
copy header.csv+Distance_3_noheader.csv Distance_3.csv
del Distance_3_noheader.csv
del header.csv
