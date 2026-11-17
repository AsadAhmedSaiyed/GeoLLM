"""
Production LiDAR and Canopy Height Modeling Library for GeoLLM.
===============================================================
100% CPU-Vectorized (NumPy, SciPy, Rasterio). Zero GPU required.

Capabilities:
1. calculate_chm: Canopy Height Model (CHM = DSM - DTM) with negative noise filtering.
2. classify_canopy_layers: Multi-tier vegetation height stratification (ground, shrub, understory, canopy).
3. extract_building_candidates: Isolates steep-sided structures from DTM/DSM differences.
4. points_to_dsm_dtm: Fast spatial binning of 3D point clouds (XYZ/CSV/NumPy) into DTM and DSM rasters.
5. read_point_cloud: Universal reader for XYZ/CSV/LAS (with graceful laspy optional import).
6. canopy_metrics_summary: Statistical distribution of tree/structure heights (percentiles, mean, volume).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import rasterio
from rasterio.transform import Affine
from scipy.ndimage import binary_dilation, binary_erosion, uniform_filter


# =====================================================================
# 1. CANOPY HEIGHT MODEL (CHM)
# =====================================================================

def calculate_chm(
    dsm: np.ndarray,
    dtm: np.ndarray,
    min_height_m: float = 0.0,
    max_height_m: float = 120.0,
) -> np.ndarray:
    """
    Computes Canopy Height Model (CHM = Digital Surface Model - Digital Terrain Model).
    Filters negative sensor noise and clips unrealistically tall outliers.
    """
    dsm_arr = np.asarray(dsm, dtype=np.float32)
    dtm_arr = np.asarray(dtm, dtype=np.float32)

    if dsm_arr.shape != dtm_arr.shape:
        raise ValueError(f"DSM shape {dsm_arr.shape} does not match DTM shape {dtm_arr.shape}")

    valid = np.isfinite(dsm_arr) & np.isfinite(dtm_arr)
    chm = np.full_like(dsm_arr, np.nan, dtype=np.float32)

    raw_diff = dsm_arr[valid] - dtm_arr[valid]
    # Physical gating: heights below min_height (e.g. -0.5m pit artifacts) are clamped to 0
    clean_diff = np.clip(raw_diff, min_height_m, max_height_m)
    chm[valid] = clean_diff

    return chm


# =====================================================================
# 2. CANOPY STRATIFICATION & BIOMASS PROXY
# =====================================================================

def classify_canopy_layers(
    chm: np.ndarray,
    shrub_thresh: float = 2.0,
    understory_thresh: float = 5.0,
    canopy_thresh: float = 15.0,
) -> Tuple[np.ndarray, Dict[int, str]]:
    """
    Classifies canopy height into vertical forest strata:
    0: Ground / Bare Surface (< 0.5m)
    1: Low Vegetation / Shrubs (0.5m to shrub_thresh)
    2: Understory / Small Trees (shrub_thresh to understory_thresh)
    3: Mid-Canopy (understory_thresh to canopy_thresh)
    4: Emergent / Tall Forest (> canopy_thresh)
    """
    arr = np.asarray(chm, dtype=np.float32)
    classes = np.zeros_like(arr, dtype=np.uint8)
    valid = np.isfinite(arr)

    classes[valid & (arr >= 0.5) & (arr < shrub_thresh)] = 1
    classes[valid & (arr >= shrub_thresh) & (arr < understory_thresh)] = 2
    classes[valid & (arr >= understory_thresh) & (arr < canopy_thresh)] = 3
    classes[valid & (arr >= canopy_thresh)] = 4

    labels = {
        0: "Ground / Bare Surface (<0.5m)",
        1: f"Low Shrubs (0.5-{shrub_thresh:.1f}m)",
        2: f"Understory ({shrub_thresh:.1f}-{understory_thresh:.1f}m)",
        3: f"Mid-Canopy ({understory_thresh:.1f}-{canopy_thresh:.1f}m)",
        4: f"Tall Canopy (>{canopy_thresh:.1f}m)",
    }
    return classes, labels


def canopy_metrics_summary(chm: np.ndarray, pixel_area_m2: float = 1.0) -> Dict[str, Any]:
    """
    Computes forestry and structural statistics from a Canopy Height Model.
    """
    arr = np.asarray(chm, dtype=np.float32)
    valid = np.isfinite(arr)
    vegetation = valid & (arr >= 1.0)

    total_pixels = int(np.count_nonzero(valid))
    veg_pixels = int(np.count_nonzero(vegetation))
    veg_vals = arr[vegetation]

    if len(veg_vals) == 0:
        return {
            "total_area_m2": total_pixels * pixel_area_m2,
            "canopy_cover_percent": 0.0,
            "mean_height_m": 0.0,
            "max_height_m": 0.0,
            "p50_height_m": 0.0,
            "p95_height_m": 0.0,
            "approx_canopy_volume_m3": 0.0,
        }

    p25, p50, p75, p95 = np.percentile(veg_vals, [25, 50, 75, 95])
    volume_m3 = float(np.sum(veg_vals) * pixel_area_m2)

    return {
        "total_area_m2": round(total_pixels * pixel_area_m2, 2),
        "canopy_area_m2": round(veg_pixels * pixel_area_m2, 2),
        "canopy_cover_percent": round(100.0 * veg_pixels / max(total_pixels, 1), 2),
        "mean_height_m": round(float(np.mean(veg_vals)), 2),
        "max_height_m": round(float(np.max(veg_vals)), 2),
        "p50_median_height_m": round(float(p50), 2),
        "p95_height_m": round(float(p95), 2),
        "std_height_m": round(float(np.std(veg_vals)), 2),
        "approx_canopy_volume_m3": round(volume_m3, 2),
    }


# =====================================================================
# 3. FAST 3D POINT CLOUD BINNING (CPU Binned Interpolation)
# =====================================================================

def points_to_dsm_dtm(
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    cell_size: float = 1.0,
    bounds: Optional[Tuple[float, float, float, float]] = None,
) -> Tuple[np.ndarray, np.ndarray, Affine]:
    """
    Converts raw 3D LiDAR point coordinates (X, Y, Z) into rasterized DTM and DSM grids.
    - DSM = Maximum elevation in each cell (first return / tree tops / roofs)
    - DTM = Minimum elevation in each cell (last return / ground surface)

    100% CPU vectorized using fast 2D spatial binning without needing external libraries.
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    z = np.asarray(z, dtype=np.float32)

    if bounds is None:
        min_x, max_x = float(np.min(x)), float(np.max(x))
        min_y, max_y = float(np.min(y)), float(np.max(y))
    else:
        min_x, min_y, max_x, max_y = bounds

    cols = int(np.ceil((max_x - min_x) / cell_size))
    rows = int(np.ceil((max_y - min_y) / cell_size))

    # Construct affine transform (top-left origin)
    transform = Affine(cell_size, 0.0, min_x, 0.0, -cell_size, max_y)

    col_idx = np.clip(np.floor((x - min_x) / cell_size).astype(np.int64), 0, cols - 1)
    row_idx = np.clip(np.floor((max_y - y) / cell_size).astype(np.int64), 0, rows - 1)
    flat_idx = row_idx * cols + col_idx

    num_cells = rows * cols
    dsm_flat = np.full(num_cells, -np.inf, dtype=np.float32)
    dtm_flat = np.full(num_cells, np.inf, dtype=np.float32)

    # Fast maximum (DSM) and minimum (DTM) per bin
    np.maximum.at(dsm_flat, flat_idx, z)
    np.minimum.at(dtm_flat, flat_idx, z)

    dsm = dsm_flat.reshape((rows, cols))
    dtm = dtm_flat.reshape((rows, cols))

    dsm[np.isneginf(dsm)] = np.nan
    dtm[np.isposinf(dtm)] = np.nan

    return dsm, dtm, transform


def read_point_cloud(
    file_path: Union[str, Path],
    max_points: Optional[int] = 5_000_000,
    bbox: Optional[Tuple[float, float, float, float]] = None,
    chunk_size: int = 500_000,
    classes: Optional[List[int]] = None,
    return_classification: bool = False,
) -> Union[Tuple[np.ndarray, np.ndarray, np.ndarray], Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]:
    """
    Reads LiDAR point clouds from CSV, TXT, XYZ, or LAS/LAZ using memory-bounded streaming chunks.
    - LAS/LAZ: Uses laspy chunk_iterator to stream points without loading entire file into RAM.
    - Spatial Bounding Box: If bbox=(min_x, min_y, max_x, max_y) is specified, only points within the
      box are accumulated.
    - Classification Filter: If classes=[2, 5, 6] is given, filters LAS points by ASPRS classification code.
    - If return_classification=True, returns (x, y, z, classification).
    """
    p = Path(file_path)
    suffix = p.suffix.lower()

    min_x, min_y, max_x, max_y = (
        (bbox[0], bbox[1], bbox[2], bbox[3]) if bbox is not None else (-np.inf, -np.inf, np.inf, np.inf)
    )

    if suffix in (".las", ".laz"):
        try:
            import laspy
            x_chunks, y_chunks, z_chunks, c_chunks = [], [], [], []
            total_loaded = 0

            with laspy.open(p) as fh:
                points_to_fetch = min(chunk_size, max_points or chunk_size)
                for chunk in fh.chunk_iterator(points_to_fetch):
                    cx = np.asarray(chunk.x, dtype=np.float64)
                    cy = np.asarray(chunk.y, dtype=np.float64)
                    cz = np.asarray(chunk.z, dtype=np.float32)
                    cc = (
                        np.asarray(chunk.classification, dtype=np.uint8)
                        if hasattr(chunk, "classification")
                        else np.zeros(len(cx), dtype=np.uint8)
                    )

                    mask = None
                    if bbox is not None:
                        mask = (cx >= min_x) & (cx <= max_x) & (cy >= min_y) & (cy <= max_y)
                    if classes is not None:
                        cls_mask = np.isin(cc, classes)
                        mask = cls_mask if mask is None else (mask & cls_mask)
                    if mask is not None:
                        if not np.any(mask):
                            continue
                        cx, cy, cz, cc = cx[mask], cy[mask], cz[mask], cc[mask]

                    needed = max_points - total_loaded if max_points is not None else len(cx)
                    if needed <= 0:
                        break

                    if len(cx) > needed:
                        cx, cy, cz, cc = cx[:needed], cy[:needed], cz[:needed], cc[:needed]

                    x_chunks.append(cx)
                    y_chunks.append(cy)
                    z_chunks.append(cz)
                    c_chunks.append(cc)
                    total_loaded += len(cx)

                    if max_points is not None and total_loaded >= max_points:
                        break

            if not x_chunks:
                empty_x = np.empty(0, dtype=np.float64)
                empty_y = np.empty(0, dtype=np.float64)
                empty_z = np.empty(0, dtype=np.float32)
                if return_classification:
                    return empty_x, empty_y, empty_z, np.empty(0, dtype=np.uint8)
                return empty_x, empty_y, empty_z

            out_x = np.concatenate(x_chunks)
            out_y = np.concatenate(y_chunks)
            out_z = np.concatenate(z_chunks)
            if return_classification:
                return out_x, out_y, out_z, np.concatenate(c_chunks)
            return out_x, out_y, out_z

        except ImportError:
            raise ImportError(
                "Reading binary .las/.laz files requires 'laspy'. "
                "Install via 'pip install laspy[lazrs]' or provide point clouds as XYZ/CSV or GeoTIFF DTM/DSM."
            )

    # Standard ASCII/CSV point clouds via memory-safe chunked reading
    import pandas as pd
    delimiter = "," if suffix == ".csv" else r"\s+"
    x_chunks, y_chunks, z_chunks = [], [], []
    total_loaded = 0

    reader = pd.read_csv(
        p,
        sep=delimiter,
        header=None,
        usecols=[0, 1, 2],
        names=["x", "y", "z"],
        dtype={"x": np.float64, "y": np.float64, "z": np.float32},
        chunksize=chunk_size,
    )

    for chunk_df in reader:
        cx = chunk_df["x"].values
        cy = chunk_df["y"].values
        cz = chunk_df["z"].values

        if bbox is not None:
            mask = (cx >= min_x) & (cx <= max_x) & (cy >= min_y) & (cy <= max_y)
            if not np.any(mask):
                continue
            cx, cy, cz = cx[mask], cy[mask], cz[mask]

        needed = max_points - total_loaded if max_points is not None else len(cx)
        if needed <= 0:
            break

        if len(cx) > needed:
            cx, cy, cz = cx[:needed], cy[:needed], cz[:needed]

        x_chunks.append(cx)
        y_chunks.append(cy)
        z_chunks.append(cz)
        total_loaded += len(cx)

        if max_points is not None and total_loaded >= max_points:
            break

    if not x_chunks:
        empty_x = np.empty(0, dtype=np.float64)
        empty_y = np.empty(0, dtype=np.float64)
        empty_z = np.empty(0, dtype=np.float32)
        if return_classification:
            return empty_x, empty_y, empty_z, np.empty(0, dtype=np.uint8)
        return empty_x, empty_y, empty_z

    out_x = np.concatenate(x_chunks)
    out_y = np.concatenate(y_chunks)
    out_z = np.concatenate(z_chunks)
    if return_classification:
        return out_x, out_y, out_z, np.zeros(len(out_x), dtype=np.uint8)
    return out_x, out_y, out_z


# =====================================================================
# 6. LIDAR 3D WEBGL MESH GENERATOR
# =====================================================================

def generate_lidar_3d_payload(
    raster_path: Union[str, Path],
    dtm_path: Optional[Union[str, Path]] = None,
    out_json_path: Optional[Union[str, Path]] = None,
    max_dim: int = 512,
) -> Dict[str, Any]:
    """
    Generates a high-detail 3D LiDAR payload with normalized height above ground (CHM).
    Applies structure-aware smoothing: gentle Gaussian for vegetation crowns, maximum-filter
    levelling for building rooftops, and median-filter spike removal for all surfaces.
    Outputs compact JSON for 60 FPS WebGL rendering in Three.js.

    max_dim controls the mesh vertex grid resolution. Default 512 gives ~260K vertices,
    enough to resolve individual tree crowns (~5m) and building roof edges at 2m LiDAR.
    """
    from rasterio.enums import Resampling
    from geollm_lib.terrain import multi_directional_hillshade, resolve_cell_size
    from scipy.ndimage import gaussian_filter, maximum_filter, median_filter

    p = Path(raster_path)
    is_chm = any(k in p.name.lower() for k in ("chm", "canopy", "above_ground", "tree_height", "height"))

    with rasterio.open(p) as src:
        scale_x = max_dim / float(src.width)
        scale_y = max_dim / float(src.height)
        # Never upsample: interpolating a coarse raster only invents fake slopes.
        scale = min(scale_x, scale_y, 1.0)
        out_w = max(int(src.width * scale), 16)
        out_h = max(int(src.height * scale), 16)
        src_w, src_h = src.width, src.height

        data = src.read(
            1,
            out_shape=(out_h, out_w),
            resampling=Resampling.bilinear,
        ).astype(np.float32)

        src_nodata = src.nodata
        bounds = [float(src.bounds.left), float(src.bounds.bottom), float(src.bounds.right), float(src.bounds.top)]
        dx_m, dy_m = resolve_cell_size(src.transform, src.crs, src.bounds)
        # Cell size of the *output* grid (source cell size scaled by the resample factor)
        dx_m = float(dx_m) * (src_w / float(out_w))
        dy_m = float(dy_m) * (src_h / float(out_h))
        crs_str = str(src.crs or "EPSG:4326")

    # If DTM is provided or raster is a DSM with a paired DTM, subtract to create CHM
    if not is_chm and dtm_path and Path(dtm_path).exists():
        with rasterio.open(dtm_path) as dtm_src:
            dtm_data = dtm_src.read(
                1,
                out_shape=(out_h, out_w),
                resampling=Resampling.bilinear,
            ).astype(np.float32)
            valid_dtm = np.isfinite(dtm_data)
            if dtm_src.nodata is not None:
                valid_dtm &= (dtm_data != dtm_src.nodata)
            valid_dtm &= (dtm_data > -100.0)

            valid_dsm = np.isfinite(data)
            if src_nodata is not None:
                valid_dsm &= (data != src_nodata)
            valid_dsm &= (data > -100.0)

            mask = valid_dtm & valid_dsm
            chm_data = np.zeros_like(data)
            chm_data[mask] = np.clip(data[mask] - dtm_data[mask], 0.0, None)
            data = chm_data
            is_chm = True

    # Robust nodata and sentinel filtering:
    valid = np.isfinite(data)
    if src_nodata is not None:
        valid &= (data != src_nodata)
    # Strictly reject negative sentinels (e.g. -9999, -32768)
    valid &= (data > -100.0)

    if is_chm:
        # In a Canopy Height Model, height above ground is strictly >= 0
        valid &= (data >= 0.0) & (data < 500.0)
        min_z = 0.0
        max_z = float(np.max(data[valid])) if np.any(valid) else 1.0
        # Infill empty/nodata boundaries with ground level (0.0) to prevent stalactites
        data_clean = np.where(valid, np.clip(data, 0.0, None), 0.0)
    else:
        min_z = float(np.min(data[valid])) if np.any(valid) else 0.0
        max_z = float(np.max(data[valid])) if np.any(valid) else 1.0
        data_clean = np.where(valid, data, min_z)

    # ---------------------------------------------------------------
    # Structure-aware surface refinement
    # Removes LiDAR spike noise and sharpens real structures.
    # ---------------------------------------------------------------

    # Spike removal only: a 3x3 median filter removes isolated noise returns
    # (power lines, birds, edge noise) while keeping building walls and
    # individual tree crowns intact. Feature-specific shaping (flat roofs,
    # rounded crowns, water) is done by the 3D viewer after classification,
    # so we deliberately do NOT max-filter or blur here — those filters merged
    # neighbouring trees into flat-topped plateaus that looked like mountains.
    data_clean = median_filter(data_clean, size=3).astype(np.float32)

    # Clamp back to valid range after filtering
    data_clean = np.clip(data_clean, min_z, max_z)

    # Recompute true range after refinement
    min_z = float(data_clean.min())
    max_z = float(data_clean.max())

    # Compute multi-directional hillshade on the refined surface for 3D depth cues
    hs = multi_directional_hillshade(data_clean, dx_m, dy_m)

    payload = {
        "version": "2.0",
        "type": "lidar_mesh_3d",
        "is_lidar": True,
        "default_surface": "lidar_canopy",
        "source": p.name,
        "width": out_w,
        "height": out_h,
        "bounds": bounds,
        "min_elevation_m": round(min_z, 2),
        "max_elevation_m": round(max_z, 2),
        "elevation_range_m": round(max_z - min_z, 2),
        "cell_size_m": [round(dx_m, 2), round(dy_m, 2)],
        "crs": crs_str,
        "elevations": [round(float(v), 2) for v in data_clean.flatten()],
        "hillshade": [int(v) for v in hs.flatten()],
    }

    if out_json_path:
        Path(out_json_path).write_text(json.dumps(payload), encoding="utf-8")
    return payload

