# Connecticut Ultrawalker

Type a Connecticut address; get the distance, as the crow flies, to the
nearest point I have actually walked - plus the date, the walk, and a link to
it on Strava.

Everything here is generated. Do not hand-edit `index.html`, `heatmap.png`
or `tiles/`.

## Rebuilding

```
cd src/plotmap
python nearest_tiles.py     # tiles/ - 3,343 files, 8.3 MB
python nearest_map.py       # index.html + heatmap.png
```

Run it after `do_current_month.bat` refreshes the activity parquet, in that
order - the page bakes in the tile geometry and the activity table, so a tile
rebuild without a page rebuild leaves the two out of step.

`nearest_map.py` also needs `src/plotmap/Distance_3_ct.csv`, which is what the
coverage heatmap is drawn from; `do_current_month.bat` rebuilds it earlier in
the same run. Without it the page still builds, just with no heatmap and no
heatmap controls. `--no-heatmap` skips it deliberately.

The heatmap ships as a SEPARATE PNG rather than a data URI inside the page,
which is the opposite of what `squadrats_map.html` does. That page has to
survive being double-clicked off `file://`, where a sibling image is a request
the browser will not make; this one already requires a server for its tiles,
so the file keeps ~240 KB of base64 out of the committed HTML and lets the
browser cache the raster separately from the page.

## Viewing it

This page **cannot be opened by double-clicking it**, unlike
`src/plotmap/squadrats_map.html`. It fetches tiles at query time and `fetch()`
is blocked under `file://`. Locally:

```
cd connecticut-ultrawalker
python -m http.server 8777
```

then <http://127.0.0.1:8777/>.

Published, it lives at
`https://andycable.github.io/walk-ct/connecticut-ultrawalker/` once Pages is
enabled on `main` at the repository root.

## Unlisted, not private

The page carries `<meta name="robots" content="noindex, nofollow">`, so search
engines that honour it will not index it. That is the whole of the protection:
the repository is public, so the URL and the underlying coordinates are
reachable by anyone who looks. Treat unlisted as "not advertised", never as
"not accessible".

`robots.txt` is deliberately left alone. A `Disallow` rule would stop crawlers
fetching the page at all, which means they would never read the `noindex` -
and it would publish the path in a file whose entire purpose is to be read.

## How the answer is computed

Walked points are deduped to 4 decimals - about 11 m, inside GPS noise - and
cut into 0.02 degree tiles. A query loads the tile it lands in, then rings
outward until the best point found is closer than the nearest ground not yet
searched. Typical query: one to nine tiles, 2-20 KB. The worst case in the
state is 2.38 miles, so the search is bounded.

Distances use the same miles-per-degree series as
`src/plotmap/distance_from_parquet.py`. Longitude in Connecticut runs about 51
miles to the degree against latitude's 69, which is why the two axes never
share a scale factor.

Geocoding is Nominatim, with Photon as a fallback. Both are volunteer-run and
rate-limited: one request per submit, never per keystroke. The US Census
geocoder is better on rural street addresses but sends no CORS headers, so a
browser cannot call it at all.
