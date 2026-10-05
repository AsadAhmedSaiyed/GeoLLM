"""Raster I/O and semantic band lookup."""
import json
import os
from typing import Any

import numpy as np
import rasterio

from .bands import BandError, ROLES, detect_sensor, infer_roles, label_role


def read_band(src: Any, index: int) -> np.ndarray:
    """Read one raster band.

    Args:
        src: An open rasterio dataset object. This is NOT a file path.
        index: 1-based integer band number.

    Returns:
        A float32 NumPy array. Raster NoData values are converted to NaN.
    """
    if not 1 <= index <= src.count:
        raise BandError(f"Band {index} does not exist. File has {src.count} bands (1..{src.count}).")
    return src.read(index, masked=True).astype("float32").filled(np.nan)


def check_explicit(src, role, idx):
    """Check that a user-specified band number is valid and not labelled as a different role.

    Raises BandError if the band does not exist or its label contradicts `role`.
    """
    if not 1 <= idx <= src.count:
        raise BandError(f"Band {idx} for '{role}' does not exist. File has {src.count} bands.")
    label = src.descriptions[idx - 1]
    other = label_role(label, detect_sensor(src.tags()))
    if other and other != role:
        raise BandError(f"Band {idx} is labelled '{label}' ({other}), not '{role}'. "
                        f"Do not substitute bands; report that '{role}' is unavailable.")


def band_for(src, role):
    """1-based band number for a semantic role. Raises BandError, never guesses."""
    if role not in ROLES:
        raise BandError(f"Unknown band role '{role}'. Use one of {ROLES}.")
    overrides = json.loads(os.environ.get("GEOLLM_BANDS", "{}"))   # set by the harness from --bands
    if role in overrides:
        idx = int(overrides[role])
        check_explicit(src, role, idx)
        return idx
    info = infer_roles(list(src.descriptions), src.tags())["roles"][role]
    if info["status"] == "found":
        return info["bands"][0]
    labels = [d or "(unlabelled)" for d in src.descriptions]
    if info["status"] == "ambiguous":
        raise BandError(f"Several bands could be '{role}' {info['bands']} (labels: {labels}). Ask the user which.")
    raise BandError(f"No '{role}' band in this file (labels: {labels}). "
                    f"Do not substitute another band; report that '{role}' is unavailable.")


def read_role(src, role):
    return read_band(src, band_for(src, role))


def write_raster(path: str, arr: np.ndarray, src: Any, nodata: Any = None) -> None:
    """Save a 2D NumPy array as a GeoTIFF with the same CRS and grid as `src`.

    Args:
        path: Output file path.
        arr: 2D NumPy array containing raster data.
        src: An open rasterio dataset used for CRS and transform metadata.
            This is NOT a file path.
        nodata: Optional NoData value. Pixels equal to this value are treated
            as invalid by later readers and checks. Choose a value that does
            not also occur as real data in the array, or omit it.
    """
    arr = np.asarray(arr)
    if arr.dtype == bool:
        arr = arr.astype("uint8")
    if nodata is None and arr.dtype.kind == "f":
        nodata = np.nan

    nodata_is_nan = isinstance(nodata, float) and np.isnan(nodata)
    if nodata is not None and not nodata_is_nan:
        if np.any(arr == nodata):
            raise ValueError(
                f"nodata={nodata} also occurs as data in the array; those "
                f"pixels would be treated as invalid by later readers. "
                f"Choose a nodata value that does not occur in the data, "
                f"or omit nodata."
            )

    with rasterio.open(str(path), "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1],
                       count=1, dtype=str(arr.dtype), crs=src.crs, transform=src.transform,
                       nodata=nodata, compress="deflate") as dst:
        dst.write(arr, 1)