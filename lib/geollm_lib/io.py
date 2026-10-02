"""Raster I/O and semantic band lookup."""
import json
import os

import numpy as np
import rasterio

from .bands import BandError, ROLES, detect_sensor, infer_roles, label_role


def read_band(src, index):
    """Read one band (1-based) as float32. NoData becomes NaN."""
    if not 1 <= index <= src.count:
        raise BandError(f"Band {index} does not exist. File has {src.count} bands (1..{src.count}).")
    return src.read(index, masked=True).astype("float32").filled(np.nan)


def check_explicit(src, role, idx):
    """Refuse a mapping that contradicts the file's own band labels."""
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


def write_raster(path, arr, src, nodata=None):
    """Save a 2D array as a GeoTIFF with the same CRS and grid as `src`."""
    arr = np.asarray(arr)
    if arr.dtype == bool:
        arr = arr.astype("uint8")
    if nodata is None and arr.dtype.kind == "f":
        nodata = np.nan
    with rasterio.open(str(path), "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1],
                       count=1, dtype=str(arr.dtype), crs=src.crs, transform=src.transform,
                       nodata=nodata, compress="deflate") as dst:
        dst.write(arr, 1)