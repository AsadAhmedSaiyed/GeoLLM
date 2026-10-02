"""Change between two dates. Refuses fake comparisons."""
import numpy as np

from .align import same_grid
from .indices import compute_index


def _guard(before_src, after_src):
    if before_src.name == after_src.name:
        raise ValueError("Before and after are the same file. Change needs two images from different dates.")
    d1, d2 = before_src.tags().get("ACQUISITION_DATETIME"), after_src.tags().get("ACQUISITION_DATETIME")
    if d1 and d2 and d1 == d2:
        raise ValueError("Both images have the same acquisition date. Change needs two different dates.")
    if not same_grid(before_src, after_src):
        raise ValueError("Images are not on the same grid. Use geollm_lib.align.align_to(before_src, after_path) first.")


def index_difference(before_src, after_src, name="ndvi"):
    """Returns (before_index, after_index, after - before)."""
    _guard(before_src, after_src)
    b, a = compute_index(name, before_src), compute_index(name, after_src)
    return b, a, a - b


def significant_change(diff, direction="decrease", n_std=1.0, abs_threshold=None):
    """Mask of significant change. Default cutoff = n_std standard deviations of the difference.
    Returns (mask, cutoff). Report the cutoff as an assumption."""
    valid = np.isfinite(diff)
    cutoff = float(abs_threshold) if abs_threshold is not None else n_std * float(np.std(diff[valid]))
    mask = np.zeros(diff.shape, bool)
    mask[valid] = diff[valid] <= -cutoff if direction == "decrease" else diff[valid] >= cutoff
    return mask, cutoff