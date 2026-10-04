"""Structural checks of result.json. They apply to ANY result, whatever the question was."""
import math
from pathlib import Path

FILE_EXT = (".tif", ".tiff", ".png", ".geojson", ".json", ".gpkg")
RELATIVE = ("change", "increase", "decrease", "diff", "growth", "loss_rate")


def _leaves(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _leaves(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _leaves(v, f"{path}[{i}]")
    else:
        yield path, obj


def check_result(result, output_dir, artifacts, facts, final=True, expected_outputs=None):
    """Returns (errors, warnings). Errors go back to the debugger."""
    errors, warnings = [], []
    if not isinstance(result, dict):
        return ["result.json must be a JSON object"], warnings
    if not isinstance(result.get("summary"), str) or not result["summary"].strip():
        errors.append("result needs a non-empty 'summary' string")
    if final:
        if not isinstance(result.get("assumptions"), list):
            errors.append("the final result needs an 'assumptions' list (state what 'high', 'low', etc. meant)")
        if "thresholds" not in result:
            warnings.append("No 'thresholds' reported; cutoffs used are unknown.")
    have = {Path(a).name for a in artifacts}
    for name in expected_outputs or []:
        if name not in have:
            errors.append(f"expected output '{name}' was not created (created: {sorted(have)})")
    rasters = [f for f in facts["files"].values() if f.get("kind") == "raster"]
    metric = bool(rasters and rasters[0].get("crs_is_projected")
                  and str(rasters[0].get("resolution_units", "")).lower() in ("metre", "meter", "m"))
    for path, v in _leaves(result):
        low = path.lower()
        if isinstance(v, float) and not math.isfinite(v):
            errors.append(f"'{path}' is not a finite number")
        if isinstance(v, (int, float)) and not isinstance(v, bool) and "percent" in low:
            lo = -1e9 if any(w in low for w in RELATIVE) else -1e-6
            hi = 1e9 if any(w in low for w in RELATIVE) else 100 + 1e-6
            if not lo <= v <= hi:
                errors.append(f"'{path}' = {v} is not a valid percentage")
        if "hectare" in low and isinstance(v, (int, float)) and not metric:
            errors.append(f"'{path}' reports an area but the input CRS is not in metres")
        if isinstance(v, str) and v.lower().endswith(FILE_EXT) and "/workspace/prior/" not in v \
                and Path(v).name not in have:
            errors.append(f"'{path}' mentions file '{v}' which was not created by this task")
    return errors, warnings