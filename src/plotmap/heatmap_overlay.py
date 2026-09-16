"""
The coverage heatmap as a raster overlay, in one place.

Renders Distance_3_ct.csv - the 0.001-degree distance-from-walked lattice - to
an indexed PNG that Leaflet can drop on the map with L.imageOverlay. Both web
pages use it and must not disagree about where the colours sit, which is the
whole reason it lives here rather than in either one of them.

They differ only in how they carry the bytes, and for a real reason:

  squadrats_map.html      opens by double-clicking, off file://, where a
                          separate PNG is a second request the browser will
                          not make. It inlines the raster as a data URI.
  connecticut-ultrawalker fetches its point tiles at query time and therefore
                          only ever works over http(s) anyway. It writes the
                          raster to a file next to index.html, which keeps
                          ~200 KB of base64 out of the committed HTML and lets
                          the browser cache the image separately from the page.

Hence build_overlay() hands back raw PNG bytes and bounds, and each caller
decides. png_data_uri() is here so the inlining path is not re-derived either.

Two things make a raster the right shape for this. The bands follow a lattice
whose edges trace every road, so as contour polygons they come to 1.1M
vertices and about 4 MB even simplified, against ~160 KB as an indexed PNG at
full resolution. And the rows have to be RESAMPLED TO MERCATOR spacing here,
because Leaflet stretches an image overlay linearly in screen space - handing
it an equirectangular grid misplaces mid-state latitudes by 246 m, a fifth of
a squadrat, which would put the colours slightly north of the ground they
describe.

The trap worth keeping in one place: the raster is laid out on the GEOMETRIC
lattice, never on the sorted list of latitudes the CSV happens to contain.
Those are not the same thing. The CT outline clips whole rows away wherever
the state is only a few cells wide, and indexing by position in the
unique-value list then packs N rows of data into more than N rows of latitude,
sliding every row above a gap south of the ground it describes. Row index has
to come from the latitude itself.
"""

import base64
import io
import math
from pathlib import Path

import coverage_bands

DISTANCE_CSV = "Distance_3_ct.csv"

# Vertical oversampling for the Mercator resample. 2 is enough for
# Connecticut: the Mercator stretch top-to-bottom is well under a factor of 2,
# so no source row can fall between output rows.
MERCATOR_OVERSAMPLE = 2


def _mercator_y(lat_deg):
    """Web Mercator y for a latitude in degrees."""
    phi = math.radians(lat_deg)
    return math.log(math.tan(math.pi / 4 + phi / 2))


def _lattice_step(values):
    """The spacing of a regular lattice, read off values that may have holes.

    The smallest gap between adjacent distinct values is the step: a missing
    row widens one gap to a multiple of the step but never produces a smaller
    one. Rounded to 1e-9 so float noise in the CSV cannot make it look like
    two different steps.
    """
    import numpy as np

    gaps = np.diff(np.unique(values))
    return float(np.round(gaps.min(), 9))


def build_overlay(path=DISTANCE_CSV):
    """Render the distance grid to a PNG for L.imageOverlay.

    Returns {"png": bytes, "bounds": [[s, w], [n, e]], "size": (w, h)}, or
    None if the distance CSV is missing - callers draw the map without it
    rather than failing.
    """
    import numpy as np
    import pandas as pd
    from PIL import Image

    if not Path(path).exists():
        print(f"Note: {path} not found - building the map without the heatmap.")
        return None

    df = pd.read_csv(path)
    lat = df["lat"].to_numpy()
    lon = df["long"].to_numpy()

    # Smallest gap between adjacent distinct values, which is the lattice step
    # even when rows are missing. Taking lats[1] - lats[0] would work only when
    # no gap happens to fall at row 1.
    d_lat = _lattice_step(lat)
    d_lon = _lattice_step(lon)

    lat0, lat1 = lat.min(), lat.max()
    lon0, lon1 = lon.min(), lon.max()
    rows = int(round((lat1 - lat0) / d_lat)) + 1
    cols = int(round((lon1 - lon0) / d_lon)) + 1

    # Band index per cell; 0 stays transparent for everything outside CT.
    # Index from the coordinate, so a row with no cells inside Connecticut
    # stays an empty row instead of closing the gap and shifting its neighbours.
    grid = np.zeros((rows, cols), dtype=np.uint8)
    r = np.rint((lat - lat0) / d_lat).astype(int)
    c = np.rint((lon - lon0) / d_lon).astype(int)
    grid[r, c] = coverage_bands.band_index(df["Dist"].to_numpy())

    # Outer edges of the lattice, not cell centres - these are the image bounds.
    south, north = lat0 - d_lat / 2, lat1 + d_lat / 2
    west, east = lon0 - d_lon / 2, lon1 + d_lon / 2

    # Resample rows so equal pixel steps are equal Mercator steps. The output
    # is OVERSAMPLED vertically: at 1:1 the Mercator stretch across the state
    # is enough that nearest-neighbour sampling skips a source row or two
    # outright. Asking for MERCATOR_OVERSAMPLE times as many rows gives every
    # source row at least one pixel, and duplicate rows cost almost nothing in
    # an indexed PNG.
    out_rows = rows * MERCATOR_OVERSAMPLE
    y_north, y_south = _mercator_y(north), _mercator_y(south)
    y_mid = y_north - (np.arange(out_rows) + 0.5) * (y_north - y_south) / out_rows
    lat_of_row = np.degrees(2 * np.arctan(np.exp(y_mid)) - math.pi / 2)
    src = np.clip(((lat_of_row - south) / d_lat).astype(int), 0, rows - 1)
    image_rows = grid[src]          # row 0 is now the north edge

    img = Image.fromarray(image_rows, mode="P")
    img.putpalette(coverage_bands.png_palette())
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True, transparency=0)
    png = buf.getvalue()

    print(f"Heatmap overlay: {cols} x {rows} cells -> {cols} x {out_rows} px, "
          f"{len(png) / 1024:.0f} KB PNG")
    return {
        "png": png,
        "bounds": [[float(south), float(west)], [float(north), float(east)]],
        "size": (cols, out_rows),
    }


def png_data_uri(png):
    """The bytes as a data URI, for the page that has to inline them."""
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")
