import numpy as np
from .indices import compute_index


def vegetation_loss(before_src, after_src, bands, drop_threshold=0.2, veg_threshold=0.4):
    """Returns (stats dict, loss_mask uint8 [1=loss, 255=no data], ndvi_diff)."""
    if before_src.name == after_src.name:
        raise ValueError("Before and after are the same file. Vegetation loss needs two images from different dates.")
    d1 = before_src.tags().get("ACQUISITION_DATETIME")
    d2 = after_src.tags().get("ACQUISITION_DATETIME")
    if d1 and d2 and d1 == d2:
        raise ValueError("Both images have the same acquisition date. Loss needs two different dates.")
    # --- end new ---
    if (before_src.shape != after_src.shape or before_src.crs != after_src.crs
            or before_src.transform != after_src.transform):
        raise ValueError("The two images must have the same size, CRS and transform. Resample one first.")

    b = compute_index("ndvi", before_src, bands)
    a = compute_index("ndvi", after_src, bands)
    diff = a - b

    valid = np.isfinite(b) & np.isfinite(a)
    veg_before = valid & (b >= veg_threshold)
    loss = veg_before & (diff <= -drop_threshold)

    mask = np.zeros(b.shape, dtype="uint8")
    mask[loss] = 1
    mask[~valid] = 255

    veg_px, loss_px = int(veg_before.sum()), int(loss.sum())
    stats = {
        "vegetated_pixels_before": veg_px,
        "loss_pixels": loss_px,
        "loss_percent_of_vegetation": round(100 * loss_px / veg_px, 3) if veg_px else None,
        "drop_threshold": drop_threshold,
        "veg_threshold": veg_threshold,
    }
    crs = before_src.crs
    if crs.is_projected and str(crs.linear_units).lower() in ("metre", "meter"):
        px_area = abs(before_src.res[0] * before_src.res[1])  # square metres
        stats["pixel_area_m2"] = px_area
        stats["loss_area_hectares"] = round(loss_px * px_area / 10000, 3)
    else:
        stats["loss_area_hectares"] = None
        stats["area_note"] = "CRS is not in metres. Reproject before computing area."
    return stats, mask, diff