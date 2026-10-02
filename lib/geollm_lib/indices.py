"""Spectral indices. Bands are found from the file's labels; nothing is guessed."""
import numpy as np

from .io import band_for, check_explicit, read_band


def _nd(a, b):
    with np.errstate(divide="ignore", invalid="ignore"):
        out = (a - b) / (a + b)
    out[(a + b) == 0] = np.nan
    return out.astype("float32")


def _refl(arr):
    """Sentinel-2 style integers (0..10000) -> 0..1."""
    if np.isfinite(arr).any() and np.nanpercentile(arr, 99) > 2:
        return arr / 10000.0
    return arr


def _savi(b):
    nir, red = _refl(b["nir"]), _refl(b["red"])
    return ((nir - red) / (nir + red + 0.5) * 1.5).astype("float32")


def _evi(b):
    nir, red, blue = _refl(b["nir"]), _refl(b["red"]), _refl(b["blue"])
    with np.errstate(divide="ignore", invalid="ignore"):
        return (2.5 * (nir - red) / (nir + 6 * red - 7.5 * blue + 1)).astype("float32")


INDEX_DEFS = {
    "ndvi": (("nir", "red"), "Vegetation greenness/vigour. ~0.5-0.9 dense healthy vegetation, 0.2-0.4 sparse or stressed, ~0 bare soil or built-up, negative water.", lambda b: _nd(b["nir"], b["red"])),
    "ndmi": (("nir", "swir1"), "Moisture content of vegetation/canopy. High = moist, low or negative = dry or non-vegetated.", lambda b: _nd(b["nir"], b["swir1"])),
    "nbr": (("nir", "swir2"), "Burn severity / vegetation disturbance. High = healthy, low = burned or bare.", lambda b: _nd(b["nir"], b["swir2"])),
    "ndwi": (("green", "nir"), "Open water (McFeeters). High = water.", lambda b: _nd(b["green"], b["nir"])),
    "mndwi": (("green", "swir1"), "Open water, more robust in built-up areas. High = water.", lambda b: _nd(b["green"], b["swir1"])),
    "ndbi": (("swir1", "nir"), "Built-up and bare surfaces. High = built-up.", lambda b: _nd(b["swir1"], b["nir"])),
    "savi": (("nir", "red"), "Soil-adjusted vegetation index, better for sparse vegetation (L=0.5).", _savi),
    "evi": (("nir", "red", "blue"), "Enhanced vegetation index, less saturated in dense canopy.", _evi),
}


def describe_indices():
    return {n: {"roles": list(r), "meaning": doc} for n, (r, doc, _) in INDEX_DEFS.items()}


def compute_index(name, src, bands=None):
    """Compute an index as a float32 array (NaN = nodata). bands={'nir': 4,...} is an optional explicit mapping."""
    name = name.lower()
    if name not in INDEX_DEFS:
        raise ValueError(f"Unknown index '{name}'. Available: {sorted(INDEX_DEFS)}")
    roles, _, fn = INDEX_DEFS[name]
    arrays = {}
    for role in roles:
        if bands and role in bands:
            idx = int(bands[role])
            check_explicit(src, role, idx)
        else:
            idx = band_for(src, role)
        arrays[role] = read_band(src, idx)
    return fn(arrays)