"""
The coverage colour bands, in one place.

Every view of "how far is this ground from somewhere I have walked" uses the
same quarter-mile bands: the statewide heatmap, the per-town heatmaps, and the
raster overlay on the interactive map. The palette and the thresholds used to
be copied into all three - six copies once you count the fact that heatmap.py
and towns_heatmap.py each spelled them out twice, once to colour the grid and
again to build the legend. Six chances for two pictures of the same data to
disagree.

Colours are stored as 8-bit RGB because that is what actually reaches a screen;
rgb01() converts for matplotlib, which quantises back to the same bytes.
"""

import numpy as np

# Upper edge of each band in miles, its colour, and its legend label. The last
# band is open-ended.
BANDS = [
    (0.25, (173, 217, 255), "0.00–0.25 mi"),
    (0.50, (0, 128, 255), "0.25–0.50 mi"),
    (0.75, (0, 191, 255), "0.50–0.75 mi"),
    (1.00, (0, 191, 0), "0.75–1.00 mi"),
    (1.25, (255, 255, 0), "1.00–1.25 mi"),
    (1.50, (255, 165, 0), "1.25–1.50 mi"),
    (float("inf"), (255, 0, 0), ">1.50 mi"),
]

WALKED = ((255, 255, 255), "Walked (0 mi)")   # distance exactly 0
OUTSIDE = (242, 242, 242)                     # not in Connecticut

EDGES = [upper for upper, _, _ in BANDS[:-1]]


def rgb01(rgb):
    """8-bit RGB to the 0-1 floats matplotlib wants."""
    return tuple(c / 255.0 for c in rgb)


def band_index(distance):
    """Band number per cell: 0 walked, 1..7 by distance. NaN lands in band 7.

    Vectorised, so callers do not walk a million-cell grid in a Python loop.
    """
    distance = np.asarray(distance, dtype=float)
    index = np.digitize(distance, EDGES) + 1
    index[distance == 0] = 0
    return index


def rgb_grid(distance, outside=OUTSIDE):
    """Colour a distance grid, returning float RGB. NaN cells get `outside`."""
    distance = np.asarray(distance, dtype=float)
    colours = np.array(
        [WALKED[0]] + [rgb for _, rgb, _ in BANDS], dtype=float
    ) / 255.0

    out = colours[np.clip(band_index(np.nan_to_num(distance, nan=0.0)), 0, len(colours) - 1)]
    out[np.isnan(distance)] = np.array(outside, dtype=float) / 255.0
    return out


def legend_patches(include_walked=True):
    """matplotlib Patch handles for the bands, in order."""
    from matplotlib.patches import Patch

    entries = ([WALKED] if include_walked else []) + [
        (rgb, label) for _, rgb, label in BANDS
    ]
    return [
        Patch(facecolor=list(rgb01(rgb)), edgecolor="black", label=label)
        for rgb, label in entries
    ]


def png_palette():
    """Flat PIL palette. Index 0 is reserved for transparency, then the bands."""
    palette = [0, 0, 0]
    for _, rgb, _ in BANDS:
        palette += list(rgb)
    return palette + [0] * (768 - len(palette))


def legend_pairs():
    """[[label, "rgb(r,g,b)"], ...] for the HTML legend."""
    return [[label, "rgb(%d,%d,%d)" % rgb] for _, rgb, label in BANDS]
