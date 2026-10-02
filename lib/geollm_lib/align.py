"""Put rasters on a common grid. GDAL command-line tools are exposed only through
validated wrappers (fixed argument lists, whitelisted options, restricted folders)."""
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import Resampling, reproject

RESAMPLING = {"nearest": Resampling.nearest, "bilinear": Resampling.bilinear,
              "cubic": Resampling.cubic, "average": Resampling.average}
GDAL_RESAMPLING = {"nearest", "bilinear", "cubic", "average", "mode"}


def same_grid(a, b):
    """True if two open rasters share CRS, size and transform."""
    return (a.crs == b.crs and a.shape == b.shape
            and np.allclose(tuple(a.transform)[:6], tuple(b.transform)[:6], atol=1e-6))


def align_to(ref, other_path, out_path=None, resampling="bilinear"):
    """Resample/reproject `other_path` onto the grid of the open raster `ref`. Returns the new file path.
    Use resampling='nearest' for categorical data."""
    if resampling not in RESAMPLING:
        raise ValueError(f"resampling must be one of {sorted(RESAMPLING)}")
    out = Path(out_path) if out_path else Path(tempfile.gettempdir()) / f"aligned_{Path(other_path).stem}.tif"
    with rasterio.open(other_path) as src:
        if src.crs is None:
            raise ValueError("The file has no CRS, so it cannot be aligned.")
        profile = src.profile.copy()
        for k in ("blockxsize", "blockysize", "tiled"):
            profile.pop(k, None)
        profile.update(driver="GTiff", crs=ref.crs, transform=ref.transform,
                       width=ref.width, height=ref.height, compress="deflate")
        with rasterio.open(out, "w", **profile) as dst:
            for i in range(1, src.count + 1):
                reproject(source=rasterio.band(src, i), destination=rasterio.band(dst, i),
                          src_transform=src.transform, src_crs=src.crs,
                          dst_transform=ref.transform, dst_crs=ref.crs,
                          resampling=RESAMPLING[resampling], src_nodata=src.nodata, dst_nodata=src.nodata)
            for i, d in enumerate(src.descriptions, start=1):
                if d:
                    dst.set_band_description(i, d)
            dst.update_tags(**src.tags())
    return str(out)


def _check_path(p):
    roots = os.environ.get("GEOLLM_ROOTS", os.pathsep.join(["/workspace", "/tmp"])).split(os.pathsep)
    rp = Path(p).resolve()
    if not any(rp == Path(r).resolve() or Path(r).resolve() in rp.parents for r in roots):
        raise ValueError(f"Path {p} is outside the allowed folders")
    return str(rp)


def _run(args):
    r = subprocess.run(args, capture_output=True, text=True, timeout=300, shell=False)
    if r.returncode != 0:
        raise RuntimeError(f"{args[0]} failed: {r.stderr.strip()[-500:]}")
    return r.stdout


def gdal_info(path):
    """Metadata from `gdalinfo -json`."""
    return json.loads(_run(["gdalinfo", "-json", _check_path(path)]))


def gdal_warp(sources, dst_path, crs=None, resolution=None, resampling="bilinear"):
    """Reproject/resample with gdalwarp. Several sources are mosaicked together."""
    if isinstance(sources, str):
        sources = [sources]
    if resampling not in GDAL_RESAMPLING:
        raise ValueError(f"resampling must be one of {sorted(GDAL_RESAMPLING)}")
    args = ["gdalwarp", "-overwrite", "-r", resampling]
    if crs:
        if not re.fullmatch(r"EPSG:\d{3,6}", str(crs)):
            raise ValueError("crs must look like 'EPSG:32633'")
        args += ["-t_srs", crs]
    if resolution:
        res = float(resolution)
        if res <= 0:
            raise ValueError("resolution must be positive")
        args += ["-tr", str(res), str(res)]
    args += [_check_path(s) for s in sources] + [_check_path(dst_path)]
    _run(args)
    return str(dst_path)


def gdal_mosaic(sources, dst_path, resampling="nearest"):
    return gdal_warp(sources, dst_path, resampling=resampling)