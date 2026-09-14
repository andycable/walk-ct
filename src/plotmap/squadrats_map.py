"""
Build a standalone interactive map of unwalked squadrats (z14 tiles).

Reads the GeoJSON written by export_squadrats.py and embeds it, the town
outlines and the per-town counts into a single self-contained HTML file, so
the map opens by double-clicking it (no local web server, no fetch/CORS).

    python export_squadrats.py
    python squadrats_map.py

Writes squadrats_map.html. Leaflet and the basemap tiles load from the
network; everything else is inline. Basemap tiles come from CARTO rather than
tile.openstreetmap.org, whose volunteer servers refuse a file:// page under
their tile usage policy.
"""

import argparse
import base64
import csv
import io
import json
import math
import os
from pathlib import Path

from shapely.geometry import shape, mapping

import ct_outline

GEOJSON_IN = "squadrats_z14.geojson"

# The same outlines the tiles were clipped to. Drawing the water-inclusive
# ct_towns.geojson here instead left the town borders hanging out in Long
# Island Sound while the tiles stopped at the shore.
TOWNS_GEOJSON = ct_outline.SHORELINE_GEOJSON
TOWN_CSV = "squadrats_by_town.csv"
OUTPUT_HTML = "squadrats_map.html"

# CARTO raster basemaps now require an API key (and CARTO is retiring raster
# in favour of vector, so expect this to need revisiting). The key is read from
# the CARTO environment variable and baked into the generated HTML, which is
# committed - a deliberate choice, not an oversight.
CARTO_KEY_ENV = "CARTO"

# Coverage heatmap overlay, built from the same distance grid heatmap.py draws.
DISTANCE_CSV = "Distance_3_ct.csv"

# Upper edge of each band in miles, and its colour. Must stay in step with the
# rgb_map in heatmap.py or the two views of the same data will disagree.
HEATMAP_BANDS = [
    (0.25, (173, 217, 255)),
    (0.50, (0, 128, 255)),
    (0.75, (0, 191, 255)),
    (1.00, (0, 191, 0)),
    (1.25, (255, 255, 0)),
    (1.50, (255, 165, 0)),
    (float("inf"), (255, 0, 0)),
]
CARTO_STYLES = {"voyager": "Streets", "light_all": "Light", "dark_all": "Dark"}


def carto_key(explicit=None):
    """The CARTO basemap key, from --carto-key or the CARTO env var."""
    key = explicit or os.environ.get(CARTO_KEY_ENV, "")
    if not key:
        print(f"WARNING: no {CARTO_KEY_ENV} environment variable and no "
              f"--carto-key given.")
        print(f"         Basemap tiles will be watermarked, and regenerating "
              f"this way")
        print(f"         strips the key out of {OUTPUT_HTML}.")
    return key

# Census filler polygons (open water) carried in the town boundary file.
SKIP_TOWNS = {"County subdivisions not defined"}

# Simplification tolerance for the embedded town outlines, in degrees.
# ~0.0008 deg is ~60 m: invisible at town scale, and cuts the 2 MB town file
# down to something reasonable to inline.
SIMPLIFY_DEG = 0.0008

SQUADRAT_COLOR = "#d000d0"  # matches squadrats.SQUADRAT_COLOR


def load_towns_simplified(path=TOWNS_GEOJSON, tolerance=SIMPLIFY_DEG):
    """Return a slimmed-down FeatureCollection of town outlines."""
    with open(path, "r") as f:
        fc = json.load(f)

    features = []
    for feat in fc["features"]:
        name = feat["properties"].get("name")
        if not name or name in SKIP_TOWNS:
            continue
        geom = shape(feat["geometry"]).simplify(tolerance, preserve_topology=True)
        features.append({
            "type": "Feature",
            "properties": {"name": name},
            "geometry": mapping(geom),
        })

    return {"type": "FeatureCollection", "features": features}


def load_town_stats(path=TOWN_CSV):
    """Return per-town counts for towns that still have unwalked squadrats."""
    with open(path, "r", newline="") as f:
        rows = list(csv.DictReader(f))

    stats = [
        {
            "town": r["Town"],
            "earned": int(r["Earned"]),
            "unwalked": int(r["Unwalked"]),
            "total": int(r["Total"]),
            "pct": float(r["PctEarned"]),
        }
        for r in rows
        if int(r["Unwalked"]) > 0
    ]
    stats.sort(key=lambda s: (-s["unwalked"], s["pct"]))
    return stats


def heatmap_legend():
    """[[label, css-colour], ...] for the band swatches, from HEATMAP_BANDS."""
    out, low = [], 0.0
    for high, rgb in HEATMAP_BANDS:
        label = f"{low:.2f}-{high:.2f}" if high != float("inf") else f"{low:.2f}+"
        out.append([label + " mi", "rgb(%d,%d,%d)" % rgb])
        low = high
    return out


def _mercator_y(lat_deg):
    """Web Mercator y for a latitude, in radians-equivalent units."""
    return math.log(math.tan(math.pi / 4 + math.radians(lat_deg) / 2))


def build_heatmap_overlay(path=DISTANCE_CSV):
    """Render the distance grid as a PNG data URI for L.imageOverlay.

    Returns {"url": data-uri, "bounds": [[s, w], [n, e]]}, or None if the
    distance CSV is missing.

    Two things make this worth doing as a raster. The bands are a 0.001 degree
    lattice whose edges follow every road, so as contour polygons they come to
    1.1M vertices and about 4 MB even simplified; as an indexed PNG the same
    grid at full resolution is ~160 KB. And the rows are RESAMPLED TO MERCATOR
    spacing here, because Leaflet stretches an image overlay linearly in screen
    space - handing it an equirectangular grid misplaces mid-state latitudes by
    246 m, a fifth of a squadrat, which would put the colours slightly north of
    the tiles they describe.
    """
    import numpy as np
    import pandas as pd
    from PIL import Image

    if not Path(path).exists():
        print(f"Note: {path} not found - building the map without the heatmap.")
        return None

    df = pd.read_csv(path)
    lats = np.sort(df["lat"].unique())
    lons = np.sort(df["long"].unique())
    d_lat = lats[1] - lats[0]
    d_lon = lons[1] - lons[0]
    rows, cols = len(lats), len(lons)

    # Band index per cell; 0 stays transparent for everything outside CT.
    edges = [b for b, _ in HEATMAP_BANDS[:-1]]
    grid = np.zeros((rows, cols), dtype=np.uint8)
    # searchsorted against the exact lattice values, not arithmetic on the
    # step size - deriving d_lat from two adjacent floats drifts by enough to
    # push the final row one index past the end of the array.
    r = np.searchsorted(lats, df["lat"].to_numpy())
    c = np.searchsorted(lons, df["long"].to_numpy())
    grid[r, c] = np.digitize(df["Dist"].to_numpy(), edges) + 1

    # Outer edges of the lattice, not cell centres - these are the image bounds.
    south, north = lats[0] - d_lat / 2, lats[-1] + d_lat / 2
    west, east = lons[0] - d_lon / 2, lons[-1] + d_lon / 2

    # Resample rows so equal pixel steps are equal Mercator steps.
    y_north, y_south = _mercator_y(north), _mercator_y(south)
    y_mid = y_north - (np.arange(rows) + 0.5) * (y_north - y_south) / rows
    lat_of_row = np.degrees(2 * np.arctan(np.exp(y_mid)) - math.pi / 2)
    src = np.clip(((lat_of_row - south) / d_lat).astype(int), 0, rows - 1)
    image_rows = grid[src]          # row 0 is now the north edge

    palette = [0, 0, 0]
    for _, rgb in HEATMAP_BANDS:
        palette += list(rgb)

    img = Image.fromarray(image_rows, mode="P")
    img.putpalette(palette + [0] * (768 - len(palette)))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True, transparency=0)
    png = buf.getvalue()

    print(f"Heatmap overlay: {cols} x {rows} cells, {len(png) / 1024:.0f} KB PNG")
    return {
        "url": "data:image/png;base64," + base64.b64encode(png).decode("ascii"),
        "bounds": [[float(south), float(west)], [float(north), float(east)]],
    }


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Unwalked Squadrats - Connecticut</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<style>
  :root {
    --bg: #14161a;
    --panel: #1c1f26;
    --line: #2d323d;
    --text: #e6e8ec;
    --dim: #9aa2b1;
    --accent: #d000d0;
  }
  * { box-sizing: border-box; }
  /* The grid really is a 0.001 deg lattice; let it look like one rather than
     smoothing it into a precision the data does not have. */
  .heatmap-img { image-rendering: pixelated; image-rendering: crisp-edges; }
  #heat-opacity { width: 100%; margin: 6px 0 2px; accent-color: var(--accent); }
  .legend { display: flex; flex-wrap: wrap; gap: 2px 8px; margin-top: 6px; }
  .legend span { display: flex; align-items: center; gap: 4px; font-size: 11px; color: var(--dim); }
  .legend i { width: 11px; height: 11px; border: 1px solid #0006; flex: none; }
  html, body { height: 100%; margin: 0; }
  body {
    display: flex; font: 14px/1.45 system-ui, -apple-system, Segoe UI, sans-serif;
    background: var(--bg); color: var(--text);
  }
  #sidebar {
    width: 300px; flex: none; display: flex; flex-direction: column;
    background: var(--panel); border-right: 1px solid var(--line);
  }
  #sidebar header { padding: 14px 16px; border-bottom: 1px solid var(--line); }
  h1 { margin: 0 0 10px; font-size: 15px; }
  .stats { display: flex; gap: 16px; }
  .stat .n { font-size: 20px; font-weight: 600; font-variant-numeric: tabular-nums; }
  .stat .n.unwalked { color: var(--accent); }
  .stat .k { font-size: 11px; color: var(--dim); text-transform: uppercase; letter-spacing: .06em; }
  .controls { padding: 10px 16px; border-bottom: 1px solid var(--line); }
  input[type=search] {
    width: 100%; padding: 7px 9px; border-radius: 6px; background: #12141a;
    border: 1px solid var(--line); color: var(--text); font-size: 13px;
  }
  label.toggle { display: flex; align-items: center; gap: 7px; margin-top: 9px; font-size: 13px; color: var(--dim); }
  #towns { flex: 1; overflow-y: auto; }
  .town {
    display: flex; justify-content: space-between; align-items: baseline; gap: 8px;
    padding: 7px 16px; cursor: pointer; border-bottom: 1px solid #23262e;
  }
  .town:hover { background: #262a33; }
  .town .name { flex: 1; }
  .town .count { color: var(--accent); font-weight: 600; font-variant-numeric: tabular-nums; }
  .town .pct { color: var(--dim); font-size: 12px; min-width: 44px; text-align: right; font-variant-numeric: tabular-nums; }
  #map { flex: 1; background: #0d0f12; }
  .leaflet-popup-content { font: 13px/1.5 system-ui, sans-serif; margin: 10px 12px; }
  footer { padding: 9px 16px; font-size: 11px; color: var(--dim); border-top: 1px solid var(--line); }
  @media (max-width: 700px) {
    body { flex-direction: column; }
    #sidebar { width: 100%; height: 46%; }
  }
</style>
</head>
<body>
<div id="sidebar">
  <header>
    <h1>Unwalked Squadrats &mdash; z14</h1>
    <div class="stats">
      <div class="stat"><div class="n unwalked" id="s-unwalked"></div><div class="k">unwalked</div></div>
      <div class="stat"><div class="n" id="s-earned"></div><div class="k">earned</div></div>
      <div class="stat"><div class="n" id="s-pct"></div><div class="k">complete</div></div>
    </div>
  </header>
  <div class="controls">
    <input type="search" id="filter" placeholder="Filter towns&hellip;" autocomplete="off">
    <label class="toggle"><input type="checkbox" id="show-towns" checked> Town boundaries</label>
    <label class="toggle"><input type="checkbox" id="show-earned"> Earned squadrats</label>
    <label class="toggle" id="heat-row"><input type="checkbox" id="show-heat" checked> Coverage heatmap</label>
    <input type="range" id="heat-opacity" min="0" max="100" value="65" title="Heatmap opacity">
    <div class="legend" id="heat-legend"></div>
  </div>
  <div id="towns"></div>
  <footer>Each square is ~1.14 mi on a side. Click one for its location.</footer>
</div>
<div id="map"></div>
<script>
var HEATMAP = __HEATMAP__;
var SQUADRATS = __SQUADRATS__;
var TOWNS = __TOWNS__;
var TOWN_STATS = __TOWN_STATS__;
var META = __META__;
var ACCENT = "__ACCENT__";

var map = L.map('map').setView([41.6, -72.7], 9);

// Basemap tiles come from CARTO, not tile.openstreetmap.org. OSM's
// volunteer servers block this map: opened from disk it is a file:// page,
// which sends no Referer and an Origin of null, so their operators cannot
// identify the app and refuse it under the tile usage policy. The data is
// still OpenStreetMap's and is credited as such.
var OSM_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
var CARTO_ATTR = OSM_ATTR + ' &copy; <a href="https://carto.com/attributions">CARTO</a>';

var CARTO_SUFFIX = '__CARTO_SUFFIX__';
function cartoLayer(style) {
  return L.tileLayer(
    'https://basemaps.cartocdn.com/rastertiles/' + style + '/{z}/{x}/{y}.png' + CARTO_SUFFIX,
    { maxZoom: 20, attribution: CARTO_ATTR }
  );
}
// Its own pane, between the basemap tiles (200) and the vector overlays
// (400), so the coverage colours sit under the squadrat outlines instead of
// washing them out.
map.createPane('heatPane');
map.getPane('heatPane').style.zIndex = 250;
map.getPane('heatPane').style.pointerEvents = 'none';

var heat = null;
if (HEATMAP) {
  heat = L.imageOverlay(HEATMAP.url, HEATMAP.bounds, {
    pane: 'heatPane', opacity: 0.65, className: 'heatmap-img', interactive: false
  }).addTo(map);
}

var streets = cartoLayer('voyager').addTo(map);
var light = cartoLayer('light_all');
var dark = cartoLayer('dark_all');
var sat = L.tileLayer(
  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
  { maxZoom: 19, attribution: 'Imagery &copy; Esri' }
);
L.control.layers({ 'Streets': streets, 'Light': light, 'Dark': dark, 'Satellite': sat },
                 null, { position: 'topright' }).addTo(map);

var HEAT_BANDS = __HEAT_BANDS__;

(function () {
  var row = document.getElementById('heat-row');
  var slider = document.getElementById('heat-opacity');
  var legend = document.getElementById('heat-legend');
  var box = document.getElementById('show-heat');

  if (!heat) {                       // no distance grid available at build time
    row.style.display = 'none';
    slider.style.display = 'none';
    return;
  }

  HEAT_BANDS.forEach(function (b) {
    var el = document.createElement('span');
    el.innerHTML = '<i style="background:' + b[1] + '"></i>' + b[0];
    legend.appendChild(el);
  });

  box.addEventListener('change', function () {
    if (box.checked) { heat.addTo(map); } else { map.removeLayer(heat); }
    slider.disabled = !box.checked;
  });
  slider.addEventListener('input', function () {
    heat.setOpacity(slider.value / 100);
  });
})();

function popupHtml(p) {
  var gmaps = 'https://www.google.com/maps?q=' + p.center_lat + ',' + p.center_lon;
  return '<b>' + p.town + '</b><br>' +
    (p.status === 'earned' ? 'Earned' : 'Unwalked') + ' squadrat<br>' +
    '<code>z' + p.z + ' / ' + p.x + ' / ' + p.y + '</code><br>' +
    p.center_lat.toFixed(5) + ', ' + p.center_lon.toFixed(5) + '<br>' +
    '<a href="' + gmaps + '" target="_blank" rel="noopener">Open in Google Maps</a>';
}

var unwalkedFeatures = SQUADRATS.features.filter(function (f) {
  return f.properties.status === 'unwalked';
});
var earnedFeatures = SQUADRATS.features.filter(function (f) {
  return f.properties.status === 'earned';
});

var unwalkedLayer = L.geoJSON(unwalkedFeatures, {
  style: { color: ACCENT, weight: 1.5, opacity: 0.9, fillColor: ACCENT, fillOpacity: 0.22 },
  onEachFeature: function (f, layer) { layer.bindPopup(popupHtml(f.properties)); }
}).addTo(map);

var earnedLayer = L.geoJSON(earnedFeatures, {
  style: { color: '#3fb950', weight: 0.7, opacity: 0.5, fill: false },
  onEachFeature: function (f, layer) { layer.bindPopup(popupHtml(f.properties)); }
});

var townLayer = L.geoJSON(TOWNS, {
  style: { color: '#7d8899', weight: 1, opacity: 0.55, fill: false },
  interactive: false
}).addTo(map);

document.getElementById('s-unwalked').textContent = META.unwalked.toLocaleString();
document.getElementById('s-earned').textContent = META.earned.toLocaleString();
document.getElementById('s-pct').textContent =
  (100 * META.earned / META.tiles_in_region).toFixed(1) + '%';

var townsEl = document.getElementById('towns');
var townBounds = {};
unwalkedFeatures.forEach(function (f) {
  var t = f.properties.town;
  var b = L.geoJSON(f).getBounds();
  townBounds[t] = townBounds[t] ? townBounds[t].extend(b) : b;
});

function renderTowns(query) {
  var q = (query || '').toLowerCase();
  townsEl.innerHTML = '';
  TOWN_STATS.filter(function (s) {
    return s.town.toLowerCase().indexOf(q) !== -1;
  }).forEach(function (s) {
    var row = document.createElement('div');
    row.className = 'town';
    row.innerHTML = '<span class="name"></span>' +
      '<span class="count">' + s.unwalked + '</span>' +
      '<span class="pct">' + s.pct.toFixed(0) + '%</span>';
    row.querySelector('.name').textContent = s.town;
    row.title = s.earned + ' of ' + s.total + ' squadrats earned';
    row.onclick = function () {
      if (townBounds[s.town]) map.fitBounds(townBounds[s.town].pad(0.25));
    };
    townsEl.appendChild(row);
  });
}
renderTowns();
document.getElementById('filter').addEventListener('input', function (e) {
  renderTowns(e.target.value);
});

document.getElementById('show-towns').addEventListener('change', function (e) {
  if (e.target.checked) { townLayer.addTo(map); } else { map.removeLayer(townLayer); }
});
document.getElementById('show-earned').addEventListener('change', function (e) {
  if (e.target.checked) { earnedLayer.addTo(map); earnedLayer.bringToBack(); }
  else { map.removeLayer(earnedLayer); }
});

// Where am I - for use while actually out walking
var locateBtn = L.control({ position: 'topleft' });
locateBtn.onAdd = function () {
  var div = L.DomUtil.create('div', 'leaflet-bar');
  div.innerHTML = '<a href="#" title="Show my location" style="font-size:16px">&#9678;</a>';
  L.DomEvent.on(div, 'click', L.DomEvent.stop);
  L.DomEvent.on(div, 'click', function () { map.locate({ setView: true, maxZoom: 14 }); });
  return div;
};
locateBtn.addTo(map);
map.on('locationfound', function (e) {
  L.circleMarker(e.latlng, { radius: 6, color: '#4aa3ff' }).addTo(map);
});

// Remember the last view between sessions
function defaultView() {
  if (unwalkedFeatures.length) map.fitBounds(unwalkedLayer.getBounds().pad(0.05));
}
try {
  var saved = JSON.parse(localStorage.getItem('squadrats-view') || 'null');
  if (saved) { map.setView(saved.center, saved.zoom); } else { defaultView(); }
  map.on('moveend', function () {
    try {
      localStorage.setItem('squadrats-view',
        JSON.stringify({ center: map.getCenter(), zoom: map.getZoom() }));
    } catch (err) { /* private window */ }
  });
} catch (err) {
  defaultView();
}
</script>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geojson", default=GEOJSON_IN, help=f"input tiles (default {GEOJSON_IN})")
    parser.add_argument("--output", default=OUTPUT_HTML, help=f"output HTML (default {OUTPUT_HTML})")
    parser.add_argument("--no-heatmap", action="store_true",
                        help="Skip the coverage heatmap overlay (a ~210 KB data URI).")
    parser.add_argument("--carto-key", default=None,
                        help="CARTO basemap key (default: the CARTO environment variable)")
    args = parser.parse_args()
    key = carto_key(args.carto_key)
    overlay = None if args.no_heatmap else build_heatmap_overlay()

    with open(args.geojson, "r") as f:
        squadrats_fc = json.load(f)

    meta = squadrats_fc.get("properties", {})
    towns = load_towns_simplified()
    stats = load_town_stats()

    html = (
        TEMPLATE
        .replace("__SQUADRATS__", json.dumps(squadrats_fc, separators=(",", ":")))
        .replace("__TOWNS__", json.dumps(towns, separators=(",", ":")))
        .replace("__TOWN_STATS__", json.dumps(stats, separators=(",", ":")))
        .replace("__META__", json.dumps(meta, separators=(",", ":")))
        .replace("__ACCENT__", SQUADRAT_COLOR)
        .replace("__HEAT_BANDS__", json.dumps(heatmap_legend(), separators=(",", ":")))
        .replace("__HEATMAP__", json.dumps(overlay, separators=(",", ":")))
        .replace("__CARTO_SUFFIX__", f"?key={key}" if key else "")
    )

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html)

    n_unwalked = sum(
        1 for x in squadrats_fc["features"] if x["properties"]["status"] == "unwalked"
    )
    print(f"Wrote {args.output} ({len(html) / 1024:.0f} KB, "
          f"{n_unwalked:,} unwalked tiles, {len(towns['features'])} town outlines)")


if __name__ == "__main__":
    main()
