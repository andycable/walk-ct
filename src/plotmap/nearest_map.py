"""
Build connecticut-ultrawalker/index.html - "how close have I walked to here?"

Type a Connecticut address, or tap the map, and the page finds the nearest
point I have actually walked, in feet, along with the date, the walk it came
from and a link to it on Strava.

    python nearest_tiles.py      # first: build the point tiles
    python nearest_map.py

Unlike squadrats_map.py this page CANNOT be opened by double-clicking it. It
fetches tiles at query time, and fetch() of a local file is blocked under
file:// - it needs to be served over http(s). See the README in
connecticut-ultrawalker/ for the one-line local server and the Pages setup.

The page carries a noindex meta tag, deliberately and not by accident: the
intent is unlisted-but-reachable. Note that robots.txt is left alone on
purpose - a Disallow rule would stop crawlers reading the noindex, which is
the opposite of what unlisted means, and would advertise the path besides.
"""

import argparse
import json
import os
from pathlib import Path

import coverage_bands
import ct_outline
import heatmap_overlay

REPO_ROOT = Path(__file__).resolve().parents[2]
SITE_DIR = REPO_ROOT / "connecticut-ultrawalker"
TILE_DIR = SITE_DIR / "tiles"
OUTPUT_HTML = SITE_DIR / "index.html"

# The coverage heatmap rides as a FILE beside the page, not as a data URI
# baked into it the way squadrats_map.html carries its copy. That page has to
# survive being double-clicked off file://; this one fetches its point tiles
# over http(s) regardless, so a separate PNG costs nothing and keeps ~240 KB
# of base64 out of the committed HTML - and lets the browser cache the raster
# apart from the page that changes every rebuild.
HEATMAP_PNG = SITE_DIR / "heatmap.png"

# Same key handling as squadrats_map.py: read from the environment and bake it
# into the committed HTML.
CARTO_KEY_ENV = "CARTO"

ACCENT = "#d000d0"          # matches squadrats.SQUADRAT_COLOR

# The walked points, distinct from the squadrat pink. Two of them: the sky blue
# is unreadable on the Streets and Light basemaps, and the deep blue disappears
# on Dark and Satellite. The page swaps them with the basemap.
WALKED_DARK = "#38bdf8"
WALKED_LIGHT = "#0369a1"

# Connecticut, for the geocoder viewbox and the "is this even in CT" check.
CT_BBOX = (40.95, 42.06, -73.75, -71.78)   # south, north, west, east

# Each town's box is padded this far, in degrees (~0.3 mi), before it bounds
# the geocoder: an address on a boundary road can sit a few metres over the
# line it is filed under.
TOWN_PAD = 0.005

# The furthest any point in Connecticut is from somewhere I have walked, in
# miles, straight off Distance_3_ct.csv. It bounds the tile ring search and it
# is the most quotable number on the page.
#
# It was 2.38 until ct_outline started dropping the islands, and the far corner
# was Chimon Island off Norwalk - a number about boats, quoted on a page about
# walking. The mainland answer is 1.67, in the Stafford woods up on the
# Massachusetts line. Tapping an island still works: the ring search only gives
# up past MAX_CT_DISTANCE * 3, which is 5.0 mi against the 2.38 an island tap
# needs.
MAX_CT_DISTANCE = 1.67


def carto_key(explicit=None):
    """The CARTO basemap key, from --carto-key or the CARTO env var."""
    key = explicit or os.environ.get(CARTO_KEY_ENV, "")
    if not key:
        print(f"WARNING: no {CARTO_KEY_ENV} environment variable and no "
              f"--carto-key given.")
        print(f"         Basemap tiles will be watermarked, and regenerating "
              f"this way strips the key out of {OUTPUT_HTML.name}.")
    return key


def town_boxes(pad=TOWN_PAD):
    """[[name, south, north, west, east], ...] for the 169 towns, by name.

    For the town pick-list: a picked town bounds the geocoder to its box and
    zooms the map to it. Boxes rather than outlines - 169 rectangles are ~7 KB
    in the page, the outlines would be megabytes, and the geocoder only takes
    a rectangle anyway.
    """
    boxes = []
    for name, poly in ct_outline.town_polygons():
        w, s, e, n = poly.bounds
        boxes.append([name, round(s - pad, 4), round(n + pad, 4),
                      round(w - pad, 4), round(e + pad, 4)])
    return sorted(boxes)


def load_index(path=TILE_DIR / "index.json"):
    """The tile geometry written by nearest_tiles.py."""
    if not path.exists():
        raise SystemExit(f"{path} not found - run nearest_tiles.py first.")
    return json.loads(path.read_text(encoding="utf-8"))


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Connecticut Ultrawalker</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<style>
  :root {
    --bg: #14161a;
    --panel: #1c1f26;
    --line: #2d323d;
    --text: #e6e8ec;
    --dim: #9aa2b1;
    --accent: __ACCENT__;
    /* Both are repainted by setBasemapTheme() when the basemap changes: the
       sky blue and the white line vanish against Streets and Light. */
    --walked: __WALKED_DARK__;
    --ink: #ffffff;
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body {
    display: flex; font: 14px/1.45 system-ui, -apple-system, Segoe UI, sans-serif;
    background: var(--bg); color: var(--text);
  }
  #sidebar {
    width: 330px; flex: none; display: flex; flex-direction: column;
    background: var(--panel); border-right: 1px solid var(--line);
    overflow-y: auto;
  }
  #sidebar header { padding: 14px 16px; border-bottom: 1px solid var(--line); }
  h1 { margin: 0; font-size: 15px; }
  .sub { color: var(--dim); font-size: 12px; margin-top: 4px; }
  .controls { padding: 12px 16px; border-bottom: 1px solid var(--line); }
  form { display: flex; gap: 6px; }
  input[type=search] {
    flex: 1; min-width: 0; padding: 9px 10px; border-radius: 6px;
    background: #12141a; color: var(--text); border: 1px solid var(--line);
    font-size: 16px;   /* 16px or iOS zooms the whole page on focus */
  }
  input[type=search]:focus { outline: none; border-color: var(--accent); }
  select#town {
    width: 100%; margin-bottom: 6px; padding: 8px 8px; border-radius: 6px;
    background: #12141a; color: var(--text); border: 1px solid var(--line);
    font-size: 16px;   /* same iOS focus-zoom rule as the search box */
  }
  select#town:focus { outline: none; border-color: var(--accent); }
  button {
    padding: 9px 12px; border-radius: 6px; border: 1px solid var(--line);
    background: #262b34; color: var(--text); font-size: 13px; cursor: pointer;
  }
  button:hover { border-color: var(--accent); }
  button:disabled { opacity: .5; cursor: default; }
  .hint { color: var(--dim); font-size: 11.5px; margin-top: 8px; }
  .hint a { color: var(--dim); }
  #result { padding: 14px 16px; border-bottom: 1px solid var(--line); }
  .matched { color: var(--dim); font-size: 12px; margin-bottom: 10px; word-break: break-word; }
  .dist { font-size: 30px; font-weight: 600; font-variant-numeric: tabular-nums; line-height: 1.1; }
  .dist.close { color: var(--accent); }
  .dist-k { font-size: 11px; color: var(--dim); text-transform: uppercase; letter-spacing: .06em; }
  .when { margin-top: 12px; font-size: 13px; }
  .when .name { color: var(--dim); font-size: 12px; margin-top: 2px; word-break: break-word; }
  .when a { color: var(--accent); }
  .muted { color: var(--dim); }
  .err { color: #f87171; font-size: 13px; }
  .spin { color: var(--dim); font-size: 13px; }
  footer { padding: 12px 16px; color: var(--dim); font-size: 11.5px; margin-top: auto; }
  footer b { color: var(--text); font-weight: 600; font-variant-numeric: tabular-nums; }
  label.toggle { display: flex; align-items: center; gap: 7px; font-size: 12px; color: var(--dim); margin-top: 10px; }
  /* Nearest-neighbour, or the browser smooths a 0.001-degree lattice into
     mush and the quarter-mile bands stop having edges. */
  .heatmap-img { image-rendering: pixelated; image-rendering: crisp-edges; }
  #heat-opacity { width: 100%; margin: 8px 0 2px; accent-color: var(--accent); }
  .legend { display: flex; flex-wrap: wrap; gap: 2px 8px; margin-top: 6px; }
  .legend span { display: flex; align-items: center; gap: 4px; font-size: 11px; color: var(--dim); }
  .legend i { width: 11px; height: 11px; border: 1px solid #0006; flex: none; }
  #map { flex: 1; min-width: 0; background: var(--bg); }
  .leaflet-container { background: #0e1013; }
  .pin {
    width: 14px; height: 14px; border-radius: 50%;
    background: var(--accent); border: 2px solid #fff; box-shadow: 0 0 0 2px #0008;
  }
  /* The phone is the point of this page - the sidebar has to stop being a
     sidebar before it eats the map. */
  @media (max-width: 760px) {
    body { flex-direction: column; }
    #sidebar { width: auto; max-height: 55%; border-right: none; border-bottom: 1px solid var(--line); }
    #map { min-height: 45vh; }
    footer { display: none; }
  }
</style>
</head>
<body>
<div id="sidebar">
  <header>
    <h1>Connecticut Ultrawalker</h1>
    <div class="sub">How close have I walked to your door?</div>
  </header>
  <div class="controls">
    <select id="town" aria-label="Town"><option value="">Any town</option></select>
    <form id="form">
      <input type="search" id="q" placeholder="Address, or town in CT"
             autocomplete="off" autocapitalize="off" spellcheck="false">
      <button type="submit" id="go">Find</button>
    </form>
    <div class="hint">or tap the map anywhere in Connecticut
      &middot; <a href="#" id="locate">use my location</a></div>
    <label class="toggle"><input type="checkbox" id="show-pts" checked>
      show my walked points nearby</label>
    <label class="toggle"><input type="checkbox" id="show-heat" checked>
      show the coverage heatmap</label>
    <input type="range" id="heat-opacity" min="0" max="100" value="65">
    <div class="legend" id="legend"></div>
  </div>
  <div id="result"><span class="muted">Enter an address to begin.</span></div>
  <footer>
    <b>__POINTS__</b> walked points from <b>__ACTIVITIES__</b> walks,
    __FIRST__ to __LAST__.<br>
    Nowhere in Connecticut is more than <b>__MAX_DIST__ mi</b> from one of
    them - and the far corner is up in the Stafford woods, on the
    Massachusetts line.
  </footer>
</div>
<div id="map"></div>
<script>
const G = __GRID__;
const CT = __CT_BBOX__;            // [south, north, west, east]
const TOWNS = __TOWNS__;           // [[name, south, north, west, east], ...]
const MAX_DIST = __MAX_DIST__;
const HEATMAP = __HEATMAP__;       // {url, bounds} or null
const HEAT_BANDS = __HEAT_BANDS__;
const I0 = Math.round(G.lat0 / G.tile), J0 = Math.round(G.lon0 / G.tile);
const TILES = new Set(G.tiles);
const cache = new Map();

/* Miles per degree, the same WGS84 series distance_from_parquet.py uses.
   Longitude shrinks by cos(lat): a degree of longitude in Connecticut is
   about 51 miles against latitude's 69, so the two axes cannot share one
   scale factor without putting every distance out by a third. */
function milesPerDegree(lat) {
  const phi = lat * Math.PI / 180;
  const mLat = 111132.92 - 559.82 * Math.cos(2 * phi)
             + 1.175 * Math.cos(4 * phi) - 0.0023 * Math.cos(6 * phi);
  const mLon = 111412.84 * Math.cos(phi) - 93.5 * Math.cos(3 * phi)
             + 0.118 * Math.cos(5 * phi);
  return [mLat / 1609.344, mLon / 1609.344];
}

function tileNumber(i, j) {
  if (i < I0 || j < J0 || i >= I0 + G.rows || j >= J0 + G.cols) return -1;
  return (i - I0) * G.cols + (j - J0);
}

/* One tile: uint32 n, then n dlat, n dlon (uint8 steps of G.step from the
   tile's SW corner), n uint16 activity indices, n uint8 visit counts. */
function decode(buf, i, j) {
  const n = new DataView(buf).getUint32(0, true);
  const dlat = new Uint8Array(buf, 4, n);
  const dlon = new Uint8Array(buf, 4 + n, n);
  const act = new Uint16Array(buf, 4 + 2 * n, n);
  const visits = new Uint8Array(buf, 4 + 4 * n, n);
  const lat = new Float64Array(n), lon = new Float64Array(n);
  const latBase = i * G.tile, lonBase = j * G.tile;
  for (let k = 0; k < n; k++) {
    lat[k] = latBase + dlat[k] * G.step;
    lon[k] = lonBase + dlon[k] * G.step;
  }
  return { n, lat, lon, act, visits };
}

function loadTile(i, j) {
  const t = tileNumber(i, j);
  if (t < 0 || !TILES.has(t)) return Promise.resolve(null);
  if (!cache.has(t)) {
    cache.set(t, fetch('tiles/' + t + '.bin')
      .then(r => r.ok ? r.arrayBuffer() : Promise.reject(r.status))
      .then(b => decode(b, i, j))
      .catch(() => null));
  }
  return cache.get(t);
}

/* Nearest walked point to (plat, plon).

   Rings outward a tile at a time and stops only when the best point found is
   closer than the nearest UNSEARCHED ground - the distance from the query to
   the edge of the loaded box. Stopping at the first non-empty ring would be
   wrong whenever the query sits near a tile edge, which is most of the time:
   a point 40 ft away across the boundary hides behind one 300 ft away inside
   it. */
async function nearest(plat, plon) {
  const [mLat, mLon] = milesPerDegree(plat);
  const ci = Math.floor(plat / G.tile), cj = Math.floor(plon / G.tile);
  const loaded = [];
  let best = null;

  for (let r = 0; r <= 14; r++) {
    const ring = [];
    for (let i = ci - r; i <= ci + r; i++) {
      for (let j = cj - r; j <= cj + r; j++) {
        // Only the new edge of the square; the interior came from earlier r.
        if (r > 0 && Math.abs(i - ci) !== r && Math.abs(j - cj) !== r) continue;
        ring.push(loadTile(i, j));
      }
    }
    for (const tile of await Promise.all(ring)) {
      if (!tile) continue;
      loaded.push(tile);
      for (let k = 0; k < tile.n; k++) {
        const dy = (tile.lat[k] - plat) * mLat;
        const dx = (tile.lon[k] - plon) * mLon;
        const d = Math.sqrt(dy * dy + dx * dx);
        if (!best || d < best.d) {
          best = { d, lat: tile.lat[k], lon: tile.lon[k],
                   act: tile.act[k], visits: tile.visits[k] };
        }
      }
    }
    const south = (ci - r) * G.tile, north = (ci + r + 1) * G.tile;
    const west = (cj - r) * G.tile, east = (cj + r + 1) * G.tile;
    const safe = Math.min((plat - south) * mLat, (north - plat) * mLat,
                          (plon - west) * mLon, (east - plon) * mLon);
    if (best && best.d <= safe) break;
    if (safe > MAX_DIST * 3) break;      // nothing out here; stop digging
  }
  return { best, loaded };
}

/* ---- map ---- */
const map = L.map('map', { zoomControl: true }).setView([41.6, -72.7], 9);

/* The same four basemaps squadrats_map.html offers, defaulting to Streets for
   the same reason: a dark basemap makes a street-level answer hard to read,
   and the two pages should not disagree about what Connecticut looks like.

   Each carries whether it is dark, because the marks drawn on top have to
   flip with it - sky blue dots and a white leader line disappear on Streets,
   and their dark counterparts disappear on Dark. */
const CARTO_SUFFIX = '__CARTO_SUFFIX__';
function cartoLayer(style) {
  return L.tileLayer(
    'https://basemaps.cartocdn.com/rastertiles/' + style + '/{z}/{x}/{y}.png' + CARTO_SUFFIX,
    { maxZoom: 20, attribution: __CARTO_ATTR__ });
}
const BASEMAPS = {
  'Streets': { layer: cartoLayer('voyager'), dark: false },
  'Light': { layer: cartoLayer('light_all'), dark: false },
  'Dark': { layer: cartoLayer('dark_all'), dark: true },
  'Satellite': { layer: L.tileLayer(
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      { maxZoom: 19, attribution: 'Imagery &copy; Esri' }), dark: true },
};
const THEME = {
  dark: { walked: '__WALKED_DARK__', ink: '#ffffff' },
  light: { walked: '__WALKED_LIGHT__', ink: '#1f2937' },
};

function setBasemapTheme(isDark) {
  const t = isDark ? THEME.dark : THEME.light;
  const root = document.documentElement.style;
  root.setProperty('--walked', t.walked);
  root.setProperty('--ink', t.ink);
}

BASEMAPS.Streets.layer.addTo(map);
setBasemapTheme(BASEMAPS.Streets.dark);
L.control.layers(
  Object.fromEntries(Object.entries(BASEMAPS).map(([k, v]) => [k, v.layer])),
  null, { position: 'topright' }).addTo(map);

/* The coverage heatmap: how far every corner of Connecticut is from somewhere
   I have walked, on the same quarter-mile bands as squadrats_map.html and the
   per-town PNGs, from the same Distance_3_ct.csv.

   Its own pane between the basemap tiles (200) and the vector overlays (400),
   so the walked dots and the answer marker draw ON TOP of the colours rather
   than being washed out by them. pointerEvents none keeps it from eating the
   map clicks this page is built around - tapping the map IS the query. */
map.createPane('heatPane');
map.getPane('heatPane').style.zIndex = 250;
map.getPane('heatPane').style.pointerEvents = 'none';

let heat = null;
if (HEATMAP) {
  heat = L.imageOverlay(HEATMAP.url, HEATMAP.bounds, {
    pane: 'heatPane', opacity: 0.65, className: 'heatmap-img',
    interactive: false,
  }).addTo(map);

  document.getElementById('legend').innerHTML = HEAT_BANDS
    .map(([label, rgb]) => '<span><i style="background:' + rgb + '"></i>' +
                           label + '</span>').join('');

  document.getElementById('show-heat').addEventListener('change', (e) => {
    if (e.target.checked) heat.addTo(map); else heat.remove();
    document.getElementById('heat-opacity').disabled = !e.target.checked;
  });
  document.getElementById('heat-opacity').addEventListener('input', (e) => {
    heat.setOpacity(e.target.value / 100);
  });
} else {
  /* No raster to show, so do not leave dead controls in the sidebar. */
  document.getElementById('show-heat').closest('label').style.display = 'none';
  document.getElementById('heat-opacity').style.display = 'none';
}

const dots = L.layerGroup().addTo(map);
const marks = L.layerGroup().addTo(map);
const canvas = L.canvas({ padding: 0.3 });
let lastLoaded = [], lastQuery = null, lastBest = null;

function cssVar(name) {
  return getComputedStyle(document.documentElement)
    .getPropertyValue(name).trim();
}

function fmt(miles) {
  const ft = miles * 5280;
  if (ft < 1000) return [Math.round(ft / 5) * 5 + '', 'feet away'];
  return [miles.toFixed(2), 'miles away'];
}

/* Walked points near the query, as a canvas layer. Circle markers are fine in
   the low thousands with a canvas renderer; as SVG the same count locks up a
   phone. Capped by distance so a far-flung tile does not drag in a whole
   town's worth of dots. */
function drawPoints(loaded, plat, plon) {
  dots.clearLayers();
  if (!document.getElementById('show-pts').checked) return;
  const [mLat, mLon] = milesPerDegree(plat);
  const limit = 0.75;
  let drawn = 0;
  for (const tile of loaded) {
    for (let k = 0; k < tile.n; k++) {
      const dy = (tile.lat[k] - plat) * mLat, dx = (tile.lon[k] - plon) * mLon;
      if (Math.sqrt(dy * dy + dx * dx) > limit) continue;
      L.circleMarker([tile.lat[k], tile.lon[k]], {
        renderer: canvas, radius: 1.6, stroke: false,
        fillColor: cssVar('--walked'), fillOpacity: 0.75,
      }).addTo(dots);
      if (++drawn > 12000) return;
    }
  }
}

function strava(id) {
  return id >= G.minStravaId
    ? '<a href="https://www.strava.com/activities/' + id +
      '" target="_blank" rel="noopener">View on Strava</a>'
    : '<span class="muted">no Strava link for this one</span>';
}

function show(html) { document.getElementById('result').innerHTML = html; }

function render(label, plat, plon, best, fit = true) {
  if (!best) {
    show('<div class="err">No walked points anywhere near that.</div>' +
         '<div class="hint">Is it inside Connecticut?</div>');
    return;
  }
  const [n, unit] = fmt(best.d);
  const a = G.activities[best.act];       // [id, "YYYY-MM-DD", name]
  const close = best.d * 5280 < 60;
  const times = best.visits > 1
    ? ' <span class="muted">&middot; passed ' + best.visits + ' times</span>'
    : '';
  show(
    '<div class="matched">' + label + '</div>' +
    '<div class="dist' + (close ? ' close' : '') + '">' + n + '</div>' +
    '<div class="dist-k">' + (close ? 'feet away - basically walked past it'
                                    : unit) + '</div>' +
    '<div class="when">First walked <b>' + a[1] + '</b>' + times +
    (a[2] ? '<div class="name">' + a[2] + '</div>' : '') +
    '<div style="margin-top:6px">' + strava(a[0]) + '</div></div>');

  marks.clearLayers();
  L.marker([plat, plon], { icon: L.divIcon({ className: '', html:
    '<div class="pin"></div>', iconSize: [14, 14], iconAnchor: [7, 7] }) })
    .addTo(marks).bindPopup(label);
  L.circleMarker([best.lat, best.lon], { radius: 5, color: cssVar('--ink'),
    weight: 2, fillColor: cssVar('--walked'), fillOpacity: 1 })
    .addTo(marks).bindPopup(n + ' ' + unit + '<br>' + a[1]);
  L.polyline([[plat, plon], [best.lat, best.lon]], {
    color: cssVar('--ink'), weight: 1.5, dashArray: '4 4', opacity: 0.8 })
    .addTo(marks);
  // Re-rendering after a basemap change must not yank the view back; the
  // viewer may have panned away since the search.
  if (fit) {
    map.fitBounds(L.latLngBounds([[plat, plon], [best.lat, best.lon]]),
                  { padding: [60, 60], maxZoom: 17 });
  }
}

async function query(plat, plon, label) {
  lastQuery = { plat, plon, label };
  show('<div class="spin">Looking...</div>');
  const { best, loaded } = await nearest(plat, plon);
  lastLoaded = loaded;
  lastBest = best;
  drawPoints(loaded, plat, plon);
  render(label, plat, plon, best);
  const url = new URL(location.href);
  url.searchParams.set('ll', plat.toFixed(6) + ',' + plon.toFixed(6));
  url.searchParams.set('q', label);
  history.replaceState(null, '', url);
}

/* ---- geocoding ----
   Nominatim sends CORS headers and needs no key; the US Census geocoder is
   better on rural street addresses but sends no Access-Control-Allow-Origin,
   so it cannot be called from a page at all. Photon picks up what Nominatim
   misses. Both are volunteer-run: one request per submit, never per keystroke.
   https://operations.osmfoundation.org/policies/nominatim/ */
/* Every query is a Connecticut query. A bare "12 Main St" otherwise lands in
   whichever Main St the geocoder likes best - the CT viewbox is a rectangle
   that takes in slices of NY, MA and RI, and Photon ignores it entirely - so
   the state goes on the end of the text, and a result only counts if the
   geocoder itself puts it in Connecticut. A trailing "CT" is spelled out
   rather than trusted: Nominatim reads "Greenwich CT" as Greenwich Court, in
   Middletown. */
function qualify(text, town) {
  const m = text.match(/^(.*?)[,\\s]*\\b(?:ct|conn|connecticut)\\b[.\\s]*(\\d{5})?\\s*$/i);
  const base = m ? m[1] : text, zip = m && m[2] ? ' ' + m[2] : '';
  return base + (town ? ', ' + town[0] : '') + ', Connecticut' + zip;
}

/* With a town picked, the search is bounded to that town's box, and inside
   the box a result that names the town beats one that does not - the box is
   a rectangle, so it always takes in corners of the neighbours. A town is
   named in a result if any address field is the town: OSM files the town
   under town, city or municipality depending on who mapped it, and a village
   like Mystic or Moosup puts its own name in front of the town's. */
function names(fields, town) {
  return !town || Object.values(fields || {}).includes(town[0]);
}

function inBox(lat, lon, b) {
  return lat >= b[0] && lat <= b[1] && lon >= b[2] && lon <= b[3];
}

function pick(hits, town) {
  return hits.find(h => names(h.fields, town)) || hits[0] || null;
}

async function geocode(text, town) {
  const b = town ? town.slice(1) : CT;                       // [S, N, W, E]
  const box = b[2] + ',' + b[1] + ',' + b[3] + ',' + b[0];    // W,N,E,S
  const q = encodeURIComponent(qualify(text, town));
  try {
    const r = await fetch('https://nominatim.openstreetmap.org/search?format=jsonv2'
      + '&limit=5&addressdetails=1&countrycodes=us&bounded=1&viewbox=' + box
      + '&q=' + q);
    const j = await r.json();
    const h = pick(j
      .filter(x => x.address && x.address['ISO3166-2-lvl4'] === 'US-CT'
                   && inBox(+x.lat, +x.lon, b))
      .map(x => ({ lat: +x.lat, lon: +x.lon, label: x.display_name,
                   fields: x.address })), town);
    if (h) return h;
  } catch (e) { /* fall through to Photon */ }
  try {
    const r = await fetch('https://photon.komoot.io/api/?limit=5&lat=41.6&lon=-72.7'
      + '&bbox=' + b[2] + ',' + b[0] + ',' + b[3] + ',' + b[1]
      + '&q=' + q);
    const j = await r.json();
    const f = pick((j.features || [])
      // Photon spells the state out for streets but sends "CT" for addresses.
      .filter(f => ['Connecticut', 'CT'].includes(f.properties.state))
      .map(f => ({ f, fields: f.properties })), town);
    if (f) {
      const c = f.f.geometry.coordinates, p = f.f.properties;
      const label = [p.name, p.street, p.city, p.state].filter(Boolean).join(', ');
      return { lat: c[1], lon: c[0], label: label || text };
    }
  } catch (e) { /* no geocoder reached */ }
  return null;
}

function inCT(lat, lon) {
  return lat >= CT[0] && lat <= CT[1] && lon >= CT[2] && lon <= CT[3];
}

/* ---- the town pick-list ----
   Picking a town zooms the map to it and narrows every search to it, so all
   that is left to type is the street. "Any town" puts the old whole-state
   search back. */
const townSel = document.getElementById('town');
townSel.insertAdjacentHTML('beforeend', TOWNS
  .map((t, i) => '<option value="' + i + '">' + t[0] + '</option>').join(''));

function pickedTown() {
  return townSel.value === '' ? null : TOWNS[+townSel.value];
}

function fitTown(t) {
  map.fitBounds([[t[1], t[3]], [t[2], t[4]]], { padding: [20, 20] });
}

function setTownUi() {
  const t = pickedTown();
  document.getElementById('q').placeholder =
    t ? 'Street or street address in ' + t[0] : 'Address, or town in CT';
}

townSel.addEventListener('change', () => {
  const t = pickedTown();
  setTownUi();
  const url = new URL(location.href);
  if (t) url.searchParams.set('town', t[0]); else url.searchParams.delete('town');
  history.replaceState(null, '', url);
  if (!t) return;
  fitTown(t);
  document.getElementById('q').focus();
});

document.getElementById('form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const text = document.getElementById('q').value.trim();
  const town = pickedTown();
  if (!text) {
    if (town) {
      fitTown(town);
      show('<div class="muted">Type a street in ' + town[0] +
           ', or tap the map.</div>');
    }
    return;
  }
  const go = document.getElementById('go');
  go.disabled = true;
  show('<div class="spin">Finding that address...</div>');
  const hit = await geocode(text, town);
  go.disabled = false;
  if (!hit) {
    show(town
      ? '<div class="err">Could not find that in ' + town[0] + '.</div>' +
        '<div class="hint">Check the spelling, switch to Any town, or tap ' +
        'the map instead.</div>'
      : '<div class="err">Could not find that address.</div>' +
        '<div class="hint">Try picking the town, or tap the map instead.</div>');
    return;
  }
  if (!inCT(hit.lat, hit.lon)) {
    show('<div class="err">That is outside Connecticut.</div>' +
         '<div class="hint">' + hit.label + '</div>');
    map.setView([hit.lat, hit.lon], 11);
    return;
  }
  query(hit.lat, hit.lon, hit.label);
});

map.on('baselayerchange', (e) => {
  const picked = Object.values(BASEMAPS).find(b => b.layer === e.layer);
  if (!picked) return;
  setBasemapTheme(picked.dark);
  if (lastQuery) {
    drawPoints(lastLoaded, lastQuery.plat, lastQuery.plon);
    render(lastQuery.label, lastQuery.plat, lastQuery.plon, lastBest, false);
  }
});

map.on('click', (e) => {
  const { lat, lng } = e.latlng;
  query(lat, lng, lat.toFixed(5) + ', ' + lng.toFixed(5));
});

document.getElementById('locate').addEventListener('click', (e) => {
  e.preventDefault();
  if (!navigator.geolocation) return;
  show('<div class="spin">Asking your browser where you are...</div>');
  navigator.geolocation.getCurrentPosition(
    (p) => query(p.coords.latitude, p.coords.longitude, 'Your location'),
    () => show('<div class="err">Could not get your location.</div>'),
    { enableHighAccuracy: true, timeout: 10000 });
});

document.getElementById('show-pts').addEventListener('change', () => {
  if (lastQuery) drawPoints(lastLoaded, lastQuery.plat, lastQuery.plon);
});

/* A result is shareable: ?ll=lat,lon carries the exact point, ?q= the label,
   ?town= the pick-list. */
(function start() {
  const p = new URLSearchParams(location.search);
  const ti = TOWNS.findIndex(t => t[0] === p.get('town'));
  if (ti >= 0) {
    townSel.value = String(ti);
    setTownUi();
    if (!p.get('ll') && !p.get('q')) fitTown(TOWNS[ti]);
  }
  const ll = p.get('ll');
  if (ll && /^-?\\d+(\\.\\d+)?,-?\\d+(\\.\\d+)?$/.test(ll)) {
    const [a, b] = ll.split(',').map(Number);
    if (p.get('q')) document.getElementById('q').value = p.get('q');
    query(a, b, p.get('q') || ll);
  } else if (p.get('q')) {
    document.getElementById('q').value = p.get('q');
    document.getElementById('form')
      .dispatchEvent(new Event('submit', { cancelable: true }));
  }
})();
</script>
</body>
</html>
"""

CARTO_ATTR = ('&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a>'
              ' &copy; <a href="https://carto.com/attributions">CARTO</a>')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", default=str(OUTPUT_HTML))
    ap.add_argument("--carto-key", default=None,
                    help="CARTO basemap key (default: the CARTO env var)")
    ap.add_argument("--no-heatmap", action="store_true",
                    help="skip the coverage heatmap overlay and its PNG")
    args = ap.parse_args()

    meta = load_index()
    key = carto_key(args.carto_key)

    overlay = None if args.no_heatmap else heatmap_overlay.build_overlay()
    if overlay:
        HEATMAP_PNG.parent.mkdir(parents=True, exist_ok=True)
        HEATMAP_PNG.write_bytes(overlay["png"])
        print(f"Wrote {HEATMAP_PNG} "
              f"({len(overlay['png']) / 1024:.0f} KB, {overlay['size'][0]}x"
              f"{overlay['size'][1]})")
        overlay = {"url": HEATMAP_PNG.name, "bounds": overlay["bounds"]}

    activities = meta["activities"]
    grid = {k: v for k, v in meta.items() if k != "points"}

    html = (
        TEMPLATE
        .replace("__GRID__", json.dumps(grid, separators=(",", ":")))
        .replace("__CT_BBOX__", json.dumps(list(CT_BBOX)))
        .replace("__TOWNS__", json.dumps(town_boxes(), separators=(",", ":")))
        .replace("__CARTO_SUFFIX__", f"?key={key}" if key else "")
        .replace("__CARTO_ATTR__", json.dumps(CARTO_ATTR))
        .replace("__ACCENT__", ACCENT)
        .replace("__WALKED_DARK__", WALKED_DARK)
        .replace("__WALKED_LIGHT__", WALKED_LIGHT)
        .replace("__MAX_DIST__", str(MAX_CT_DISTANCE))
        .replace("__HEATMAP__", json.dumps(overlay, separators=(",", ":")))
        .replace("__HEAT_BANDS__",
                 json.dumps(coverage_bands.legend_pairs(), separators=(",", ":")))
        .replace("__POINTS__", f"{meta['points']:,}")
        .replace("__ACTIVITIES__", f"{len(activities):,}")
        .replace("__FIRST__", activities[0][1][:7])
        .replace("__LAST__", activities[-1][1][:7])
    )

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"Wrote {out} ({len(html) / 1024:.0f} KB, "
          f"{len(meta['tiles']):,} tiles behind it)")


if __name__ == "__main__":
    main()
