"""Hyperspectral helpers. Wavelengths come from the file's own metadata; units are never silently assumed.

All array-based functions (continuum_removal, absorption_feature_depth, bad_band_mask,
spectral_unmix) accept plain NumPy arrays so they work identically with rasterio,
xarray/NetCDF4 (e.g. NASA EMIT), HDF5 (e.g. PRISMA), or ENVI cubes.
"""
import re
from typing import Optional, Sequence, Tuple, Union

import numpy as np
from rasterio.windows import Window
from scipy.optimize import nnls

from .bands import BandError
from .io import read_band

try:
    from numba import njit as _njit
    _HAS_NUMBA = True
except Exception:
    _HAS_NUMBA = False

_KEYS = (
    "wavelength",
    "WAVELENGTH",
    "center_wavelength",
    "CENTER_WAVELENGTH",
    "wavelength_nm",
    "WAVELENGTH_NM",
    "wavelength_um",
    "WAVELENGTH_UM",
)
_NUM = re.compile(
    r"(\d+(?:\.\d+)?)\s*(nm|nanometers?|um|µm|microns?|micrometers?)?",
    re.I,
)
_UNIT = {
    "nm": 1.0,
    "nanometer": 1.0,
    "nanometers": 1.0,
    "um": 1000.0,
    "µm": 1000.0,
    "micron": 1000.0,
    "microns": 1000.0,
    "micrometer": 1000.0,
    "micrometers": 1000.0,
}

# Standard atmospheric water-vapor absorption bands (nm) where SNR approaches zero.
DEFAULT_WATER_VAPOR_WINDOWS = ((1340.0, 1460.0), (1790.0, 1960.0))


def _to_nm(value, default_unit: Optional[str] = None) -> Tuple[Optional[float], Optional[str]]:
    m = _NUM.search(str(value))
    if not m:
        return None, None
    v = float(m.group(1))
    unit = (m.group(2) or default_unit or "").strip().lower()
    if unit in _UNIT:
        return v * _UNIT[unit], "explicit_unit"
    if 300.0 <= v <= 2600.0:
        return v, "assumed_nm"
    if 0.3 <= v <= 2.6:
        return v * 1000.0, "assumed_um"
    return None, None


def band_wavelengths(src, allow_missing: bool = False) -> Tuple[np.ndarray, str]:
    """Return (wavelengths_nm as float64 array, unit_source).

    Reads wavelengths from dataset tags, per-band tags, or band descriptions.
    Supports both nanometers (300-2600) and micrometers (0.3-2.6).
    Raises BandError if wavelengths cannot be determined (or if any band is
    missing a wavelength when allow_missing=False).
    """
    tags = src.tags()
    default_unit = (
        tags.get("wavelength_unit")
        or tags.get("WAVELENGTH_UNIT")
        or tags.get("wavelength units")
        or tags.get("WAVELENGTH_UNITS")
    )
    values = [None] * src.count
    ds_list = (
        tags.get("wavelengths")
        or tags.get("WAVELENGTHS")
        or tags.get("wavelength")
        or tags.get("WAVELENGTH")
        or tags.get("center_wavelengths")
    )
    if ds_list:
        parts = [p for p in re.split(r"[,\s;]+", str(ds_list).strip("{}[] ")) if p]
        if len(parts) == src.count:
            values = parts

    for i in range(1, src.count + 1):
        if values[i - 1] is None:
            bt = src.tags(i)
            key = next((k for k in _KEYS if k in bt), None)
            if key is not None:
                val = bt[key]
                # Hint unit from key name if explicit unit missing in value
                if key.lower().endswith("_um") and not _NUM.search(str(val) or "").group(2):
                    val = f"{val} um"
                elif key.lower().endswith("_nm") and not _NUM.search(str(val) or "").group(2):
                    val = f"{val} nm"
                values[i - 1] = val
        if values[i - 1] is None:
            values[i - 1] = src.descriptions[i - 1]

    out, sources = [], set()
    for v in values:
        nm, how = _to_nm(v, default_unit) if v is not None else (None, None)
        if nm is None:
            if not allow_missing:
                raise BandError("Not every band has a readable wavelength in this file's metadata.")
            out.append(np.nan)
        else:
            out.append(nm)
            sources.add(how)

    wl_arr = np.asarray(out, dtype="float64")
    if not np.isfinite(wl_arr).any():
        raise BandError("No readable wavelengths found in this file's metadata.")

    if "assumed_um" in sources:
        unit_source = "assumed_um"
    elif "assumed_nm" in sources:
        unit_source = "assumed_nm"
    else:
        unit_source = "explicit_unit"
    return wl_arr, unit_source


def bad_band_mask(
    wavelengths_nm: Sequence[float],
    tags: Optional[dict] = None,
    exclude_water_vapor: bool = True,
    water_vapor_windows: Sequence[Tuple[float, float]] = DEFAULT_WATER_VAPOR_WINDOWS,
    valid_range_nm: Optional[Tuple[float, float]] = None,
) -> np.ndarray:
    """Return a boolean 1D mask (True = usable band, False = bad/noisy band).

    Checks:
    1. Finite wavelengths.
    2. Sensor bad-band list ('bbl', 'BBL', 'good_wavelengths') in `tags` if present.
    3. Atmospheric water-vapor absorption windows (default 1340-1460 nm, 1790-1960 nm).
    4. Optional spectral bounds `valid_range_nm=(min_nm, max_nm)`.
    """
    wl = np.asarray(wavelengths_nm, dtype="float64")
    good = np.isfinite(wl)

    if tags:
        raw_bbl = (
            tags.get("bbl")
            or tags.get("BBL")
            or tags.get("bad_band_list")
            or tags.get("good_wavelengths")
        )
        if raw_bbl is not None:
            if isinstance(raw_bbl, str):
                parts = [p for p in re.split(r"[,\s;]+", raw_bbl.strip("{}[] ")) if p]
                if len(parts) == len(wl):
                    try:
                        bbl = np.asarray([float(p) for p in parts])
                        good &= bbl != 0
                    except ValueError:
                        pass
            else:
                bbl = np.asarray(raw_bbl)
                if len(bbl) == len(wl):
                    good &= bbl != 0

    if exclude_water_vapor:
        for lo, hi in water_vapor_windows:
            good &= ~((wl >= lo) & (wl <= hi))

    if valid_range_nm is not None:
        lo, hi = valid_range_nm
        good &= (wl >= lo) & (wl <= hi)

    return good


def band_at(src, nm: float, tol: float = 15.0) -> int:
    """1-based band index closest to `nm` nanometres. Raises BandError if none within `tol`."""
    wl, _ = band_wavelengths(src, allow_missing=True)
    finite = np.isfinite(wl)
    if not finite.any():
        raise BandError("No readable wavelengths found in this file's metadata.")
    diffs = np.where(finite, np.abs(wl - nm), np.inf)
    i = int(np.argmin(diffs))
    if diffs[i] > tol:
        raise BandError(
            f"No band within {tol} nm of {nm} nm (range {np.nanmin(wl):.0f}-{np.nanmax(wl):.0f} nm)."
        )
    return i + 1


def read_at(src, nm: float, tol: float = 15.0) -> np.ndarray:
    """float32 array (NaN = nodata) of the band nearest to `nm` nm."""
    return read_band(src, band_at(src, nm, tol))


def read_wavelength_subset(
    src,
    target_nms: Sequence[float],
    tol: float = 15.0,
    window: Optional[Window] = None,
) -> Tuple[np.ndarray, np.ndarray, list]:
    """Memory-safe selective reader for a list of target wavelengths (nm).

    Reads only the requested narrow bands instead of the full 3D hyperspectral cube.
    Returns (cube_float32 [K, H, W], actual_wavelengths_nm [K], band_indices_1based [K]).
    """
    wl, _ = band_wavelengths(src, allow_missing=True)
    finite = np.isfinite(wl)
    indices = []
    actual_nms = []
    for nm in target_nms:
        diffs = np.where(finite, np.abs(wl - nm), np.inf)
        i = int(np.argmin(diffs))
        if diffs[i] > tol:
            raise BandError(
                f"No band within {tol} nm of {nm} nm (range {np.nanmin(wl):.0f}-{np.nanmax(wl):.0f} nm)."
            )
        indices.append(i + 1)
        actual_nms.append(float(wl[i]))

    arr = src.read(indexes=indices, window=window, masked=True).astype("float32").filled(np.nan)
    return arr, np.asarray(actual_nms, dtype="float64"), indices


def spectral_ratio(src, nm_a: float, nm_b: float, tol: float = 15.0) -> np.ndarray:
    """float32 array: band(nm_a) / band(nm_b)."""
    a, b = read_at(src, nm_a, tol), read_at(src, nm_b, tol)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = a / b
    out[b == 0] = np.nan
    return out.astype("float32")


def normalized_difference_nm(src, nm_a: float, nm_b: float, tol: float = 15.0) -> np.ndarray:
    """float32 array: (band(nm_a) - band(nm_b)) / (band(nm_a) + band(nm_b))."""
    a, b = read_at(src, nm_a, tol), read_at(src, nm_b, tol)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = (a - b) / (a + b)
    out[(a + b) == 0] = np.nan
    return out.astype("float32")


def spectral_signature(
    src,
    mask: Optional[np.ndarray] = None,
    band_indices: Optional[Sequence[int]] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """Return (wavelengths_nm, mean_reflectance_per_band) over `mask` (2D bool) or whole image.

    Reads one band at a time so memory stays O(H * W), safe for 200-300+ band cubes.
    """
    wl_all, _ = band_wavelengths(src, allow_missing=True)
    idxs = list(band_indices) if band_indices is not None else list(range(1, src.count + 1))
    means = []
    wl_out = []
    for i in idxs:
        b = read_band(src, i)
        v = b[mask] if mask is not None else b.ravel()
        v = v[np.isfinite(v)]
        means.append(float(v.mean()) if v.size else np.nan)
        wl_out.append(wl_all[i - 1])
    return np.asarray(wl_out, dtype="float64"), np.asarray(means, dtype="float64")


def _upper_hull_1d_py(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Compute continuum-removed spectrum via upper convex hull (Clark & Roush, 1984)."""
    n = x.shape[0]
    out = np.full(n, np.nan, dtype=np.float64)
    valid_idx = np.where(np.isfinite(y) & np.isfinite(x))[0]
    if valid_idx.size < 2:
        return out

    # Andrew's monotone chain for the upper hull on sorted x
    hull = np.empty(valid_idx.size, dtype=np.int64)
    h_len = 0
    for k in range(valid_idx.size):
        idx = valid_idx[k]
        xi = x[idx]
        yi = y[idx]
        while h_len >= 2:
            a = hull[h_len - 2]
            b = hull[h_len - 1]
            # Cross product >= 0 means b is on or below the chord a -> idx
            cross = (x[b] - x[a]) * (yi - y[a]) - (y[b] - y[a]) * (xi - x[a])
            if cross >= 0.0:
                h_len -= 1
            else:
                break
        hull[h_len] = idx
        h_len += 1

    # Linearly interpolate continuum between consecutive upper-hull vertices
    for seg in range(h_len - 1):
        i0 = hull[seg]
        i1 = hull[seg + 1]
        x0, y0 = x[i0], y[i0]
        x1, y1 = x[i1], y[i1]
        dx = x1 - x0
        for j in range(i0, i1 + 1):
            if not np.isfinite(y[j]):
                continue
            cont = y0 + (y1 - y0) * ((x[j] - x0) / dx) if dx > 0 else y0
            if cont > 0.0:
                out[j] = y[j] / cont
    return out


if _HAS_NUMBA:
    @_njit(cache=True)
    def _continuum_removal_2d_numba(x: np.ndarray, mat: np.ndarray) -> np.ndarray:
        """mat shape: (B, N) -> returns (B, N) float32 continuum-removed spectra."""
        nb, nn = mat.shape
        out = np.full((nb, nn), np.nan, dtype=np.float32)
        hull = np.empty(nb, dtype=np.int64)
        valid_idx = np.empty(nb, dtype=np.int64)
        for col in range(nn):
            v_len = 0
            for i in range(nb):
                if np.isfinite(mat[i, col]) and np.isfinite(x[i]):
                    valid_idx[v_len] = i
                    v_len += 1
            if v_len < 2:
                continue
            h_len = 0
            for k in range(v_len):
                idx = valid_idx[k]
                xi = x[idx]
                yi = mat[idx, col]
                while h_len >= 2:
                    a = hull[h_len - 2]
                    b = hull[h_len - 1]
                    cross = (x[b] - x[a]) * (yi - mat[a, col]) - (mat[b, col] - mat[a, col]) * (xi - x[a])
                    if cross >= 0.0:
                        h_len -= 1
                    else:
                        break
                hull[h_len] = idx
                h_len += 1
            for seg in range(h_len - 1):
                i0 = hull[seg]
                i1 = hull[seg + 1]
                x0 = x[i0]
                y0 = mat[i0, col]
                x1 = x[i1]
                y1 = mat[i1, col]
                dx = x1 - x0
                for j in range(i0, i1 + 1):
                    yj = mat[j, col]
                    if not np.isfinite(yj):
                        continue
                    cont = y0 + (y1 - y0) * ((x[j] - x0) / dx) if dx > 0.0 else y0
                    if cont > 0.0:
                        out[j, col] = np.float32(yj / cont)
        return out


def continuum_removal(wavelengths_nm: Sequence[float], spectra: np.ndarray) -> np.ndarray:
    """Upper convex-hull continuum removal (Clark & Roush, 1984).

    Normalizes reflectance curves against their upper convex hull so absorption
    features can be measured independent of illumination or topography.
    Hull vertices equal 1.0; absorption dips lie in (0, 1).

    Args:
        wavelengths_nm: 1D array of band center wavelengths (nm), length B.
        spectra: NumPy array of shape (B,), (B, N), or (B, H, W).

    Returns:
        float32 array of the same shape as `spectra`.
    """
    wl = np.asarray(wavelengths_nm, dtype="float64")
    arr = np.asarray(spectra, dtype="float64")
    if arr.shape[0] != wl.shape[0]:
        raise ValueError(f"wavelengths length ({wl.shape[0]}) != spectra band axis ({arr.shape[0]})")

    order = np.argsort(wl)
    inv_order = np.argsort(order)
    wl_s = wl[order]
    orig_shape = arr.shape
    mat = arr[order].reshape(wl.shape[0], -1)

    if _HAS_NUMBA:
        cr_s = _continuum_removal_2d_numba(wl_s, np.ascontiguousarray(mat))
    else:
        cr_s = np.empty_like(mat, dtype="float32")
        for col in range(mat.shape[1]):
            cr_s[:, col] = _upper_hull_1d_py(wl_s, mat[:, col]).astype("float32")

    return cr_s[inv_order].reshape(orig_shape)


def absorption_feature_depth(
    wavelengths_nm: Sequence[float],
    spectra: np.ndarray,
    feature_nm: float,
    left_nm: float,
    right_nm: float,
    tol: float = 20.0,
) -> Union[float, np.ndarray]:
    """Continuum-removed absorption band depth at `feature_nm` between shoulders [left_nm, right_nm].

    Uses standard linear continuum interpolation (Clark & Roush, 1984):
        R_c = R(left) + ((wl_f - wl_l) / (wl_r - wl_l)) * (R(right) - R(left))
        depth = 1 - R(feature) / R_c

    Positive values indicate an absorption dip (e.g. Al-OH at 2200 nm between 2120 and 2250 nm,
    carbonate at 2340 nm between 2260 and 2400 nm, Fe3+ at 860 nm between 750 and 1000 nm).
    Works on 1D (B,), 2D (B, N), or 3D (B, H, W) arrays.
    """
    wl = np.asarray(wavelengths_nm, dtype="float64")
    arr = np.asarray(spectra, dtype="float32")
    if arr.shape[0] != wl.shape[0]:
        raise ValueError(f"wavelengths length ({wl.shape[0]}) != spectra band axis ({arr.shape[0]})")

    def _pick(target: float) -> Tuple[int, float]:
        diffs = np.where(np.isfinite(wl), np.abs(wl - target), np.inf)
        idx = int(np.argmin(diffs))
        if diffs[idx] > tol:
            raise BandError(f"No band within {tol} nm of {target} nm.")
        return idx, float(wl[idx])

    i_l, w_l = _pick(left_nm)
    i_f, w_f = _pick(feature_nm)
    i_r, w_r = _pick(right_nm)
    if not (w_l < w_f < w_r):
        raise ValueError(f"Expected left_nm ({w_l}) < feature_nm ({w_f}) < right_nm ({w_r}).")

    frac = np.float32((w_f - w_l) / (w_r - w_l))
    r_l = arr[i_l]
    r_f = arr[i_f]
    r_r = arr[i_r]
    cont = r_l + frac * (r_r - r_l)

    with np.errstate(divide="ignore", invalid="ignore"):
        depth = 1.0 - (r_f / cont)

    if np.ndim(depth) == 0:
        return float(depth) if (np.isfinite(depth) and cont > 0) else float("nan")
    depth = np.where(cont > 0, depth, np.nan).astype("float32")
    return depth


def _unmix_block(cube: np.ndarray, endmembers: np.ndarray, method: str) -> Tuple[np.ndarray, np.ndarray]:
    """Unmix a (B, H, W) block against endmembers (K, B). Returns (abundances [K, H, W], rmse [H, W])."""
    nb, h, w = cube.shape
    k = endmembers.shape[0]
    m_mat = endmembers.T.astype("float64")  # (B, K)
    flat = cube.reshape(nb, -1).astype("float64")  # (B, N)
    n_px = flat.shape[1]

    abund = np.full((k, n_px), np.nan, dtype="float32")
    rmse = np.full(n_px, np.nan, dtype="float32")

    valid_cols = np.all(np.isfinite(flat), axis=0)
    if not valid_cols.any():
        return abund.reshape(k, h, w), rmse.reshape(h, w)

    y_valid = flat[:, valid_cols]  # (B, M)
    m_valid = y_valid.shape[1]

    if method == "ucls":
        pinv = np.linalg.pinv(m_mat)  # (K, B)
        sol = pinv @ y_valid  # (K, M)
        recon = m_mat @ sol
        err = np.sqrt(np.mean((y_valid - recon) ** 2, axis=0))
        abund[:, valid_cols] = sol.astype("float32")
        rmse[valid_cols] = err.astype("float32")
        return abund.reshape(k, h, w), rmse.reshape(h, w)

    if method == "fcls":
        # Heinz & Chang (2001) FCLS via augmented NNLS:
        # minimize ||[delta * M; 1^T] s - [delta * y; 1]||_2 subject to s >= 0
        scale = float(np.linalg.norm(m_mat, ord="fro")) / max(1.0, np.sqrt(m_mat.size))
        delta = 1e-4 / max(scale, 1e-6)
        a_aug = np.vstack([delta * m_mat, np.ones((1, k), dtype="float64")])
        sol = np.empty((k, m_valid), dtype="float64")
        b_aug = np.empty(nb + 1, dtype="float64")
        b_aug[nb] = 1.0
        for idx in range(m_valid):
            b_aug[:nb] = delta * y_valid[:, idx]
            s, _ = nnls(a_aug, b_aug)
            s_sum = s.sum()
            if s_sum > 0:
                s /= s_sum
            sol[:, idx] = s
    elif method == "nnls":
        sol = np.empty((k, m_valid), dtype="float64")
        for idx in range(m_valid):
            s, _ = nnls(m_mat, y_valid[:, idx])
            sol[:, idx] = s
    else:
        raise ValueError(f"Unknown unmixing method '{method}'. Use 'fcls', 'nnls', or 'ucls'.")

    recon = m_mat @ sol
    err = np.sqrt(np.mean((y_valid - recon) ** 2, axis=0))
    abund[:, valid_cols] = sol.astype("float32")
    rmse[valid_cols] = err.astype("float32")
    return abund.reshape(k, h, w), rmse.reshape(h, w)


def spectral_unmix(
    src_or_cube,
    endmembers: np.ndarray,
    band_indices: Optional[Sequence[int]] = None,
    method: str = "fcls",
    block_size: int = 256,
) -> Tuple[np.ndarray, np.ndarray]:
    """Linear Spectral Unmixing of a hyperspectral raster or NumPy cube.

    Estimates fractional abundance of each endmember spectrum per pixel.
    When given a rasterio dataset, streams spatial blocks of `block_size x block_size`
    so memory remains bounded on large hyperspectral cubes.

    Args:
        src_or_cube: Open rasterio dataset OR 3D NumPy array of shape (B, H, W).
        endmembers: 2D array of shape (K, B) — K reference endmember spectra across B bands.
        band_indices: Optional 1-based band indices to read when `src_or_cube` is a rasterio
            dataset (e.g. from `bad_band_mask` to exclude water-vapor bands).
        method: 'fcls' (Fully Constrained Least Squares: s >= 0, sum(s) = 1; Heinz & Chang 2001),
            'nnls' (Non-Negative Least Squares: s >= 0), or 'ucls' (Unconstrained Least Squares).
        block_size: Spatial tile size when streaming from a rasterio dataset.

    Returns:
        (abundances [K, H, W] float32, rmse [H, W] float32).
    """
    em = np.asarray(endmembers, dtype="float64")
    if em.ndim != 2:
        raise ValueError(f"endmembers must be 2D (K, B), got shape {em.shape}")
    k, nb = em.shape

    if isinstance(src_or_cube, np.ndarray):
        if src_or_cube.ndim != 3 or src_or_cube.shape[0] != nb:
            raise ValueError(f"cube must have shape ({nb}, H, W), got {src_or_cube.shape}")
        return _unmix_block(src_or_cube, em, method)

    # Rasterio dataset path: stream spatial blocks
    idxs = list(band_indices) if band_indices is not None else list(range(1, src_or_cube.count + 1))
    if len(idxs) != nb:
        raise ValueError(f"endmembers has {nb} bands, but {len(idxs)} bands were selected")

    h, w = src_or_cube.height, src_or_cube.width
    abund_out = np.full((k, h, w), np.nan, dtype="float32")
    rmse_out = np.full((h, w), np.nan, dtype="float32")

    for r0 in range(0, h, block_size):
        rh = min(block_size, h - r0)
        for c0 in range(0, w, block_size):
            cw = min(block_size, w - c0)
            win = Window(c0, r0, cw, rh)
            blk = src_or_cube.read(indexes=idxs, window=win, masked=True).astype("float32").filled(np.nan)
            a_blk, e_blk = _unmix_block(blk, em, method)
            abund_out[:, r0 : r0 + rh, c0 : c0 + cw] = a_blk
            rmse_out[r0 : r0 + rh, c0 : c0 + cw] = e_blk

    return abund_out, rmse_out


def spectral_angle(
    src,
    reference: Sequence[float],
    band_indices: Optional[Sequence[int]] = None,
    block_size: int = 512,
    max_values: Optional[float] = None,
) -> np.ndarray:
    """Per-pixel Spectral Angle Mapper (radians) to a reference spectrum. Small = similar.

    Streams in spatial blocks (`block_size x block_size`) so large 200-300+ band cubes
    do not exhaust RAM. Pass `band_indices` (1-based) to exclude noisy water-vapor bands.
    """
    ref = np.asarray(reference, dtype="float64")
    idxs = list(band_indices) if band_indices is not None else list(range(1, src.count + 1))
    if len(ref) != len(idxs):
        raise ValueError(f"reference has {len(ref)} values but {len(idxs)} bands were selected")
    if max_values is not None and len(idxs) * src.height * src.width > max_values:
        raise ValueError("Cube too large for max_values limit; clip or pass max_values=None for streaming.")

    ref_norm = float(np.sqrt(np.sum(ref ** 2)))
    if ref_norm == 0.0 or not np.isfinite(ref_norm):
        return np.full((src.height, src.width), np.nan, dtype="float32")

    h, w = src.height, src.width
    out = np.full((h, w), np.nan, dtype="float32")

    for r0 in range(0, h, block_size):
        rh = min(block_size, h - r0)
        for c0 in range(0, w, block_size):
            cw = min(block_size, w - c0)
            win = Window(c0, r0, cw, rh)
            cube = src.read(indexes=idxs, window=win, masked=True).astype("float64").filled(np.nan)
            dot = np.nansum(cube * ref[:, None, None], axis=0)
            norm = np.sqrt(np.nansum(cube ** 2, axis=0)) * ref_norm
            with np.errstate(divide="ignore", invalid="ignore"):
                ang = np.arccos(np.clip(dot / norm, -1.0, 1.0))
            ang[~np.isfinite(cube).all(axis=0) | (norm == 0)] = np.nan
            out[r0 : r0 + rh, c0 : c0 + cw] = ang.astype("float32")

    return out
