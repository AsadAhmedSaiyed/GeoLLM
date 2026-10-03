"""Multi-date analysis. Dates come from file metadata."""
import datetime as dt

import numpy as np
import rasterio

from .align import same_grid
from .indices import compute_index

_KEYS = ("ACQUISITION_DATETIME", "DATETIME", "DATE", "datetime", "TIFFTAG_DATETIME")


def acquisition_date(path):
    """datetime of a file from its tags, or None."""
    with rasterio.open(path) as src:
        tags = src.tags()
    for k in _KEYS:
        if tags.get(k):
            s = str(tags[k]).replace("Z", "+00:00").replace(":", "-", 2) if " " in str(tags[k]) else str(tags[k]).replace("Z", "+00:00")
            try:
                return dt.datetime.fromisoformat(s)
            except ValueError:
                continue
    return None


def order_by_date(paths):
    """[(path, datetime)] oldest first. Raises if any file has no readable date."""
    items = [(p, acquisition_date(p)) for p in paths]
    missing = [p for p, d in items if d is None]
    if missing:
        raise ValueError(f"No acquisition date in: {missing}")
    return sorted(items, key=lambda t: t[1].replace(tzinfo=None))


def index_stack(paths, name="ndvi"):
    """(array (T,H,W), dates) of an index over files ordered by date. All files must share one grid (see align.align_to)."""
    ordered = order_by_date(paths)
    arrays, dates, ref = [], [], None
    for p, d in ordered:
        with rasterio.open(p) as src:
            if ref is None:
                ref = (src.crs, src.shape, tuple(src.transform)[:6])
            elif not (src.crs == ref[0] and src.shape == ref[1] and np.allclose(tuple(src.transform)[:6], ref[2], atol=1e-6)):
                raise ValueError("Files are not on the same grid. Align them first with geollm_lib.align.align_to.")
            arrays.append(compute_index(name, src))
            dates.append(d)
    return np.stack(arrays), dates


def trend_per_year(stack, dates):
    """Per-pixel least-squares slope (index units per year). NaN where fewer than 3 valid dates."""
    t0 = dates[0].replace(tzinfo=None)
    x = np.array([(d.replace(tzinfo=None) - t0).days / 365.25 for d in dates])[:, None, None]
    valid = np.isfinite(stack)
    n = valid.sum(0)
    y = np.where(valid, stack, 0.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        xm = (x * valid).sum(0) / n
        ym = y.sum(0) / n
        cov = ((x - xm) * (y - ym) * valid).sum(0)
        var = (((x - xm) ** 2) * valid).sum(0)
        slope = cov / var
    slope[(n < 3) | (var <= 0)] = np.nan
    return slope.astype("float32")


def anomaly_zscore(stack):
    """z-score of the last date against the mean/std of the earlier dates. Needs >= 3 dates."""
    if stack.shape[0] < 3:
        raise ValueError("anomaly_zscore needs at least 3 dates")
    hist, last = stack[:-1], stack[-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        z = (last - np.nanmean(hist, axis=0)) / np.nanstd(hist, axis=0)
    return z.astype("float32")


def change_magnitude(a, b):
    """b - a (later minus earlier)."""
    return (b - a).astype("float32")