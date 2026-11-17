import json
import numpy as np
import pytest
from pathlib import Path

from geollm_lib.raster import spatial_gradient, check_bimodality, local_adaptive_threshold


def test_spatial_gradient_flat_vs_edge():
    """Verify that flat background has zero gradient, while boundary edges have high gradient."""
    flat = np.full((100, 100), 10.0, dtype=np.float32)
    grad_flat = spatial_gradient(flat)
    assert np.allclose(grad_flat, 0.0, atol=1e-5), "Flat background must have zero gradient"

    step = np.zeros((100, 100), dtype=np.float32)
    step[:, 50:] = 100.0  # Sharp vertical edge at column 50
    grad_step = spatial_gradient(step)
    assert np.max(grad_step) > 50.0, "Sharp edge must have high gradient"
    assert np.all(grad_step[:, :45] == 0.0), "Interior flat area must have zero gradient"


def test_check_bimodality_unimodal_rejection():
    """Verify that unimodal distributions (sand, ocean, forest) are correctly rejected as bimodal."""
    # 1. Pure normal distribution
    unimodal_normal = np.random.normal(10, 2, 5000).astype(np.float32)
    diag_normal = check_bimodality(unimodal_normal)
    assert not diag_normal["is_bimodal"], "Unimodal Gaussian must NOT be flagged as bimodal"

    # 2. Pure uniform distribution
    unimodal_uniform = np.random.uniform(0, 10, 5000).astype(np.float32)
    diag_uniform = check_bimodality(unimodal_uniform)
    assert not diag_uniform["is_bimodal"], "Uniform distribution must NOT be flagged as bimodal"


def test_check_bimodality_bimodal_detection():
    """Verify that genuine two-class mixtures (water + land, fire + forest) are detected as bimodal."""
    # 1. Balanced mixture (50% water, 50% land)
    bimodal_balanced = np.concatenate([
        np.random.normal(-15, 1, 2500),
        np.random.normal(5, 1, 2500),
    ]).astype(np.float32)
    diag_bal = check_bimodality(bimodal_balanced)
    assert diag_bal["is_bimodal"], "Balanced two-class mixture must be detected as bimodal"
    assert diag_bal["peak_count"] >= 2

    # 2. Imbalanced mixture (5% river in 95% desert)
    bimodal_imbalanced = np.concatenate([
        np.random.normal(-15, 0.5, 250),
        np.random.normal(5, 1, 4750),
    ]).astype(np.float32)
    diag_imb = check_bimodality(bimodal_imbalanced)
    assert diag_imb["is_bimodal"], "5% river in 95% desert must be detected via Ashman's D >= 3.8"
    assert diag_imb["ashman_d"] >= 3.8


def test_local_adaptive_threshold_synthetic_scene():
    """Verify that local adaptive thresholding cleanly segments rivers without touching pure desert tiles."""
    img = np.random.normal(10, 1, (1024, 1024)).astype(np.float32)
    # Inject a 20-pixel wide river channel at row 500 with low backscatter (-15 dB)
    img[500:520, :] = np.random.normal(-15, 0.5, (20, 1024))

    mask, stats = local_adaptive_threshold(img, block_size=256, invert=True)

    # 8 tiles contain the river, 8 tiles are pure desert
    assert stats["bimodal_tiles"] == 8, f"Expected 8 bimodal tiles, got {stats['bimodal_tiles']}"
    assert stats["unimodal_tiles"] == 8, f"Expected 8 unimodal tiles, got {stats['unimodal_tiles']}"

    # Pure desert tiles must have exactly 0 candidate pixels
    desert_region = mask[:450, :]
    assert np.all(desert_region == 0), "Desert tiles must contain zero false-positive water pixels"

    # River region must have high detection rate
    river_pixels = np.sum(mask[500:520, :] == 1)
    assert river_pixels > 20000, f"Expected >20000 river detections, got {river_pixels}"

