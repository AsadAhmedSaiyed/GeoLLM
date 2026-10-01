import numpy as np


def raster_stats(arr):
    valid = arr[np.isfinite(arr)]
    if valid.size == 0:
        return {"valid_pixels": 0, "nodata_pixels": int(arr.size)}
    p5, p25, p50, p75, p95 = np.percentile(valid, [5, 25, 50, 75, 95])
    return {
        "valid_pixels": int(valid.size),
        "nodata_pixels": int(arr.size - valid.size),
        "min": float(valid.min()), "max": float(valid.max()),
        "mean": float(valid.mean()), "std": float(valid.std()),
        "p5": float(p5), "p25": float(p25), "median": float(p50),
        "p75": float(p75), "p95": float(p95),
    }