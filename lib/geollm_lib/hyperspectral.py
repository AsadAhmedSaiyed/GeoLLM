"""Hyperspectral helpers. Wavelengths come from the file's own metadata; units are never silently assumed."""
import re

import numpy as np

from .bands import BandError
from .io import read_band

_KEYS = ("wavelength", "WAVELENGTH", "center_wavelength", "CENTER_WAVELENGTH", "wavelength_nm")
_NUM = re.compile(r"(\d+(?:\.\d+)?)\s*(nm|um|µm|microns?)?", re.I)
_UNIT = {"nm": 1.0, "um": 1000.0, "µm": 1000.0, "micron": 1000.0, "microns": 1000.0}


def _to_nm(value, default_unit):
    m = _NUM.search(str(value))
    if not m:
        return None, None
    v = float(m.group(1))
    unit = (m.group(2) or default_unit or "").lower()
    if unit in _UNIT:
        return v * _UNIT[unit], "explicit_unit"
    if 300 <= v <= 2600:
        return v, "assumed_nm"
    return None, None


def band_wavelengths(src):
    """Returns (wavelengths_nm as float array, unit_source). Raises BandError if any band has no readable wavelength."""
    tags = src.tags()
    default_unit = tags.get("wavelength_unit") or tags.get("WAVELENGTH_UNIT")
    values = [None] * src.count
    ds_list = tags.get("wavelengths") or tags.get("WAVELENGTHS")
    if ds_list:
        parts = [p for p in re.split(r"[,\s;]+", str(ds_list).strip("{}[] ")) if p]
        if len(parts) == src.count:
            values = parts
    for i in range(1, src.count + 1):
        if values[i - 1] is None:
            bt = src.tags(i)
            values[i - 1] = next((bt[k] for k in _KEYS if k in bt), None)
        if values[i - 1] is None:
            values[i - 1] = src.descriptions[i - 1]
    out, sources = [], set()
    for v in values:
        nm, how = _to_nm(v, default_unit) if v is not None else (None, None)
        if nm is None:
            raise BandError("Not every band has a readable wavelength in this file's metadata.")
        out.append(nm)
        sources.add(how)
    return np.asarray(out, dtype="float64"), ("assumed_nm" if "assumed_nm" in sources else "explicit_unit")


def band_at(src, nm, tol=15.0):
    """1-based band index closest to `nm` nanometres. Raises BandError if none within `tol`."""
    wl, _ = band_wavelengths(src)
    i = int(np.argmin(np.abs(wl - nm)))
    if abs(wl[i] - nm) > tol:
        raise BandError(f"No band within {tol} nm of {nm} nm (range {wl.min():.0f}-{wl.max():.0f} nm).")
    return i + 1


def read_at(src, nm, tol=15.0):
    """float32 array (NaN = nodata) of the band nearest to `nm` nm."""
    return read_band(src, band_at(src, nm, tol))


def spectral_ratio(src, nm_a, nm_b, tol=15.0):
    """float32 array: band(nm_a) / band(nm_b)."""
    a, b = read_at(src, nm_a, tol), read_at(src, nm_b, tol)
    with np.errstate(divide="ignore", invalid="ignore"):
        return (a / b).astype("float32")


def normalized_difference_nm(src, nm_a, nm_b, tol=15.0):
    """float32 array: (band(nm_a) - band(nm_b)) / (band(nm_a) + band(nm_b))."""
    a, b = read_at(src, nm_a, tol), read_at(src, nm_b, tol)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = (a - b) / (a + b)
    out[(a + b) == 0] = np.nan
    return out.astype("float32")


def spectral_signature(src, mask=None):
    """(wavelengths_nm, mean value per band) over `mask` (boolean 2D) or the whole image."""
    wl, _ = band_wavelengths(src)
    means = []
    for i in range(1, src.count + 1):
        b = read_band(src, i)
        v = b[mask] if mask is not None else b.ravel()
        v = v[np.isfinite(v)]
        means.append(float(v.mean()) if v.size else np.nan)
    return wl, np.asarray(means)


def spectral_angle(src, reference, max_values=2e8):
    """Per-pixel spectral angle (radians) to a reference spectrum (one value per band). Small = similar."""
    ref = np.asarray(reference, dtype="float64")
    if len(ref) != src.count:
        raise ValueError(f"reference has {len(ref)} values but the file has {src.count} bands")
    if src.count * src.height * src.width > max_values:
        raise ValueError("Cube too large to load at once; clip or tile it first.")
    cube = src.read(masked=True).astype("float64").filled(np.nan)
    dot = np.nansum(cube * ref[:, None, None], axis=0)
    norm = np.sqrt(np.nansum(cube ** 2, axis=0)) * np.sqrt(np.sum(ref ** 2))
    with np.errstate(divide="ignore", invalid="ignore"):
        ang = np.arccos(np.clip(dot / norm, -1, 1))
    ang[~np.isfinite(cube).all(axis=0)] = np.nan
    return ang.astype("float32")