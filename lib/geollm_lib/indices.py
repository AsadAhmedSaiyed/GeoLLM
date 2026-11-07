"""Spectral indices. Bands are found from the file's labels; nothing is guessed."""
import numpy as np

from .io import band_for, check_explicit, read_band


def _nd(a, b):
    with np.errstate(divide="ignore", invalid="ignore"):
        out = (a - b) / (a + b)
    out[(a + b) == 0] = np.nan
    return out.astype("float32")


def _refl(arr):
    """Sentinel-2 / Landsat integer surface reflectance (0..10000) -> 0..1 float32."""
    arr = np.asarray(arr, dtype="float32")
    if np.isfinite(arr).any() and np.nanpercentile(arr, 99) > 2:
        return np.clip(arr / 10000.0, 0.0, 1.5).astype("float32")
    return arr


def to_surface_reflectance(arr, tags=None, filename=""):
    """Convert raw sensor DN array to physical Bottom-of-Atmosphere surface reflectance [0..1].

    Automatically harmonizes Sentinel-2 L2A Processing Baseline 04.00+ (post-2022-01-25)
    which encodes surface reflectance with BOA_ADD_OFFSET = -1000 (DN = reflectance * 10000 + 1000),
    as well as standard 0..10000 integer reflectance.
    """
    import re
    arr = np.asarray(arr, dtype="float32").copy()
    tags = tags or {}
    if not np.isfinite(arr).any() or np.nanpercentile(arr, 99) <= 2.0:
        return arr

    boa_offset = tags.get("BOA_ADD_OFFSET") or tags.get("boa_add_offset")
    offset_val = 0.0
    if boa_offset is not None and str(boa_offset).strip() != "":
        try:
            offset_val = float(boa_offset)
        except (ValueError, TypeError):
            offset_val = 0.0
    else:
        baseline = tags.get("s2_processing_baseline") or tags.get("PROCESSING_BASELINE")
        acq_date = str(tags.get("acquisition_date") or tags.get("datetime") or "")[:10]
        if not acq_date and filename:
            m = re.search(r"(\d{4}-\d{2}-\d{2})", str(filename))
            if m:
                acq_date = m.group(1)
        is_s2 = (
            "sentinel-2" in str(tags.get("collection", "")).lower()
            or "sentinel-2" in str(filename).lower()
            or baseline is not None
        )
        if is_s2:
            try:
                if baseline and float(baseline) >= 4.0:
                    offset_val = -1000.0
                elif acq_date >= "2022-01-25" and float(np.nanpercentile(arr, 1)) > 700.0:
                    offset_val = -1000.0
            except (ValueError, TypeError):
                pass

    return np.clip((arr + offset_val) / 10000.0, 0.0001, 1.5).astype("float32")


def _savi(b):
    nir, red = _refl(b["nir"]), _refl(b["red"])
    return ((nir - red) / (nir + red + 0.5) * 1.5).astype("float32")


def _msavi2(b):
    """Modified Soil-Adjusted Vegetation Index 2 (Qi et al., 1994) — self-adjusting L for arid/urban soil."""
    nir, red = _refl(b["nir"]), _refl(b["red"])
    with np.errstate(invalid="ignore"):
        radicand = np.maximum(0.0, (2.0 * nir + 1.0) ** 2 - 8.0 * (nir - red))
        out = 0.5 * (2.0 * nir + 1.0 - np.sqrt(radicand))
    return out.astype("float32")


def _evi(b):
    nir, red, blue = _refl(b["nir"]), _refl(b["red"]), _refl(b["blue"])
    with np.errstate(divide="ignore", invalid="ignore"):
        return (2.5 * (nir - red) / (nir + 6 * red - 7.5 * blue + 1)).astype("float32")


def _bsi(b):
    """Bare Soil Index (Rikimaru et al., 2002) — separates bare soil/sand/rubble from vegetation and water."""
    swir1, red, nir, blue = _refl(b["swir1"]), _refl(b["red"]), _refl(b["nir"]), _refl(b["blue"])
    num = (swir1 + red) - (nir + blue)
    den = (swir1 + red) + (nir + blue)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = num / den
    out[den == 0] = np.nan
    return out.astype("float32")


def _ibi(b):
    """Index-Based Built-Up Index (Xu, 2008) — isolates built-up impervious surfaces using NDBI, SAVI, and MNDWI."""
    swir1, nir, red, green = _refl(b["swir1"]), _refl(b["nir"]), _refl(b["red"]), _refl(b["green"])
    ndbi = _nd(swir1, nir)
    savi = ((nir - red) / (nir + red + 0.5) * 1.5).astype("float32")
    mndwi = _nd(green, swir1)
    half_bg = (savi + mndwi) / 2.0
    with np.errstate(divide="ignore", invalid="ignore"):
        out = (ndbi - half_bg) / (ndbi + half_bg)
    out[(ndbi + half_bg) == 0] = np.nan
    return out.astype("float32")


INDEX_DEFS = {
    "ndvi": (("nir", "red"), "Vegetation greenness/vigour. ~0.5-0.9 dense healthy vegetation, 0.2-0.4 sparse or stressed, ~0 bare soil or built-up, negative water.", lambda b: _nd(b["nir"], b["red"])),
    "msavi2": (("nir", "red"), "Modified Soil-Adjusted Vegetation Index 2 (Qi et al. 1994). Suppresses bare soil background noise in arid/semi-arid and urban environments.", _msavi2),
    "savi": (("nir", "red"), "Soil-adjusted vegetation index, better for sparse vegetation (L=0.5).", _savi),
    "evi": (("nir", "red", "blue"), "Enhanced vegetation index, less saturated in dense canopy.", _evi),
    "ndmi": (("nir", "swir1"), "Moisture content of vegetation/canopy. High = moist, low or negative = dry or non-vegetated.", lambda b: _nd(b["nir"], b["swir1"])),
    "nbr": (("nir", "swir2"), "Burn severity / vegetation disturbance. High = healthy, low = burned or bare.", lambda b: _nd(b["nir"], b["swir2"])),
    "ndwi": (("green", "nir"), "Open water (McFeeters). High = water.", lambda b: _nd(b["green"], b["nir"])),
    "mndwi": (("green", "swir1"), "Open water, more robust in built-up areas. High = water.", lambda b: _nd(b["green"], b["swir1"])),
    "ndbi": (("swir1", "nir"), "Built-up and bare surfaces. High = built-up.", lambda b: _nd(b["swir1"], b["nir"])),
    "ibi": (("swir1", "nir", "red", "green"), "Index-Based Built-Up Index (Xu 2008). Suppresses vegetation and water/soil noise to isolate built-up impervious surfaces.", _ibi),
    "bsi": (("swir1", "red", "nir", "blue"), "Bare Soil Index. High values indicate exposed bare soil, sand, or cleared/disturbed ground.", _bsi),
    "ui": (("swir2", "nir"), "Urban Index (Kawamura 1996). Uses SWIR2 and NIR to highlight dense urban/impervious structures.", lambda b: _nd(b["swir2"], b["nir"])),
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
    tags = src.tags() if hasattr(src, "tags") else {}
    fname = getattr(src, "name", "")
    for role in roles:
        if bands and role in bands:
            idx = int(bands[role])
            check_explicit(src, role, idx)
        else:
            idx = band_for(src, role)
        raw = read_band(src, idx)
        arrays[role] = to_surface_reflectance(raw, tags=tags, filename=fname)
    return fn(arrays)