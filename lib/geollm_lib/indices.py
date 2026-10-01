import numpy as np
from .io import read_band

ALIASES = {
    "blue":  {"blue", "b2", "b02"},
    "green": {"green", "b3", "b03"},
    "red":   {"red", "b4", "b04"},
    "nir":   {"nir", "nir08", "b8", "b08", "b8a"},
    "swir1": {"swir1", "swir16", "b11"},
    "swir2": {"swir2", "swir22", "b12"},
}


def _check_role(src, role, idx):
    """Refuse a mapping that contradicts the file's own band labels."""
    if not 1 <= idx <= src.count:
        raise ValueError(f"Band {idx} for '{role}' does not exist. File has {src.count} bands.")
    desc = (src.descriptions[idx - 1] or "").strip().lower()
    if not desc:
        return
    for other, names in ALIASES.items():
        if other != role and desc in names and desc not in ALIASES[role]:
            raise ValueError(
                f"Band {idx} is labelled '{desc}' in the file, but was assigned the role '{role}'. "
                f"Do not guess bands. If the file has no '{role}' band, this index cannot be computed."
            )

REQUIRED = {
    "ndvi": ["nir", "red"],
    "ndmi": ["nir", "swir1"],
    "nbr": ["nir", "swir2"],
    "evi": ["nir", "red", "blue"],
}


def _norm_diff(a, b):
    """(a - b) / (a + b), with NaN where the bottom is 0."""
    with np.errstate(divide="ignore", invalid="ignore"):
        out = (a - b) / (a + b)
    out[(a + b) == 0] = np.nan
    return out


def _to_reflectance(arr):
    """Sentinel-2 style integers (0..10000) -> 0..1."""
    return arr / 10000.0 if np.nanpercentile(arr, 99) > 2 else arr


def compute_index(name, src, bands):
    """bands = {"nir": 4, "red": 3, ...} using 1-based band numbers."""
    name = name.lower()
    if name not in REQUIRED:
        raise ValueError(f"Unknown index '{name}'. Supported: {list(REQUIRED)}")
    missing = [r for r in REQUIRED[name] if r not in bands]
    if missing:
        raise ValueError(f"{name} needs bands {missing}. Example: bands={{'nir': 4, 'red': 3}}")

    for role in REQUIRED[name]:
        _check_role(src, role, bands[role])
    a = {role: read_band(src, bands[role]) for role in REQUIRED[name]}

    if name == "ndvi":
        return _norm_diff(a["nir"], a["red"])
    if name == "ndmi":
        return _norm_diff(a["nir"], a["swir1"])
    if name == "nbr":
        return _norm_diff(a["nir"], a["swir2"])
    nir, red, blue = (_to_reflectance(a[k]) for k in ("nir", "red", "blue"))
    with np.errstate(divide="ignore", invalid="ignore"):
        return (2.5 * (nir - red) / (nir + 6 * red - 7.5 * blue + 1)).astype("float32")