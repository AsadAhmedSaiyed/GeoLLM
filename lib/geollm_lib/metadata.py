"""Facts about the input files (what the LLM sees instead of pixels)."""
import math
from pathlib import Path
import os
MAX_SAMPLED_BANDS = int(os.environ.get("GEOLLM_MAX_BAND_SAMPLES", "10"))

import rasterio
from rasterio.errors import RasterioIOError

from .bands import detect_sensor, infer_roles, label_role

RASTER_EXT = {".tif", ".tiff"}
VECTOR_EXT = {".geojson", ".json", ".gpkg"}


class GeoTiffError(Exception):
    """Raised when a file is not a usable GeoTIFF."""


def _safe(v):
    return "nan" if isinstance(v, float) and math.isnan(v) else v


def _band_sample(src, i):
    h, w = src.height, src.width
    step = max(1, max(h, w) // 256)
    arr = src.read(i, out_shape=(max(1, h // step), max(1, w // step)), masked=True)
    if arr.count() == 0:
        return {}
    return {"sample_min": float(arr.min()), "sample_max": float(arr.max()),
            "sample_mean": round(float(arr.mean()), 4)}


def inspect_geotiff(path):
    path = Path(path)
    if not path.is_file():
        raise GeoTiffError(f"File not found: {path}")
    if path.suffix.lower() not in RASTER_EXT:
        raise GeoTiffError(f"Unsupported extension '{path.suffix}'")
    try:
        src = rasterio.open(path)
    except RasterioIOError as e:
        raise GeoTiffError(f"Cannot open as raster: {e}") from e
    with src:
        if src.crs is None:
            raise GeoTiffError("File has no CRS; it is not georeferenced.")
        tags = src.tags()
        sensor = detect_sensor(tags)
        labels = list(src.descriptions)
        bands = []
        for i in range(1, src.count + 1):
          entry = {...}
          if i <= MAX_SAMPLED_BANDS:          # only sample first N bands
            entry.update(_band_sample(src, i))
          bands.append(entry)

        metric = src.crs.is_projected and str(src.crs.linear_units).lower() in ("metre", "meter", "m")
        rx, ry = src.res
        return {
            "kind": "raster", "format": "GeoTIFF", "width": src.width, "height": src.height,
            "band_count": src.count, "bands": bands[:MAX_SAMPLED_BANDS] if src.count > MAX_SAMPLED_BANDS else bands,
"bands_truncated": src.count > MAX_SAMPLED_BANDS,
 "band_roles": infer_roles(labels, tags),
            "sensor": sensor, "date": tags.get("ACQUISITION_DATETIME"),
            "crs": src.crs.to_string(), "crs_is_projected": src.crs.is_projected,
            "resolution": [rx, ry], "resolution_units": src.crs.linear_units if src.crs.is_projected else "degrees",
            "extent_km2": round(src.width * src.height * abs(rx * ry) / 1e6, 3) if metric else None,
            "bounds": list(src.bounds), "nodata": _safe(src.nodata), "tags": tags,
        }


def inspect_vector(path):
    import geopandas as gpd
    gdf = gpd.read_file(str(path))
    return {"kind": "vector", "features": int(len(gdf)),
            "geometry_types": {k: int(v) for k, v in gdf.geom_type.value_counts().items()},
            "crs": gdf.crs.to_string() if gdf.crs else None,
            "columns": [c for c in gdf.columns if c != "geometry"],
            "bounds": [float(x) for x in gdf.total_bounds]}


def _alignment(files):
    rasters = {n: f for n, f in files.items() if f.get("kind") == "raster"}
    dates = {n: f.get("date") for n, f in rasters.items()}
    if len(rasters) < 2:
        return {"rasters": len(rasters), "aligned": None, "differences": [], "dates": dates}
    names = list(rasters)
    ref, diffs = rasters[names[0]], []
    for n in names[1:]:
        f = rasters[n]
        if f["crs"] != ref["crs"]:
            diffs.append(f"{n}: CRS {f['crs']} vs {ref['crs']}")
        if f["resolution"] != ref["resolution"]:
            diffs.append(f"{n}: resolution {f['resolution']} vs {ref['resolution']}")
        if (f["width"], f["height"]) != (ref["width"], ref["height"]):
            diffs.append(f"{n}: size {f['width']}x{f['height']} vs {ref['width']}x{ref['height']}")
        if any(abs(a - b) > 1e-6 for a, b in zip(f["bounds"], ref["bounds"])):
            diffs.append(f"{n}: different bounds")
    return {"rasters": len(rasters), "aligned": not diffs, "differences": diffs, "dates": dates}


def inspect_dataset(paths):
    files = {}
    for p in map(Path, paths):
        ext = p.suffix.lower()
        try:
            if ext in RASTER_EXT:
                files[p.name] = inspect_geotiff(p)
            elif ext in VECTOR_EXT:
                files[p.name] = inspect_vector(p)
            else:
                files[p.name] = {"error": f"Unsupported file type '{ext}'"}
        except Exception as e:
            files[p.name] = {"error": str(e)}
    return {"files": files, "alignment": _alignment(files)}