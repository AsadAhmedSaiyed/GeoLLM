"""Deterministic checks on task outputs. Exit code 0 does not mean the result is right."""
import json
from pathlib import Path

import numpy as np
import rasterio
from matplotlib import image as mpimg

BOUNDED = ("ndvi", "ndmi", "nbr", "ndwi", "mndwi", "ndbi")
LOOSE = ("evi", "savi")


def _issue(sev, code, art, msg):
    return {"severity": sev, "code": code, "artifact": art, "message": msg}


def _confirmed(obj, key):
    if isinstance(obj, dict):
        return obj.get(key) is True or any(_confirmed(v, key) for v in obj.values())
    if isinstance(obj, list):
        return any(_confirmed(v, key) for v in obj)
    return False


def _numbers(obj, key):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key and isinstance(v, (int, float)) and not isinstance(v, bool):
                yield v
            yield from _numbers(v, key)
    elif isinstance(obj, list):
        for v in obj:
            yield from _numbers(v, key)


def image_stats(path):
    """Size and how much of the image is one single colour."""
    a = mpimg.imread(str(path))
    h, w = a.shape[:2]
    s = max(1, max(h, w) // 800)
    a = a[::s, ::s]
    rgb = (a[..., :3] if a.ndim == 3 else np.stack([a] * 3, -1))
    q = (np.clip(rgb, 0, 1) * 255).astype(int) // 8
    codes = (q[..., 0] << 10) + (q[..., 1] << 5) + q[..., 2]
    return {"width": int(w), "height": int(h), "dominant_color_fraction": round(float(np.bincount(codes.ravel()).max() / codes.size), 4)}


def _read_small(src, max_px=2048):
    f = max(1, max(src.height, src.width) // max_px)
    return src.read(1, out_shape=(max(1, src.height // f), max(1, src.width // f)), masked=True)


def check_outputs(output_dir, artifacts, result, facts):
    """Returns a list of issues {severity: error|warning, code, artifact, message}."""
    out, root = [], Path(output_dir)
    rasters = [f for f in facts["files"].values() if f.get("kind") == "raster"]
    primary = rasters[0] if rasters else None
    masks = []
    for rel in artifacts:
        p, name = root / rel, Path(rel).name.lower()
        try:
            if name.endswith((".tif", ".tiff")):
                with rasterio.open(p) as src:
                    arr = _read_small(src)
                    if src.crs is None:
                        out.append(_issue("warning", "no_crs", rel, f"'{rel}' has no CRS"))
                    elif primary and src.crs.to_string() != primary["crs"]:
                        out.append(_issue("warning", "crs_differs", rel, f"'{rel}' CRS {src.crs.to_string()} differs from the input {primary['crs']}"))
                    if primary and (src.width, src.height) != (primary["width"], primary["height"]):
                        out.append(_issue("warning", "shape_differs", rel, f"'{rel}' is {src.width}x{src.height}, input is {primary['width']}x{primary['height']}"))
                vals = np.ma.filled(arr, 255 if arr.dtype.kind in "ui" else np.nan)
                is_mask = arr.dtype.kind in "uib" and (set(np.unique(vals).tolist()) <= {0, 1, 255} or "mask" in name)
                if is_mask:
                    valid, sel = int((vals != 255).sum()), int((vals == 1).sum())
                    if valid == 0:
                        out.append(_issue("error", "mask_no_valid", rel, f"mask '{rel}' has no valid pixels"))
                    elif sel == 0:
                        out.append(_issue("warning" if _confirmed(result, "empty_result_confirmed") else "error", "mask_empty", rel,
                                          f"mask '{rel}' selects zero pixels. If that is the genuine answer, set 'empty_result_confirmed': true in the result and explain why; otherwise check the thresholds/logic."))
                    elif sel == valid:
                        out.append(_issue("warning" if _confirmed(result, "full_coverage_confirmed") else "error", "mask_full", rel,
                                          f"mask '{rel}' selects every valid pixel. If genuine, set 'full_coverage_confirmed': true and explain; otherwise check the thresholds/logic."))
                    masks.append((rel, sel))
                else:
                    a = np.ma.filled(arr.astype("float32"), np.nan)
                    fin = np.isfinite(a)
                    frac_nan = 1 - fin.mean()
                    if not fin.any():
                        out.append(_issue("error", "all_nan", rel, f"'{rel}' contains no valid values (all NaN/nodata)"))
                        continue
                    if frac_nan > 0.9:
                        out.append(_issue("warning", "mostly_nan", rel, f"'{rel}' is {frac_nan:.0%} NaN/nodata"))
                    lo, hi = float(a[fin].min()), float(a[fin].max())
                    if lo == hi:
                        out.append(_issue("warning" if lo != 0 else "error", "constant", rel, f"'{rel}' is constant ({lo})"))
                    if any(t in name for t in BOUNDED) and (lo < -1.05 or hi > 1.05):
                        out.append(_issue("error", "index_range", rel, f"'{rel}' range [{lo:.3f}, {hi:.3f}] is outside [-1, 1] for a normalized index"))
                    elif any(t in name for t in LOOSE) and (lo < -5 or hi > 5):
                        out.append(_issue("warning", "index_range", rel, f"'{rel}' range [{lo:.2f}, {hi:.2f}] looks implausible"))
                    if "db" in name and (lo < -80 or hi > 40):
                        out.append(_issue("error", "db_range", rel, f"'{rel}' range [{lo:.1f}, {hi:.1f}] dB is implausible for backscatter"))
            elif name.endswith(".geojson"):
                d = json.loads(p.read_text())
                if not d.get("features"):
                    out.append(_issue("warning" if _confirmed(result, "empty_result_confirmed") else "error", "vector_empty", rel,
                                      f"'{rel}' has no features. If genuine, set 'empty_result_confirmed': true and explain."))
            elif name.endswith(".png"):
                st = image_stats(p)
                if st["dominant_color_fraction"] > 0.995:
                    out.append(_issue("warning", "image_uniform", rel, f"image '{rel}' is {st['dominant_color_fraction']:.1%} one colour (blank or uninformative?)"))
        except Exception as e:
            out.append(_issue("error", "unreadable", rel, f"cannot read output '{rel}': {e}"))
    if len(masks) == 1:
        claimed = list(_numbers(result, "selected_pixels"))
        if claimed and abs(claimed[0] - masks[0][1]) > max(1, 0.02 * masks[0][1]):
            out.append(_issue("warning", "count_mismatch", masks[0][0],
                              f"result says selected_pixels={claimed[0]} but mask '{masks[0][0]}' (sampled) has about {masks[0][1]}"))
    return out