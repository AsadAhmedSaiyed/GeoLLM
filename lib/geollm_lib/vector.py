"""Vector operations: mask -> polygons, boundaries -> masks, zonal statistics."""
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
from rasterio import features
from shapely.geometry import shape

from .masks import filter_small


def _metric(src):
    return src.crs is not None and src.crs.is_projected and str(src.crs.linear_units).lower() in ("metre", "meter", "m")


def mask_to_geojson(mask, src, path, min_pixels=1, max_features=50000):
    """Polygonize a boolean mask and save as GeoJSON (WGS84). Returns the number of polygons."""
    m = np.asarray(mask, bool)
    if min_pixels > 1:
        m = filter_small(m, min_pixels)
    geoms = [shape(g) for g, v in features.shapes(m.astype("uint8"), mask=m, transform=src.transform) if v == 1]
    if len(geoms) > max_features:
        raise ValueError(f"{len(geoms)} polygons is too many; raise min_pixels to drop tiny patches.")
    if not geoms:
        Path(path).write_text(json.dumps({"type": "FeatureCollection", "features": []}))
        return 0
    gdf = gpd.GeoDataFrame({"id": range(1, len(geoms) + 1)}, geometry=geoms, crs=src.crs)
    if _metric(src):
        gdf["area_ha"] = (gdf.geometry.area / 10000).round(3)
    gdf.to_crs(4326).to_file(str(path), driver="GeoJSON")
    return len(geoms)


def read_vector(path):
    return gpd.read_file(str(path))


def rasterize_vector(gdf, src):
    """Boolean mask (on the raster grid) of everything inside the vector shapes."""
    if gdf.crs is None:
        raise ValueError("The vector file has no CRS.")
    g = gdf.to_crs(src.crs)
    return features.geometry_mask(g.geometry, out_shape=(src.height, src.width),
                                  transform=src.transform, invert=True)


def zonal_stats(arr, zones, src, max_zones=500):
    """Mean/min/max/count of `arr` inside each polygon of `zones`."""
    if zones.crs is None:
        raise ValueError("The vector file has no CRS.")
    if len(zones) > max_zones:
        raise ValueError(f"{len(zones)} zones is too many (limit {max_zones}).")
    out = []
    for i, geom in enumerate(zones.to_crs(src.crs).geometry):
        inside = features.geometry_mask([geom], out_shape=arr.shape, transform=src.transform, invert=True)
        vals = arr[inside & np.isfinite(arr)]
        out.append({"zone": i, "count": int(vals.size),
                    "mean": float(vals.mean()) if vals.size else None,
                    "min": float(vals.min()) if vals.size else None,
                    "max": float(vals.max()) if vals.size else None})
    return out