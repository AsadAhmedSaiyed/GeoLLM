"""
Time series analysis and temporal operations for GeoLLM.
Additive module for multi-date raster stacks and 1D pixel profiles.
"""
from __future__ import annotations

import math
import warnings
from datetime import datetime
from pathlib import Path
from typing import Callable, Literal

import numpy as np
import pandas as pd
import scipy.stats

from geollm_lib.align import align_to, same_grid
from geollm_lib.io import read_band
from geollm_lib.masks import valid_mask
from geollm_lib.temporal import acquisition_date, order_by_date


def load_series(
    paths: list[str | Path],
    reader: Callable[[str | Path], np.ndarray] | None = None,
    *,
    chunk_rows: int = 256,
    nodata: float = np.nan,
    align_resampling: str = "bilinear",
) -> tuple[np.ndarray, list[datetime], dict]:
    """Load N rasters into a (T, H, W) float32 stack, aligning to reference if needed."""
    import rasterio

    if not paths:
        raise ValueError("paths cannot be empty")

    str_paths = [str(p) for p in paths]
    ordered = order_by_date(str_paths)
    sorted_paths = [p for p, _ in ordered]
    dates = [d for _, d in ordered]

    ref_path = sorted_paths[0]
    with rasterio.open(ref_path) as ref_src:
        ref_crs = ref_src.crs
        ref_transform = ref_src.transform
        ref_shape = (ref_src.height, ref_src.width)
        ref_profile = ref_src.profile.copy()

    aligned_paths = [ref_path]
    for p in sorted_paths[1:]:
        with rasterio.open(p) as cur_src:
            with rasterio.open(ref_path) as r_src:
                if same_grid(r_src, cur_src):
                    aligned_paths.append(p)
                else:
                    aligned = align_to(r_src, p, resampling=align_resampling)
                    aligned_paths.append(aligned)

    T = len(aligned_paths)
    H, W = ref_shape

    if reader is not None:
        first_arr = reader(aligned_paths[0])
        if first_arr.shape != (H, W):
            raise ValueError(f"Reader returned shape {first_arr.shape}, expected {(H, W)}")
        stack = np.empty((T, H, W), dtype=np.float32)
        stack[0] = first_arr
        for t in range(1, T):
            stack[t] = reader(aligned_paths[t])
    else:
        stack = np.empty((T, H, W), dtype=np.float32)
        for r_start in range(0, H, chunk_rows):
            r_end = min(r_start + chunk_rows, H)
            window = rasterio.windows.Window(0, r_start, W, r_end - r_start)
            for t, p in enumerate(aligned_paths):
                with rasterio.open(p) as src:
                    chunk = src.read(1, window=window, masked=True).astype(np.float32)
                    chunk_filled = chunk.filled(np.nan)
                    stack[t, r_start:r_end, :] = chunk_filled

    meta = {
        "crs": ref_crs.to_string() if ref_crs else None,
        "transform": list(ref_transform)[:6],
        "shape": [H, W],
        "timestamps": [d.isoformat() for d in dates],
        "paths": sorted_paths,
    }
    return stack, dates, meta


def zonal_series(
    stack: np.ndarray,
    dates: list[datetime],
    vector_path: str | Path,
    *,
    id_column: str | None = None,
    stat: Literal["mean", "median", "sum", "std"] = "mean",
    ref_raster_path: str | Path | None = None,
) -> pd.DataFrame:
    """Calculate time series aggregated across polygon zones."""
    import geopandas as gpd
    import rasterio.mask
    import rasterio

    gdf = gpd.read_file(vector_path)
    if id_column is not None:
        zone_ids = gdf[id_column].tolist()
    else:
        zone_ids = list(gdf.index)

    T, H, W = stack.shape
    if ref_raster_path is not None:
        with rasterio.open(ref_raster_path) as src:
            transform = src.transform
            crs = src.crs
    else:
        transform = rasterio.transform.from_origin(0, H, 1, 1)
        crs = None

    if crs is not None and gdf.crs is not None and gdf.crs != crs:
        gdf = gdf.to_crs(crs)

    results = {zid: [] for zid in zone_ids}

    for idx, row in gdf.iterrows():
        geom = [row.geometry]
        zid = row[id_column] if id_column else idx
        mask = rasterio.features.geometry_mask(
            geom, out_shape=(H, W), transform=transform, invert=True
        )
        for t in range(T):
            layer = stack[t]
            valid_pixels = layer[mask & np.isfinite(layer)]
            if valid_pixels.size == 0:
                val = np.nan
            elif stat == "mean":
                val = float(np.mean(valid_pixels))
            elif stat == "median":
                val = float(np.median(valid_pixels))
            elif stat == "sum":
                val = float(np.sum(valid_pixels))
            elif stat == "std":
                val = float(np.std(valid_pixels))
            else:
                raise ValueError(f"Unknown stat: {stat}")
            results[zid].append(val)

    df = pd.DataFrame(results, index=pd.DatetimeIndex(dates))
    df.index.name = "date"
    return df


def fill_gaps(
    stack: np.ndarray,
    dates: list[datetime],
    *,
    method: Literal["linear", "nearest", "forward", "backward"] = "linear",
    max_gap: int | None = None,
) -> np.ndarray:
    """Interpolate NaNs along the time axis (axis 0) for each spatial pixel."""
    T, H, W = stack.shape
    flat = stack.reshape(T, -1)
    out = np.empty_like(flat)

    dt_series = pd.Series(dates)
    numeric_index = dt_series.astype("int64").values

    for i in range(flat.shape[1]):
        col = flat[:, i]
        nans = np.isnan(col)
        if not nans.any():
            out[:, i] = col
            continue
        if nans.all():
            out[:, i] = np.nan
            continue

        s = pd.Series(col, index=numeric_index)
        if method == "linear":
            s_interp = s.interpolate(method="index", limit=max_gap, limit_direction="both")
        elif method == "nearest":
            s_interp = s.interpolate(method="nearest", limit=max_gap, limit_direction="both")
        elif method == "forward":
            s_interp = s.ffill(limit=max_gap)
        elif method == "backward":
            s_interp = s.bfill(limit=max_gap)
        else:
            raise ValueError(f"Unsupported gap fill method: {method}")
        out[:, i] = s_interp.values

    return out.reshape(T, H, W)


def lag_features(stack: np.ndarray, lags: list[int]) -> np.ndarray:
    """Generate lagged temporal features. Output shape is (len(lags), T, H, W)."""
    T, H, W = stack.shape
    out = np.full((len(lags), T, H, W), np.nan, dtype=np.float32)
    for idx, lag in enumerate(lags):
        if lag == 0:
            out[idx] = stack
        elif lag > 0:
            if lag < T:
                out[idx, lag:, :, :] = stack[:-lag, :, :]
        else:
            abs_lag = abs(lag)
            if abs_lag < T:
                out[idx, :-abs_lag, :, :] = stack[abs_lag:, :, :]
    return out


def ols_trend(
    stack: np.ndarray,
    dates: list[datetime],
    *,
    mask: np.ndarray | None = None,
) -> dict[str, np.ndarray]:
    """Compute vectorized ordinary least squares trend per pixel over time."""
    T, H, W = stack.shape
    d0 = dates[0]
    days = np.array([(d - d0).total_seconds() / 86400.0 for d in dates], dtype=np.float64)
    x = days / 365.2425

    flat = stack.reshape(T, -1)
    N = flat.shape[1]

    slope_arr = np.full(N, np.nan, dtype=np.float32)
    intercept_arr = np.full(N, np.nan, dtype=np.float32)
    r_val_arr = np.full(N, np.nan, dtype=np.float32)
    p_val_arr = np.full(N, np.nan, dtype=np.float32)
    std_err_arr = np.full(N, np.nan, dtype=np.float32)

    active = np.ones(N, dtype=bool)
    if mask is not None:
        active &= mask.ravel()

    for i in np.where(active)[0]:
        y = flat[:, i]
        valid = np.isfinite(y)
        if np.sum(valid) < 3:
            continue
        xv = x[valid]
        yv = y[valid]
        res = scipy.stats.linregress(xv, yv)
        slope_arr[i] = res.slope
        intercept_arr[i] = res.intercept
        r_val_arr[i] = res.rvalue
        p_val_arr[i] = res.pvalue
        std_err_arr[i] = res.stderr

    return {
        "slope": slope_arr.reshape(H, W),
        "intercept": intercept_arr.reshape(H, W),
        "r_value": r_val_arr.reshape(H, W),
        "p_value": p_val_arr.reshape(H, W),
        "std_err": std_err_arr.reshape(H, W),
    }


def mann_kendall(
    stack: np.ndarray,
    *,
    mask: np.ndarray | None = None,
    alpha: float = 0.05,
) -> dict[str, np.ndarray]:
    """Vectorized / pixel-wise Mann-Kendall non-parametric monotonic trend test."""
    T, H, W = stack.shape
    flat = stack.reshape(T, -1)
    N = flat.shape[1]

    tau_arr = np.full(N, np.nan, dtype=np.float32)
    p_arr = np.full(N, np.nan, dtype=np.float32)
    sig_arr = np.zeros(N, dtype=bool)

    active = np.ones(N, dtype=bool)
    if mask is not None:
        active &= mask.ravel()

    t_idx = np.arange(T)
    for i in np.where(active)[0]:
        y = flat[:, i]
        valid = np.isfinite(y)
        if np.sum(valid) < 4:
            continue
        tau, p = scipy.stats.kendalltau(t_idx[valid], y[valid])
        tau_arr[i] = tau
        p_arr[i] = p
        sig_arr[i] = p < alpha if np.isfinite(p) else False

    return {
        "tau": tau_arr.reshape(H, W),
        "p_value": p_arr.reshape(H, W),
        "significant": sig_arr.reshape(H, W),
    }


def sens_slope(
    stack: np.ndarray,
    dates: list[datetime],
    *,
    mask: np.ndarray | None = None,
) -> np.ndarray:
    """Compute Sen's slope (median pairwise slope) in units/year."""
    T, H, W = stack.shape
    d0 = dates[0]
    years = np.array([(d - d0).total_seconds() / (86400.0 * 365.2425) for d in dates], dtype=np.float64)

    flat = stack.reshape(T, -1)
    N = flat.shape[1]
    slopes = np.full(N, np.nan, dtype=np.float32)

    active = np.ones(N, dtype=bool)
    if mask is not None:
        active &= mask.ravel()

    for i in np.where(active)[0]:
        y = flat[:, i]
        valid = np.isfinite(y)
        if np.sum(valid) < 3:
            continue
        xv = years[valid]
        yv = y[valid]
        res = scipy.stats.siegelslopes(yv, xv)
        slopes[i] = res[0]

    return slopes.reshape(H, W)


def seasonal_baseline(
    stack: np.ndarray,
    dates: list[datetime],
    *,
    freq: Literal["month", "quarter", "doy"] = "month",
    stat: Literal["mean", "median"] = "median",
) -> tuple[np.ndarray, dict]:
    """Compute seasonal baseline climatology for anomaly detection."""
    T, H, W = stack.shape
    if freq == "month":
        keys = [d.month for d in dates]
    elif freq == "quarter":
        keys = [(d.month - 1) // 3 + 1 for d in dates]
    elif freq == "doy":
        keys = [d.timetuple().tm_yday for d in dates]
    else:
        raise ValueError(f"Unknown freq: {freq}")

    unique_keys = sorted(list(set(keys)))
    baseline_dict = {}
    anomalies = np.empty_like(stack)

    for k in unique_keys:
        idxs = [i for i, x in enumerate(keys) if x == k]
        sub = stack[idxs]
        if stat == "median":
            base = np.nanmedian(sub, axis=0)
        else:
            base = np.nanmean(sub, axis=0)
        baseline_dict[k] = base
        for idx in idxs:
            anomalies[idx] = stack[idx] - base

    return anomalies, baseline_dict


def stl_decompose(
    series_1d: np.ndarray | pd.Series,
    dates: list[datetime],
    *,
    period: int = 12,
    robust: bool = True,
) -> pd.DataFrame:
    """STL (Seasonal and Trend decomposition using Loess) for a 1D pixel time series."""
    from statsmodels.tsa.seasonal import STL

    if isinstance(series_1d, np.ndarray):
        s = pd.Series(series_1d, index=pd.DatetimeIndex(dates))
    else:
        s = series_1d.copy()
        s.index = pd.DatetimeIndex(dates)

    if s.isna().any():
        s = s.interpolate(method="time").bfill().ffill()

    stl = STL(s, period=period, robust=robust)
    res = stl.fit()
    return pd.DataFrame(
        {
            "observed": s.values,
            "trend": res.trend.values,
            "seasonal": res.seasonal.values,
            "resid": res.resid.values,
        },
        index=s.index,
    )


def change_points(
    stack: np.ndarray,
    dates: list[datetime],
    *,
    method: Literal["cusum", "pelt", "binseg"] = "cusum",
    threshold: float = 3.0,
    min_size: int = 3,
    penalty: float | None = None,
) -> dict[str, np.ndarray]:
    """Detect abrupt change points in time series across pixels or profile."""
    T, H, W = stack.shape
    change_count = np.zeros((H, W), dtype=np.int32)
    first_change_idx = np.full((H, W), -1, dtype=np.int32)

    if method == "cusum":
        flat = stack.reshape(T, -1)
        for i in range(flat.shape[1]):
            y = flat[:, i]
            valid = np.isfinite(y)
            if np.sum(valid) < 2 * min_size:
                continue
            y_v = y[valid]
            mean_y = np.mean(y_v)
            std_y = np.std(y_v)
            if std_y < 1e-6:
                continue
            z = (y_v - mean_y) / std_y
            s_pos = np.zeros(len(z))
            s_neg = np.zeros(len(z))
            cps = []
            for t in range(1, len(z)):
                s_pos[t] = max(0, s_pos[t - 1] + z[t] - 0.5)
                s_neg[t] = min(0, s_neg[t - 1] + z[t] + 0.5)
                if s_pos[t] > threshold or s_neg[t] < -threshold:
                    cps.append(t)
                    s_pos[t] = 0
                    s_neg[t] = 0
            if cps:
                r, c = divmod(i, W)
                change_count[r, c] = len(cps)
                first_change_idx[r, c] = cps[0]

    elif method in ("pelt", "binseg"):
        import ruptures as rpt

        flat = stack.reshape(T, -1)
        for i in range(flat.shape[1]):
            y = flat[:, i]
            valid = np.isfinite(y)
            if np.sum(valid) < 2 * min_size:
                continue
            y_v = y[valid].reshape(-1, 1)
            algo = rpt.Pelt(model="rbf", min_size=min_size) if method == "pelt" else rpt.Binseg(model="rbf", min_size=min_size)
            algo.fit(y_v)
            pen = penalty if penalty is not None else 3.0 * np.log(len(y_v))
            res = algo.predict(pen=pen)
            cps = [cp for cp in res if cp < len(y_v)]
            if cps:
                r, c = divmod(i, W)
                change_count[r, c] = len(cps)
                first_change_idx[r, c] = cps[0]
    else:
        raise ValueError(f"Unknown change point method: {method}")

    return {
        "change_count": change_count,
        "first_change_index": first_change_idx,
    }


def cluster_pixel_series(
    stack: np.ndarray,
    n_clusters: int = 4,
    *,
    mask: np.ndarray | None = None,
    random_state: int = 42,
) -> tuple[np.ndarray, np.ndarray]:
    """Cluster pixel temporal trajectories using k-means."""
    from sklearn.cluster import KMeans

    T, H, W = stack.shape
    flat = stack.reshape(T, -1).T
    N = flat.shape[0]

    valid_mask_px = ~np.isnan(flat).any(axis=1)
    if mask is not None:
        valid_mask_px &= mask.ravel()

    cluster_map = np.full(N, -1, dtype=np.int32)
    valid_indices = np.where(valid_mask_px)[0]
    if len(valid_indices) < n_clusters:
        return cluster_map.reshape(H, W), np.array([])

    X = flat[valid_indices]
    kmeans = KMeans(n_clusters=n_clusters, random_state=random_state, n_init=10)
    labels = kmeans.fit_predict(X)
    cluster_map[valid_indices] = labels
    return cluster_map.reshape(H, W), kmeans.cluster_centers_


def forecast_simple(
    series_1d: np.ndarray | pd.Series,
    dates: list[datetime],
    *,
    steps: int = 3,
    method: Literal["linear", "mean", "drift"] = "linear",
) -> tuple[np.ndarray, list[datetime]]:
    """Simple univariate baseline forecasting forward N steps."""
    y = np.asarray(series_1d, dtype=np.float64)
    valid = np.isfinite(y)
    if np.sum(valid) < 2:
        raise ValueError("Need at least 2 valid points to forecast")

    d0 = dates[0]
    days = np.array([(d - d0).total_seconds() / 86400.0 for d in dates])
    mean_dt = np.mean(np.diff(days))
    future_days = np.array([days[-1] + (k + 1) * mean_dt for k in range(steps)])
    future_dates = [datetime.fromtimestamp(d0.timestamp() + fd * 86400.0) for fd in future_days]

    if method == "linear":
        res = scipy.stats.linregress(days[valid], y[valid])
        preds = res.intercept + res.slope * future_days
    elif method == "mean":
        preds = np.full(steps, np.mean(y[valid]))
    elif method == "drift":
        idx_first = np.where(valid)[0][0]
        idx_last = np.where(valid)[0][-1]
        drift_slope = (y[idx_last] - y[idx_first]) / (days[idx_last] - days[idx_first])
        preds = y[idx_last] + drift_slope * (future_days - days[idx_last])
    else:
        raise ValueError(f"Unknown forecast method: {method}")

    return preds.astype(np.float32), future_dates

