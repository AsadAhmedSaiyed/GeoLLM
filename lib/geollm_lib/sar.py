"""SAR helpers. SAR is radar backscatter, not reflectance: do not apply optical formulas to it."""
import numpy as np
from scipy import ndimage

from .io import read_role


def is_db(arr):
    """True if values look like dB (negative values exist), False if they look like linear backscatter, None if neither."""
    v = arr[np.isfinite(arr)]
    if v.size == 0:
        return None
    if v.min() < 0:
        return True
    return False if np.percentile(v, 99) <= 5 else None


def to_db(linear):
    """Linear backscatter -> dB (NaN where <= 0)."""
    with np.errstate(divide="ignore", invalid="ignore"):
        out = 10 * np.log10(np.where(linear > 0, linear, np.nan))
    return out.astype("float32")


def backscatter_db(src, pol):
    """Backscatter in dB for polarization 'vv'|'vh'|'hh'|'hv'. Raises if the values look like uncalibrated DN."""
    arr = read_role(src, pol)
    kind = is_db(arr)
    if kind is None:
        raise ValueError("Backscatter values look like uncalibrated DN/amplitude; radiometric calibration is required first.")
    return arr if kind else to_db(arr)


def speckle_filter(arr, size=5):
    """NaN-aware boxcar (mean) filter. Apply to linear power ideally; on dB it is a rough smoother."""
    ok = np.isfinite(arr)
    num = ndimage.uniform_filter(np.where(ok, arr, 0.0), size=size)
    den = ndimage.uniform_filter(ok.astype("float32"), size=size)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = num / den
    out[~ok] = np.nan
    return out.astype("float32")


def ratio_db(a_db, b_db):
    """a/b in linear terms = a_db - b_db (e.g. VV/VH)."""
    return (a_db - b_db).astype("float32")


def db_change(before_db, after_db):
    """after - before in dB. Negative = backscatter dropped."""
    return (after_db - before_db).astype("float32")


def flood_candidate_mask(before_db, after_db, drop_db=3.0, max_after_db=-15.0):
    """Open-water flood screening: backscatter fell by >= drop_db AND is now <= max_after_db (VV-like dB).
    Returns (mask, cutoffs dict). These are literature-typical screening values, not calibrated for this scene: report them."""
    diff = after_db - before_db
    ok = np.isfinite(diff) & np.isfinite(after_db)
    mask = np.zeros(diff.shape, bool)
    mask[ok] = (diff[ok] <= -drop_db) & (after_db[ok] <= max_after_db)
    return mask, {"drop_db": drop_db, "max_after_db": max_after_db}