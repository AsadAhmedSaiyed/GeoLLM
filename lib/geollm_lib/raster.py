"""
Out-of-Core Big-Data Raster Engine for GeoLLM.
==============================================
Provides chunked, memory-bounded raster processing using Dask, Xarray, and Rasterio.
Enables processing multi-gigabyte rasters without exceeding RAM limits.

Capabilities:
1. is_chunked: Detects whether an array or DataArray is Dask-backed.
2. open_raster_chunks: Opens GeoTIFF lazily as an xarray.DataArray backed by Dask chunks.
3. save_raster_chunks: Writes Dask-backed or xarray DataArray to GeoTIFF block-by-block.
4. stream_window_blocks: Ultra-safe blockwise processor with bounded RAM footprint.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import numpy as np
import rasterio
from rasterio.windows import Window


def is_chunked(data: Any) -> bool:
    """Returns True if the object is a Dask array or a Dask-backed xarray DataArray."""
    try:
        import dask.array as da
        if isinstance(data, da.Array):
            return True
    except ImportError:
        pass

    try:
        import xarray as xr
        if isinstance(data, (xr.DataArray, xr.Dataset)):
            return getattr(data, "chunks", None) is not None
    except ImportError:
        pass

    return False


def open_raster_chunks(
    file_path: Union[str, Path],
    chunk_size: Tuple[int, int] = (1024, 1024),
    band: Optional[int] = None,
    masked: bool = True,
) -> Any:
    """
    Opens a GeoTIFF lazily as an xarray.DataArray backed by Dask chunks.
    Reads metadata immediately but defers raster loading until computation.

    Args:
        file_path: Path to the GeoTIFF raster.
        chunk_size: (height, width) tuple of chunk pixel dimensions (default 1024x1024).
        band: 1-based band index to select, or None to load all bands.
        masked: If True, automatically masks NoData values and converts to float32 NaN.

    Returns:
        xarray.DataArray backed by Dask.
    """
    import rioxarray
    import xarray as xr

    p = Path(file_path)
    if not p.is_file():
        raise FileNotFoundError(f"Raster file not found: {p}")

    chunks = {"y": chunk_size[0], "x": chunk_size[1]}
    da = rioxarray.open_rasterio(p, chunks=chunks, masked=masked)

    if masked:
        da = da.astype("float32")

    if band is not None:
        if 1 <= band <= da.sizes.get("band", 1):
            da = da.sel(band=band)
        else:
            raise ValueError(f"Requested band {band} is out of range for raster with {da.sizes.get('band')} bands")

    return da


def save_raster_chunks(
    data: Any,
    out_path: Union[str, Path],
    chunk_size: Tuple[int, int] = (512, 512),
    nodata: Optional[float] = np.nan,
    compress: str = "deflate",
    tiled: bool = True,
) -> Path:
    """
    Writes a Dask array or xarray.DataArray to a GeoTIFF file block-by-block.
    Guarantees that memory consumption never exceeds a single block chunk.

    Args:
        data: xarray.DataArray or Dask array or NumPy ndarray.
        out_path: Output GeoTIFF destination path.
        chunk_size: Block size for raster tiling.
        nodata: Value to use for nodata cells.
        compress: Compression algorithm ('deflate', 'lzw', etc.).
        tiled: Whether to write as tiled GeoTIFF (recommended True).

    Returns:
        Path to the saved GeoTIFF.
    """
    import xarray as xr
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(data, xr.DataArray):
        # Use rioxarray to write tiled raster directly to disk
        encoding: Dict[str, Any] = {
            "compress": compress,
            "tiled": tiled,
            "blockxsize": chunk_size[1] if tiled else None,
            "blockysize": chunk_size[0] if tiled else None,
        }
        if nodata is not None:
            encoding["_FillValue"] = nodata

        # Clean encoding dict
        encoding = {k: v for k, v in encoding.items() if v is not None}
        data.rio.to_raster(out, windowed=True, **encoding)
        return out

    # If it is a Dask array or NumPy array without xarray metadata, fallback to rasterio windowed writer
    arr = data
    if hasattr(arr, "compute"):
        # Dask array
        import dask.array as da
        h, w = arr.shape[-2], arr.shape[-1]
        bands = 1 if arr.ndim == 2 else arr.shape[0]

        profile = {
            "driver": "GTiff",
            "height": h,
            "width": w,
            "count": bands,
            "dtype": str(arr.dtype),
            "nodata": nodata,
            "compress": compress,
            "tiled": tiled,
            "blockxsize": min(chunk_size[1], w),
            "blockysize": min(chunk_size[0], h),
        }

        with rasterio.open(out, "w", **profile) as dst:
            bx, by = profile["blockxsize"], profile["blockysize"]
            for y0 in range(0, h, by):
                ny = min(by, h - y0)
                for x0 in range(0, w, bx):
                    nx = min(bx, w - x0)
                    win = Window(x0, y0, nx, ny)
                    if bands == 1:
                        block = arr[y0 : y0 + ny, x0 : x0 + nx].compute()
                        dst.write(block, 1, window=win)
                    else:
                        block = arr[:, y0 : y0 + ny, x0 : x0 + nx].compute()
                        dst.write(block, window=win)
        return out

    # Standard numpy array
    arr = np.asarray(data)
    h, w = arr.shape[-2], arr.shape[-1]
    bands = 1 if arr.ndim == 2 else arr.shape[0]
    profile = {
        "driver": "GTiff",
        "height": h,
        "width": w,
        "count": bands,
        "dtype": str(arr.dtype),
        "nodata": nodata,
        "compress": compress,
        "tiled": tiled,
        "blockxsize": min(chunk_size[1], w),
        "blockysize": min(chunk_size[0], h),
    }
    with rasterio.open(out, "w", **profile) as dst:
        if bands == 1:
            dst.write(arr.squeeze(), 1)
        else:
            dst.write(arr)
    return out


def stream_window_blocks(
    src_path: Union[str, Path],
    dst_path: Union[str, Path],
    process_fn: Callable[[np.ndarray], np.ndarray],
    block_size: int = 1024,
    out_dtype: Optional[str] = "float32",
    nodata: Optional[float] = np.nan,
    compress: str = "deflate",
) -> Path:
    """
    Streams a giant raster file through a pixel-wise or windowed processing function.
    Memory consumption is strictly bounded to `O(block_size^2)`.

    Args:
        src_path: Input GeoTIFF path.
        dst_path: Output GeoTIFF path.
        process_fn: Function taking a (bands, H, W) or (H, W) NumPy array and returning processed array.
        block_size: Width/Height of square processing tile.
        out_dtype: Data type of output raster.
        nodata: Output nodata fill value.
        compress: GeoTIFF compression algorithm.

    Returns:
        Path to output raster.
    """
    src_p = Path(src_path)
    dst_p = Path(dst_path)
    dst_p.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(src_p) as src:
        profile = src.profile.copy()
        h, w = src.height, src.width

        # Test process_fn on a 1x1 test window to inspect output shape & dtype
        test_win = Window(0, 0, min(16, w), min(16, h))
        sample_in = src.read(window=test_win, masked=True).astype("float32").filled(np.nan)
        sample_out = np.asarray(process_fn(sample_in))
        out_bands = 1 if sample_out.ndim == 2 else sample_out.shape[0]
        actual_dtype = out_dtype or str(sample_out.dtype)

        profile.update({
            "driver": "GTiff",
            "height": h,
            "width": w,
            "count": out_bands,
            "dtype": actual_dtype,
            "nodata": nodata,
            "compress": compress,
            "tiled": True,
            "blockxsize": min(256, w),
            "blockysize": min(256, h),
        })

        with rasterio.open(dst_p, "w", **profile) as dst:
            for y0 in range(0, h, block_size):
                ny = min(block_size, h - y0)
                for x0 in range(0, w, block_size):
                    nx = min(block_size, w - x0)
                    win = Window(x0, y0, nx, ny)
                    in_block = src.read(window=win, masked=True).astype("float32").filled(np.nan)
                    out_block = process_fn(in_block)
                    out_block = np.asarray(out_block, dtype=actual_dtype)

                    if out_bands == 1 and out_block.ndim == 2:
                        dst.write(out_block, 1, window=win)
                    elif out_bands == 1 and out_block.ndim == 3 and out_block.shape[0] == 1:
                        dst.write(out_block[0], 1, window=win)
                    else:
                        dst.write(out_block, window=win)

    return dst_p
