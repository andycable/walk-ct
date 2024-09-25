copy gpx\*.gpx \export_55533644\activities
for %%f in (\export_55533644\activities\*.gz) do gzip.exe -d %%f
for %%f in (\export_55533644\activities\*.fit) do convert\dist\convert.fit_to_gpx.exe %%f %%f.gpx
: for %%f in (\export_55533644\activities\*.gpx) do go_gpx\go_gpx.exe %%f %%f
