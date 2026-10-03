"""Masks: relative/absolute selection, combining, area, regions."""
import numpy as np
from scipy import ndimage


def valid_mask(*arrays):
    return np.logical_and.reduce([np.isfinite(a) for a in arrays])


def select_extreme(arr, fraction=0.2, keep="high"):
    """Select the top ('high') or bottom ('low') `fraction` of valid pixels. Returns (mask, cutoff)."""
    if not 0 < fraction < 1:
        raise ValueError("fraction must be between 0 and 1")
    if keep not in ("high", "low"):
        raise ValueError("keep must be 'high' or 'low'")
    valid = np.isfinite(arr)
    if not valid.any():
        raise ValueError("no valid pixels")
    cutoff = float(np.quantile(arr[valid], 1 - fraction if keep == "high" else fraction))
    mask = np.zeros(arr.shape, bool)
    mask[valid] = arr[valid] >= cutoff if keep == "high" else arr[valid] <= cutoff
    return mask, cutoff


def threshold_mask(arr, value, keep="above"):
    valid = np.isfinite(arr)
    mask = np.zeros(arr.shape, bool)
    mask[valid] = arr[valid] > value if keep == "above" else arr[valid] < value
    return mask


def combine(masks, op="and"):
    """op: 'and', 'or', or 'and_not' (first mask minus all the others)."""
    masks = [np.asarray(m, bool) for m in masks]
    if op == "and":
        return np.logical_and.reduce(masks)
    if op == "or":
        return np.logical_or.reduce(masks)
    if op == "and_not":
        out = masks[0].copy()
        for m in masks[1:]:
            out &= ~m
        return out
    raise ValueError("op must be 'and', 'or' or 'and_not'")


def area_stats(mask, src, valid=None):
    """Selected pixel count, percent of valid pixels and hectares for a boolean mask. Returns a dict with keys: selected_pixels, valid_pixels, percent_of_valid, pixel_area_m2 and area_hectares (area_hectares is None, with 'area_note', when the CRS is not in metres)."""
    mask = np.asarray(mask, bool)
    if valid is not None:
        mask = mask & valid
    count = int(mask.sum())
    denom = int(valid.sum()) if valid is not None else int(mask.size)
    out = {"selected_pixels": count, "valid_pixels": denom,
           "percent_of_valid": round(100 * count / denom, 4) if denom else None}
    crs = src.crs
    if crs is not None and crs.is_projected and str(crs.linear_units).lower() in ("metre", "meter", "m"):
        px = abs(src.res[0] * src.res[1])
        out["pixel_area_m2"] = px
        out["area_hectares"] = round(count * px / 10000, 3)
    else:
        out["area_hectares"] = None
        out["area_note"] = "CRS is not in metres; reproject before reporting area."
    return out


def filter_small(mask, min_pixels):
    """Remove connected patches smaller than min_pixels."""
    labels, n = ndimage.label(mask)
    if n == 0:
        return np.asarray(mask, bool)
    sizes = np.bincount(labels.ravel())
    keep = sizes >= min_pixels
    keep[0] = False
    return keep[labels]


def region_summary(mask, top=5):
    labels, n = ndimage.label(mask)
    if n == 0:
        return {"regions": 0, "largest_pixels": 0, "top_sizes": []}
    sizes = np.sort(np.bincount(labels.ravel())[1:])[::-1]
    return {"regions": int(n), "largest_pixels": int(sizes[0]), "top_sizes": [int(s) for s in sizes[:top]]}


def quadrant_summary(mask):
    """Share (%) of selected pixels in each image quadrant. Assumes a north-up image."""
    m = np.asarray(mask, bool)
    total, (h, w) = int(m.sum()), m.shape
    r, c = h // 2, w // 2
    parts = {"north_west": m[:r, :c], "north_east": m[:r, c:], "south_west": m[r:, :c], "south_east": m[r:, c:]}
    return {k: (round(100 * int(v.sum()) / total, 2) if total else 0.0) for k, v in parts.items()}

def distance_to_mask(mask, src):
    """Distance in CRS units (metres if projected) from every pixel to the nearest True pixel of `mask`."""
    return ndimage.distance_transform_edt(~np.asarray(mask, bool),
                                          sampling=(abs(src.res[1]), abs(src.res[0]))).astype("float32")


def label_regions(mask):
    """Connected regions of a mask. Returns (label_array, number_of_regions)."""
    return ndimage.label(np.asarray(mask, bool))