"""Checks that apply to ANY result, whatever the question was."""
import math
from pathlib import Path

import numpy as np
import rasterio

FILE_EXT = (".tif", ".tiff", ".png", ".geojson", ".json")


def _leaves(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _leaves(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _leaves(v, f"{path}[{i}]")
    else:
        yield path, obj


def check_result(result, run_dir, artifacts, facts):
    """Returns (errors, warnings). Errors go back to the LLM for a retry."""
    errors, warnings = [], []
    if not isinstance(result, dict):
        return ["result.json must be a JSON object"], warnings
    if not isinstance(result.get("summary"), str) or not result["summary"].strip():
        errors.append("result needs a non-empty 'summary' string")
    if not isinstance(result.get("assumptions"), list):
        errors.append("result needs an 'assumptions' list (state what 'high', 'low', etc. meant)")
    if "thresholds" not in result:
        warnings.append("No 'thresholds' reported; cutoffs used are unknown.")

    rasters = [f for f in facts["files"].values() if f.get("kind") == "raster"]
    primary = rasters[0] if rasters else None
    metric = bool(primary and primary.get("crs_is_projected")
                  and str(primary.get("resolution_units", "")).lower() in ("metre", "meter", "m"))
    have = {Path(a).name for a in artifacts}

    for path, v in _leaves(result):
        low = path.lower()
        if isinstance(v, float) and not math.isfinite(v):
            errors.append(f"'{path}' is not a finite number")
        if isinstance(v, (int, float)) and not isinstance(v, bool) and "percent" in low and not -1e-6 <= v <= 100 + 1e-6:
            errors.append(f"'{path}' = {v} is not a valid percentage (0-100)")
        if "hectare" in low and isinstance(v, (int, float)) and not metric:
            errors.append(f"'{path}' reports an area but the CRS is not in metres")
        if isinstance(v, str) and v.lower().endswith(FILE_EXT) and Path(v).name not in have:
            errors.append(f"'{path}' mentions file '{v}' which was not created")

    for a in artifacts:
        name = Path(a).name.lower()
        if not name.endswith((".tif", ".tiff")):
            continue
        try:
            with rasterio.open(Path(run_dir) / a) as src:
                if "mask" in name:
                    vals = set(np.unique(src.read(1)).tolist())
                    if not vals <= {0, 1, 255}:
                        errors.append(f"mask '{a}' has values other than 0/1/255: {sorted(vals)[:5]}")
                if primary and (src.width, src.height) != (primary["width"], primary["height"]):
                    warnings.append(f"'{a}' has a different size from the input ({src.width}x{src.height}).")
                if primary and src.crs and src.crs.to_string() != primary["crs"]:
                    warnings.append(f"'{a}' has a different CRS from the input ({src.crs.to_string()}).")
        except Exception as e:
            errors.append(f"output raster '{a}' cannot be opened: {e}")
    return errors, warnings