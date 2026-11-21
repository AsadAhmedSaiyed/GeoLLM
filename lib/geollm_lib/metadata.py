"""Facts about the input files (what the LLM sees instead of pixels)."""
import math
import os
from pathlib import Path

import numpy as np
import rasterio
from rasterio.errors import RasterioIOError

from .bands import detect_sensor, infer_roles, label_role
from .hyperspectral import bad_band_mask, band_wavelengths

MAX_SAMPLED_BANDS = int(os.environ.get("GEOLLM_MAX_BAND_SAMPLES", "10"))

RASTER_EXT = {".tif", ".tiff"}
MULTIDIM_EXT = {".nc", ".h5", ".he5"}
ENVI_EXT = {".hdr", ".img", ".bsq", ".bil", ".bip"}
VECTOR_EXT = {".geojson", ".json", ".gpkg"}
POINT_CLOUD_EXT = {".las", ".laz", ".xyz"}


class GeoTiffError(Exception):
    """Raised when a file is not a usable GeoTIFF."""


def _safe(v):
    return "nan" if isinstance(v, float) and math.isnan(v) else v


def _band_sample(src, i):
    h, w = src.height, src.width
    step = max(1, max(h, w) // 256)
    arr = src.read(i, out_shape=(max(1, h // step), max(1, w // step)), masked=True)
    if arr.count() == 0:
        return {}
    return {"sample_min": float(arr.min()), "sample_max": float(arr.max()),
            "sample_mean": round(float(arr.mean()), 4)}


def _spectral_summary_from_src(src, tags):
    """Header-only wavelength summary across ALL bands (zero pixel reads)."""
    try:
        wl, unit_source = band_wavelengths(src, allow_missing=True)
    except Exception:
        return None
    finite = wl[np.isfinite(wl)]
    if finite.size == 0:
        return None
    sorted_wl = np.sort(finite)
    diffs = np.diff(sorted_wl)
    pos_diffs = diffs[diffs > 0]
    good = bad_band_mask(wl, tags=tags, exclude_water_vapor=True)
    return {
        "wavelength_count": int(finite.size),
        "total_bands": int(src.count),
        "min_nm": round(float(sorted_wl[0]), 2),
        "max_nm": round(float(sorted_wl[-1]), 2),
        "median_step_nm": round(float(np.median(pos_diffs)), 2) if pos_diffs.size else None,
        "unit_source": unit_source,
        "good_bands_excl_water_vapor": int(good.sum()),
        "flagged_bad_or_water_vapor_bands": int(src.count - good.sum()),
        "is_hyperspectral": bool(finite.size >= 15),
    }


def inspect_geotiff(path):
    path = Path(path)
    if not path.is_file():
        raise GeoTiffError(f"File not found: {path}")
    if path.suffix.lower() not in RASTER_EXT:
        raise GeoTiffError(f"Unsupported extension '{path.suffix}'")
    try:
        src = rasterio.open(path)
    except RasterioIOError as e:
        raise GeoTiffError(f"Cannot open as raster: {e}") from e
    with src:
        if src.crs is None:
            raise GeoTiffError("File has no CRS; it is not georeferenced.")
        tags = src.tags()
        sensor = detect_sensor(tags)
        labels = list(src.descriptions)
        bands = []
        for i in range(1, min(src.count, MAX_SAMPLED_BANDS) + 1):
            entry = {
                "index": i,
                "label": labels[i - 1],
                "role": label_role(labels[i - 1], sensor),
                "dtype": src.dtypes[i - 1],
                "nodata": _safe(src.nodatavals[i - 1]),
            }
            entry.update(_band_sample(src, i))
            bands.append(entry)

        spectral_summary = _spectral_summary_from_src(src, tags)
        metric = src.crs.is_projected and str(src.crs.linear_units).lower() in ("metre", "meter", "m")
        rx, ry = src.res
        info = {
            "kind": "raster", "format": "GeoTIFF", "width": src.width, "height": src.height,
            "band_count": src.count, "bands": bands,
            "bands_truncated": src.count > MAX_SAMPLED_BANDS,
            "band_roles": infer_roles(labels, tags),
            "sensor": sensor, "date": tags.get("ACQUISITION_DATETIME"),
            "crs": src.crs.to_string(), "crs_is_projected": src.crs.is_projected,
            "resolution": [rx, ry], "resolution_units": src.crs.linear_units if src.crs.is_projected else "degrees",
            "extent_km2": round(src.width * src.height * abs(rx * ry) / 1e6, 3) if metric else None,
            "bounds": list(src.bounds), "nodata": _safe(src.nodata), "tags": tags,
        }
        if spectral_summary:
            info["spectral_summary"] = spectral_summary
        return info


def inspect_multidim_raster(path):
    """Header-only inspection of NetCDF4 / HDF5 hyperspectral or gridded cubes (e.g. NASA EMIT, PRISMA)."""
    path = Path(path)
    ext = path.suffix.lower()
    out = {
        "kind": "multidim_raster",
        "format": ext.lstrip(".").upper(),
        "size_bytes": path.stat().st_size,
    }

    # 1. Try xarray (header/metadata only, no pixel reads)
    try:
        import xarray as xr
        with xr.open_dataset(path) as ds:
            out["dimensions"] = {k: int(v) for k, v in ds.sizes.items()}
            out["variables"] = {
                name: {"dims": list(var.dims), "shape": list(var.shape), "dtype": str(var.dtype)}
                for name, var in list(ds.data_vars.items())[:25]
            }
            out["coords"] = list(ds.coords.keys())[:25]
            # Detect wavelength coordinate if present
            for cname in ds.coords:
                if "wavelength" in str(cname).lower():
                    wl = np.asarray(ds.coords[cname].values, dtype="float64")
                    finite = wl[np.isfinite(wl)]
                    if finite.size:
                        scale = 1000.0 if float(np.nanmax(finite)) < 10.0 else 1.0
                        sorted_wl = np.sort(finite * scale)
                        out["spectral_summary"] = {
                            "wavelength_count": int(finite.size),
                            "min_nm": round(float(sorted_wl[0]), 2),
                            "max_nm": round(float(sorted_wl[-1]), 2),
                            "is_hyperspectral": bool(finite.size >= 15),
                        }
                    break
            return out
    except Exception:
        pass

    # 2. Try h5py for HDF5 / HE5 / NetCDF4 groups
    try:
        import h5py
        with h5py.File(path, "r") as hf:
            groups = []
            datasets = {}
            def _visit(name, obj):
                if len(datasets) >= 30:
                    return
                if isinstance(obj, h5py.Dataset):
                    datasets[name] = {"shape": list(obj.shape), "dtype": str(obj.dtype)}
                elif isinstance(obj, h5py.Group):
                    groups.append(name)
            hf.visititems(_visit)
            out["groups"] = groups[:20]
            out["datasets"] = datasets
            return out
    except Exception:
        pass

    # 3. Fallback: rasterio / GDAL subdatasets
    try:
        with rasterio.open(path) as src:
            out["driver"] = src.driver
            out["subdatasets"] = list(src.subdatasets)[:25]
            if src.count > 0:
                out["width"] = src.width
                out["height"] = src.height
                out["band_count"] = src.count
                out["crs"] = src.crs.to_string() if src.crs else None
            return out
    except Exception as e:
        out["note"] = f"Metadata inspection requires netCDF4/h5py inside the execution container ({e})"
        return out


def inspect_envi_raster(path):
    """Header-only inspection of ENVI hyperspectral files (.hdr, .img, .bsq, .bil, .bip)."""
    path = Path(path)
    out = {
        "kind": "raster",
        "format": "ENVI",
        "size_bytes": path.stat().st_size,
    }
    # Try opening via rasterio (GDAL ENVI driver)
    target = path
    if path.suffix.lower() == ".hdr":
        for cand_ext in ("", ".img", ".bsq", ".bil", ".bip", ".dat"):
            cand = path.with_suffix(cand_ext)
            if cand.is_file() and cand != path:
                target = cand
                break
    try:
        with rasterio.open(target) as src:
            tags = src.tags()
            out.update({
                "width": src.width,
                "height": src.height,
                "band_count": src.count,
                "crs": src.crs.to_string() if src.crs else None,
                "bounds": list(src.bounds) if src.crs else None,
            })
            ss = _spectral_summary_from_src(src, tags)
            if ss:
                out["spectral_summary"] = ss
            return out
    except Exception as e:
        out["note"] = f"ENVI header/data file; inspect with spectral.envi or rasterio in sandbox ({e})"
        return out


def inspect_vector(path):
    import geopandas as gpd
    gdf = gpd.read_file(str(path))
    return {"kind": "vector", "features": int(len(gdf)),
            "geometry_types": {k: int(v) for k, v in gdf.geom_type.value_counts().items()},
            "crs": gdf.crs.to_string() if gdf.crs else None,
            "columns": [c for c in gdf.columns if c != "geometry"],
            "bounds": [float(x) for x in gdf.total_bounds]}


def inspect_point_cloud(path):
    path = Path(path)
    ext = path.suffix.lower()
    if ext in (".las", ".laz"):
        try:
            import laspy
            with laspy.open(path) as fh:
                hdr = fh.header
                mins = [float(x) for x in hdr.mins]
                maxs = [float(x) for x in hdr.maxs]
                crs = hdr.parse_crs()
                return {
                    "kind": "point_cloud",
                    "format": ext.lstrip(".").upper(),
                    "point_count": int(hdr.point_count),
                    "bounds": [mins[0], mins[1], maxs[0], maxs[1]],
                    "z_range": [round(mins[2], 2), round(maxs[2], 2)],
                    "crs": str(crs) if crs else None,
                }
        except Exception as e:
            return {"kind": "point_cloud", "format": ext.lstrip(".").upper(), "size_bytes": path.stat().st_size, "note": str(e)}
    return {"kind": "point_cloud", "format": ext.lstrip(".").upper(), "size_bytes": path.stat().st_size}


def _alignment(files):
    rasters = {n: f for n, f in files.items() if f.get("kind") == "raster" and f.get("crs") and f.get("bounds")}
    dates = {n: f.get("date") for n, f in rasters.items()}
    if len(rasters) < 2:
        return {"rasters": len(rasters), "aligned": None, "differences": [], "dates": dates}
    names = list(rasters)
    ref, diffs = rasters[names[0]], []
    for n in names[1:]:
        f = rasters[n]
        if f["crs"] != ref["crs"]:
            diffs.append(f"{n}: CRS {f['crs']} vs {ref['crs']}")
        if f.get("resolution") != ref.get("resolution"):
            diffs.append(f"{n}: resolution {f.get('resolution')} vs {ref.get('resolution')}")
        if (f["width"], f["height"]) != (ref["width"], ref["height"]):
            diffs.append(f"{n}: size {f['width']}x{f['height']} vs {ref['width']}x{ref['height']}")
        if any(abs(a - b) > 1e-6 for a, b in zip(f["bounds"], ref["bounds"])):
            diffs.append(f"{n}: different bounds")
    return {"rasters": len(rasters), "aligned": not diffs, "differences": diffs, "dates": dates}


def inspect_dataset(paths):
    files = {}
    for p in map(Path, paths):
        ext = p.suffix.lower()
        try:
            if ext in RASTER_EXT:
                files[p.name] = inspect_geotiff(p)
            elif ext in MULTIDIM_EXT:
                files[p.name] = inspect_multidim_raster(p)
            elif ext in ENVI_EXT:
                files[p.name] = inspect_envi_raster(p)
            elif ext in VECTOR_EXT:
                files[p.name] = inspect_vector(p)
            elif ext in POINT_CLOUD_EXT:
                files[p.name] = inspect_point_cloud(p)
            else:
                files[p.name] = {"error": f"Unsupported file type '{ext}'"}
        except Exception as e:
            files[p.name] = {"error": str(e)}
    return {"files": files, "alignment": _alignment(files)}
