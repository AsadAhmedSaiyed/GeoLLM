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

def _metric_gdf(gdf):
    return gdf.crs is not None and gdf.crs.is_projected and str(gdf.crs.axis_info[0].unit_name).lower() in ("metre", "meter")


def write_geojson(gdf, path):
    """Save a GeoDataFrame as GeoJSON (WGS84)."""
    gdf.to_crs(4326).to_file(str(path), driver="GeoJSON")


def buffer_vector(gdf, distance_m):
    """Buffer geometries by distance_m metres. The vector must be in a metric CRS (reproject first)."""
    if not _metric_gdf(gdf):
        raise ValueError("buffer_vector needs a metric CRS. Use gdf.to_crs(<projected CRS>) first.")
    out = gdf.copy()
    out["geometry"] = gdf.geometry.buffer(distance_m)
    return out


def intersect_vectors(a, b):
    """Geometric intersection of two GeoDataFrames (b is reprojected to a's CRS)."""
    return gpd.overlay(a, b.to_crs(a.crs), how="intersection")


def union_vectors(a, b):
    """Geometric union of two GeoDataFrames."""
    return gpd.overlay(a, b.to_crs(a.crs), how="union")


def clip_vector(gdf, clip_gdf):
    """Clip gdf to the extent of clip_gdf."""
    return gpd.clip(gdf, clip_gdf.to_crs(gdf.crs))


def spatial_join(left, right, how="inner", predicate="intersects"):
    """Attach attributes of `right` to `left` by spatial relation."""
    return gpd.sjoin(left, right.to_crs(left.crs), how=how, predicate=predicate)


def filter_features(gdf, column, values):
    """Keep rows where `column` is in `values`."""
    if column not in gdf.columns:
        raise ValueError(f"No column '{column}'. Columns: {list(gdf.columns)}")
    return gdf[gdf[column].isin(values)]


def area_hectares(gdf):
    """Total area of the geometries in hectares. Needs a metric CRS."""
    if not _metric_gdf(gdf):
        raise ValueError("area_hectares needs a metric CRS. Reproject first.")
    return float(gdf.geometry.area.sum() / 10000)