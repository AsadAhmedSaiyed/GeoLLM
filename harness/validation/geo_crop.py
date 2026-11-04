"""Geospatial window extraction, CRS reprojection, and multi-panel side-by-side rendering.

Extracts identical geographic bounding windows across input satellite GeoTIFFs,
sub-agent output GeoTIFFs, and PNG maps for side-by-side visual validation.
"""
from __future__ import annotations

import base64
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from rasterio.windows import Window, from_bounds
import pyproj
from PIL import Image

from .config import ValidationConfig, get_validation_config


@dataclass(frozen=True)
class ExtractedCrop:
    """Extracted full-resolution raster crop with spatial metadata."""
    source_path: str
    array: np.ndarray  # Shape: (Bands, H, W) or (H, W)
    crs: str
    bounds_geo: Tuple[float, float, float, float]  # minx, miny, maxx, maxy
    window: Tuple[int, int, int, int]  # col_off, row_off, width, height
    nodata: Optional[float]
    is_mask: bool
    is_continuous: bool


def _transform_bounds(
    bounds: Tuple[float, float, float, float],
    src_crs_str: str,
    dst_crs_str: str,
) -> Tuple[float, float, float, float]:
    """Reprojects bounding box coordinates between coordinate reference systems."""
    if src_crs_str.lower() == dst_crs_str.lower():
        return bounds
    transformer = pyproj.Transformer.from_crs(src_crs_str, dst_crs_str, always_xy=True)
    minx, miny, maxx, maxy = bounds
    # Transform all 4 bounding corners to properly envelop reprojection curvature
    xs = [minx, maxx, minx, maxx]
    ys = [miny, miny, maxy, maxy]
    tx, ty = transformer.transform(xs, ys)
    return (min(tx), min(ty), max(tx), max(ty))


def extract_raster_crop(
    raster_path: Union[str, Path],
    bbox_geo: Optional[Tuple[float, float, float, float]] = None,
    bbox_norm: Optional[Tuple[float, float, float, float]] = None,
    bbox_crs: Optional[str] = None,
    target_bands: Optional[Sequence[int]] = None,
    cfg: Optional[ValidationConfig] = None,
) -> ExtractedCrop:
    """Extracts a full-resolution spatial crop from a GeoTIFF using windowed I/O.

    Args:
        raster_path: Path to target GeoTIFF file.
        bbox_geo: Geographic bounding box (minx, miny, maxx, maxy).
        bbox_norm: Normalized image coordinates (ymin, xmin, ymax, xmax) between 0.0 and 1.0.
        bbox_crs: Coordinate system of bbox_geo (defaults to raster's native CRS).
        target_bands: Optional 1-based band numbers to read (reads all or top 3 if None).
        cfg: Optional validation configuration.

    Returns:
        ExtractedCrop dataclass containing the pixel array and georeferencing info.
    """
    config = cfg or get_validation_config()
    p = Path(raster_path)
    if not p.is_file():
        raise FileNotFoundError(f"Raster file not found: {p}")

    with rasterio.open(p) as src:
        crs_str = src.crs.to_string() if src.crs else "EPSG:4326"

        if bbox_norm is not None:
            # Normalized box: (ymin, xmin, ymax, xmax)
            ymin, xmin, ymax, xmax = bbox_norm
            col_off = int(np.clip(xmin * src.width, 0, src.width - 1))
            row_off = int(np.clip(ymin * src.height, 0, src.height - 1))
            w = max(1, int(np.clip((xmax - xmin) * src.width, 1, src.width - col_off)))
            h = max(1, int(np.clip((ymax - ymin) * src.height, 1, src.height - row_off)))
            win = Window(col_off=col_off, row_off=row_off, width=w, height=h)
        elif bbox_geo is not None:
            # Geographic bounds: reproject to native CRS if needed
            target_bbox = bbox_geo
            if bbox_crs and src.crs and bbox_crs.lower() != crs_str.lower():
                target_bbox = _transform_bounds(bbox_geo, bbox_crs, crs_str)
            win = from_bounds(*target_bbox, transform=src.transform)
            # Clip window to raster extent
            col_off = int(np.clip(win.col_off, 0, src.width - 1))
            row_off = int(np.clip(win.row_off, 0, src.height - 1))
            w = max(1, int(np.clip(win.width, 1, src.width - col_off)))
            h = max(1, int(np.clip(win.height, 1, src.height - row_off)))
            win = Window(col_off=col_off, row_off=row_off, width=w, height=h)
        else:
            # Default to full extent
            win = Window(col_off=0, row_off=0, width=src.width, height=src.height)

        # Select bands to read
        if target_bands:
            bands_to_read = [b for b in target_bands if 1 <= b <= src.count]
        else:
            bands_to_read = list(range(1, min(src.count + 1, 4)))

        # Read window with nodata masking
        arr = src.read(bands_to_read, window=win, masked=True)
        crop_bounds = rasterio.windows.bounds(win, transform=src.transform)

        # Determine semantic raster properties
        first_band = arr[0] if arr.ndim == 3 else arr
        valid_vals = first_band.compressed() if hasattr(first_band, "compressed") else first_band.ravel()
        uniq = np.unique(valid_vals[:5000]) if len(valid_vals) > 0 else np.array([])

        is_mask = bool(len(uniq) <= 3 and set(uniq).issubset({0, 1, 255}))
        is_continuous = bool(not is_mask and arr.dtype.kind == "f")

        return ExtractedCrop(
            source_path=str(p),
            array=arr,
            crs=crs_str,
            bounds_geo=(crop_bounds[0], crop_bounds[1], crop_bounds[2], crop_bounds[3]),
            window=(int(win.col_off), int(win.row_off), int(win.width), int(win.height)),
            nodata=src.nodata,
            is_mask=is_mask,
            is_continuous=is_continuous,
        )


def render_crop_to_rgb(crop: ExtractedCrop) -> np.ndarray:
    """Renders an ExtractedCrop array into an 8-bit RGB image (H, W, 3)."""
    arr = crop.array
    if arr.ndim == 2:
        arr = arr[np.newaxis, ...]

    # Convert to float32 first to safely allow np.nan fill values across all dtypes
    if hasattr(arr, "filled"):
        data = arr.astype("float32").filled(np.nan)
    else:
        data = arr.astype("float32")

    if crop.is_mask:
        # Binary mask: background gray, mask translucent red/blue
        mask_2d = np.nan_to_num(data[0], nan=0.0) > 0
        h, w = mask_2d.shape
        rgb = np.full((h, w, 3), 220, dtype=np.uint8)  # Light gray background
        rgb[mask_2d] = [220, 38, 38]  # Vivid Red for selected pixels
        return rgb

    if data.shape[0] >= 3:
        # Multi-band optical: Red, Green, Blue
        rgb = np.zeros((data.shape[1], data.shape[2], 3), dtype=np.float32)
        for i in range(3):
            b = data[i]
            finite = b[np.isfinite(b)]
            if len(finite) > 0:
                p2, p98 = np.percentile(finite, [2, 98])
                denom = max(1e-5, p98 - p2)
                rgb[..., i] = np.clip((b - p2) / denom, 0, 1)
        # Apply black background for nodata
        nan_mask = ~np.isfinite(data[:3]).all(axis=0)
        rgb[nan_mask] = 0.0
        return (rgb * 255).astype(np.uint8)

    # Single-band continuous (e.g. NDVI, NDWI, DEM)
    band_2d = data[0]
    finite = band_2d[np.isfinite(band_2d)]
    if len(finite) == 0:
        return np.full((band_2d.shape[0], band_2d.shape[1], 3), 128, dtype=np.uint8)

    p2, p98 = np.percentile(finite, [2, 98])
    denom = max(1e-5, p98 - p2)
    normalized = np.clip((band_2d - p2) / denom, 0.0, 1.0)
    cmap = plt.get_cmap("viridis" if not crop.is_continuous else "RdYlGn")
    rgba = cmap(normalized)
    rgb = (rgba[..., :3] * 255).astype(np.uint8)

    # Black for nodata pixels
    rgb[~np.isfinite(band_2d)] = 20
    return rgb


def extract_png_crop(
    png_path: Union[str, Path],
    bbox_norm: Tuple[float, float, float, float],
) -> Optional[np.ndarray]:
    """Crops a matplotlib PNG map using normalized bounding coordinates."""
    p = Path(png_path)
    if not p.is_file():
        return None
    try:
        with Image.open(p) as img:
            img_rgb = img.convert("RGB")
            w, h = img_rgb.size
            ymin, xmin, ymax, xmax = bbox_norm
            left = int(np.clip(xmin * w, 0, w - 1))
            upper = int(np.clip(ymin * h, 0, h - 1))
            right = max(left + 1, int(np.clip(xmax * w, 1, w)))
            lower = max(upper + 1, int(np.clip(ymax * h, 1, h)))
            cropped = img_rgb.crop((left, upper, right, lower))
            return np.array(cropped)
    except Exception:
        return None


def generate_side_by_side_comparison(
    input_raster_path: Union[str, Path],
    output_raster_path: Optional[Union[str, Path]] = None,
    png_map_path: Optional[Union[str, Path]] = None,
    bbox_geo: Optional[Tuple[float, float, float, float]] = None,
    bbox_norm: Optional[Tuple[float, float, float, float]] = None,
    out_path: Optional[Union[str, Path]] = None,
    cfg: Optional[ValidationConfig] = None,
) -> Path:
    """Generates a side-by-side multi-panel comparison image for visual inspection.

    Panels:
    1. Input Satellite Source Crop (Raw Optical / SAR)
    2. Output GeoTIFF Re-rendered Crop (Ground-Truth Cartography)
    3. Output PNG Map Crop (Sub-Agent Rendered Figure, if available)
    4. Difference / Discrepancy View

    Returns:
        Path to the saved PNG comparison image.
    """
    config = cfg or get_validation_config()

    # 1. Extract input satellite crop
    input_crop = extract_raster_crop(input_raster_path, bbox_geo=bbox_geo, bbox_norm=bbox_norm, cfg=config)
    input_rgb = render_crop_to_rgb(input_crop)

    panels: List[Tuple[str, np.ndarray]] = [("Source Satellite Crop", input_rgb)]

    # 2. Extract and re-render output GeoTIFF crop using shared geographic bounds
    out_crop = None
    if output_raster_path and Path(output_raster_path).is_file():
        try:
            out_crop = extract_raster_crop(
                output_raster_path,
                bbox_geo=input_crop.bounds_geo,
                bbox_crs=input_crop.crs,
                cfg=config,
            )
            out_rgb = render_crop_to_rgb(out_crop)
            panels.append(("Output GeoTIFF (Re-rendered)", out_rgb))
        except Exception:
            pass

    # 3. Extract sub-agent PNG map crop if present
    if png_map_path and bbox_norm is not None:
        png_crop = extract_png_crop(png_map_path, bbox_norm)
        if png_crop is not None:
            panels.append(("Sub-Agent PNG Map Crop", png_crop))

    # 4. Generate Difference Overlay if both input and output crops are available
    if out_crop is not None:
        try:
            # Rescale out_rgb to match input_rgb dimensions for overlay
            h, w = input_rgb.shape[:2]
            out_resized = np.array(Image.fromarray(render_crop_to_rgb(out_crop)).resize((w, h), Image.Resampling.NEAREST))
            diff = np.clip(np.abs(input_rgb.astype(int) - out_resized.astype(int)), 0, 255).astype(np.uint8)
            panels.append(("Discrepancy / Overlay", diff))
        except Exception:
            pass

    # Build Matplotlib multi-panel figure
    n_panels = len(panels)
    fig, axes = plt.subplots(1, n_panels, figsize=(4.5 * n_panels, 4.5), dpi=150)
    if n_panels == 1:
        axes = [axes]

    for ax, (title, img_arr) in zip(axes, panels):
        ax.imshow(img_arr)
        ax.set_title(title, fontsize=10, fontweight="bold", pad=6)
        ax.axis("off")

    fig.tight_layout()

    # Save to disk
    if out_path:
        save_dest = Path(out_path)
    else:
        save_dest = Path("runs") / "validation_crops" / f"comparison_{int(input_crop.bounds_geo[0])}.png"
    save_dest.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(save_dest), bbox_inches="tight")
    plt.close(fig)

    return save_dest
