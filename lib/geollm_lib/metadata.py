"""Inspect a GeoTIFF and return structured, JSON-safe metadata."""
import json
import math
import sys
from pathlib import Path

import rasterio
from rasterio.errors import RasterioIOError


class GeoTiffError(Exception):
    """Raised when a file is not a usable GeoTIFF."""


def _json_safe(value):
    """JSON has no NaN. Convert NaN nodata to the string 'nan'."""
    if isinstance(value, float) and math.isnan(value):
        return "nan"
    return value


def inspect_geotiff(path) -> dict:
    path = Path(path)

    if not path.is_file():
        raise GeoTiffError(f"File not found: {path}")
    if path.suffix.lower() not in {".tif", ".tiff"}:
        raise GeoTiffError(f"Unsupported extension '{path.suffix}'. Expected .tif/.tiff")

    try:
        src = rasterio.open(path)
    except RasterioIOError as e:
        raise GeoTiffError(f"Cannot open as raster: {e}") from e

    with src:
        if src.crs is None:
            raise GeoTiffError("File has no CRS; it is not georeferenced.")

        bands = []
        for i in range(1, src.count + 1):          # rasterio bands are 1-indexed
            bands.append({
                "index": i,
                "description": src.descriptions[i - 1],   # often None
                "dtype": src.dtypes[i - 1],
                "nodata": _json_safe(src.nodatavals[i - 1]),
            })

        res_x, res_y = src.res
        return {
            "format": "GeoTIFF",
            "path": str(path),
            "width": src.width,
            "height": src.height,
            "band_count": src.count,
            "bands": bands,
            "crs": src.crs.to_string(),
            "epsg": src.crs.to_epsg(),
            "crs_is_projected": src.crs.is_projected,
            "resolution": [res_x, res_y],
            "resolution_units": src.crs.linear_units if src.crs.is_projected else "degrees",
            "bounds": list(src.bounds),                # left, bottom, right, top
            "transform": list(tuple(src.transform)[:6]),
            "nodata": _json_safe(src.nodata),
            "dtype": src.dtypes[0],
            "tags": src.tags(),
        }


if __name__ == "__main__":
    print(json.dumps(inspect_geotiff(sys.argv[1]), indent=2))