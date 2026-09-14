"""
The imshow extent of a raster, in one place.

matplotlib's `extent` is the OUTER EDGE of the image: the left edge of column
0 and the right edge of the last column, not the coordinates those columns
stand for. Every grid in this project stores a cell by the coordinate at its
CENTER - `lat_min + r * LAT_STEP`, and the point-in-polygon and nearest-walk
tests are all done at that center - so handing those same numbers to imshow
as the extent is half a cell out on each side.

Every raster map here had that bug, each in its own way. The statewide heatmap
passed the CT bounding box, which is not even a whole number of cells wide, so
the picture was stretched by 0.1% and off by up to 67 m at the edges. The
per-town heatmaps passed `lon_min + c * LON_STEP` to `lon_min + (c + 1) * STEP`,
the right width but shifted a uniform half cell north-east. The gerrymander
maps passed the min and max of the data. All of them drew the town outlines and
squadrat tiles, which are in true coordinates, slightly off the colors beneath.

So: one function, used at every imshow, that converts a grid's origin and shape
into the edges matplotlib actually wants.
"""


def cell_extent(lon0, lat0, cols, rows, lon_step, lat_step):
    """imshow extent for a raster whose cell (0, 0) is CENTERED at (lon0, lat0).

    Returns [west, east, south, north] - the outer edges of the image, half a
    cell beyond the first and last cell centers on each axis.

    Pass the grid's own origin and shape, never the data's min and max: a grid
    sized by `round(span / step) + 1` does not in general end exactly at the
    span it was cut from, and the difference lands in the picture.
    """
    return [lon0 - lon_step / 2.0,
            lon0 + (cols - 0.5) * lon_step,
            lat0 - lat_step / 2.0,
            lat0 + (rows - 0.5) * lat_step]
