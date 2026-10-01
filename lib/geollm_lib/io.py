import numpy as np
import rasterio


def read_band(src, index):
    """Read one band (1-based) as float32. NoData pixels become NaN."""
    if not 1 <= index <= src.count:
        raise ValueError(f"Band {index} does not exist. File has {src.count} bands (1..{src.count}).")
    return src.read(index, masked=True).astype("float32").filled(np.nan)


def write_raster(path, arr, src, nodata=None):
    """Save a 2D array as a GeoTIFF with the same location/CRS as `src`."""
    if nodata is None and arr.dtype.kind == "f":
        nodata = np.nan
    with rasterio.open(
        str(path), "w", driver="GTiff",
        height=arr.shape[0], width=arr.shape[1], count=1,
        dtype=str(arr.dtype), crs=src.crs, transform=src.transform,
        nodata=nodata, compress="deflate",
    ) as dst:
        dst.write(arr, 1)