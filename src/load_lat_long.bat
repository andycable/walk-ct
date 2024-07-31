pushd r:\walk-ct
git pull
popd

sqlcmd -S %DEV_SERVER% -U %USER% -P %PASS% -d Weather -Q "TRUNCATE TABLE Lat_Long_1"
bcp Lat_Long_1 IN R:\walk-ct\src\all.1.uniq.csv -F 2 -c -t, -S %DEV_SERVER% -U %USER% -P %PASS% -d Weather

:: sqlcmd -S %DEV_SERVER% -U %USER% -P %PASS% -d Weather -Q "TRUNCATE TABLE Lat_Long_11"
:: bcp Lat_Long_11 IN R:\walk-ct\src\all.11.uniq.csv -F 2 -c -t, -S %DEV_SERVER% -U %USER% -P %PASS% -d Weather

sqlcmd -S %DEV_SERVER% -U %USER% -P %PASS% -d Weather -Q "TRUNCATE TABLE Lat_Long_2"
bcp Lat_Long_2 IN R:\walk-ct\src\all.2.uniq.csv -F 2 -c -t, -S %DEV_SERVER% -U %USER% -P %PASS% -d Weather

:: sqlcmd -S %DEV_SERVER% -U %USER% -P %PASS% -d Weather -Q "TRUNCATE TABLE Lat_Long_25"
:: bcp Lat_Long_25 IN R:\walk-ct\src\all.25.uniq.csv -F 2 -c -t, -S %DEV_SERVER% -U %USER% -P %PASS% -d Weather

sqlcmd -S %DEV_SERVER% -U %USER% -P %PASS% -d Weather -Q "TRUNCATE TABLE Lat_Long_3"
bcp Lat_Long_3 IN R:\walk-ct\src\all.3.uniq.csv -F 2 -c -t, -S %DEV_SERVER% -U %USER% -P %PASS% -d Weather

:: sqlcmd -S %DEV_SERVER% -U %USER% -P %PASS% -d Weather -Q "TRUNCATE TABLE Lat_Long_5"
:: bcp Lat_Long_5 IN R:\walk-ct\src\all.5.uniq.csv -F 2 -c -t, -S %DEV_SERVER% -U %USER% -P %PASS% -d Weather

