"""Unit tests for Phase 1 Validation Upgrade: Quality Gate & GeoTIFF Backend."""
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from PIL import Image

from harness.validation import (
    ValidationConfig,
    compute_mutual_valid_mask,
    evaluate_quality_gate,
    extract_png_crop,
    extract_raster_crop,
    generate_side_by_side_comparison,
    inspect_raster_quality,
    render_crop_to_rgb,
)


def _create_synthetic_geotiff(
    path: Path,
    data: np.ndarray,
    crs: str = "EPSG:32643",
    nodata: float = 0.0,
    descriptions: list[str] | None = None,
):
    """Helper to write synthetic multi-band or single-band GeoTIFF."""
    if data.ndim == 2:
        data = data[np.newaxis, ...]
    count, height, width = data.shape
    transform = from_origin(500000.0, 2000000.0, 10.0, 10.0)

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=count,
        dtype=str(data.dtype),
        crs=crs,
        transform=transform,
        nodata=nodata,
    ) as dst:
        dst.write(data)
        if descriptions:
            for idx, desc in enumerate(descriptions, start=1):
                if idx <= count:
                    dst.set_band_description(idx, desc)


def test_inspect_clean_geotiff(tmp_path):
    """A clean raster without nodata or clouds must pass with verdict='valid'."""
    p = tmp_path / "clean.tif"
    arr = np.ones((1, 50, 50), dtype="float32") * 0.45
    _create_synthetic_geotiff(p, arr, nodata=np.nan)

    report = inspect_raster_quality(p)
    assert report.is_usable is True
    assert report.verdict == "valid"
    assert report.nodata_fraction == 0.0
    assert report.cloud_fraction == 0.0
    assert report.width == 50
    assert report.height == 50
    assert report.is_projected is True


def test_inspect_excessive_nodata(tmp_path):
    """A raster with >60% nodata must be flagged as 'insufficient_data'."""
    p = tmp_path / "mostly_nodata.tif"
    arr = np.full((1, 100, 100), np.nan, dtype="float32")
    arr[0, :25, :25] = 0.5  # Only 6.25% valid data
    _create_synthetic_geotiff(p, arr, nodata=np.nan)

    report = inspect_raster_quality(p)
    assert report.is_usable is False
    assert report.verdict == "insufficient_data"
    assert report.nodata_fraction > 0.90
    assert any("Excessive nodata" in iss for iss in report.issues)


def test_cloud_detection_scl_band(tmp_path):
    """When a Scene Classification Layer (SCL) is present, clouds must be detected."""
    p = tmp_path / "sentinel_scl.tif"
    # Band 1: NDVI (float32), Band 2: SCL (uint8)
    ndvi = np.full((50, 50), 0.6, dtype="float32")
    scl = np.full((50, 50), 4, dtype="uint8")  # Class 4 = Vegetation
    scl[:20, :50] = 9  # Class 9 = Cloud High Probability (40% cloud cover)

    stack = np.stack([ndvi.astype("float32"), scl.astype("float32")])
    _create_synthetic_geotiff(p, stack, descriptions=["NDVI", "SCL"])

    report = inspect_raster_quality(p)
    assert report.cloud_detection_method == "scl"
    assert np.isclose(report.cloud_fraction, 0.40, atol=0.05)


def test_spectral_cloud_vs_salt_flat(tmp_path):
    """Spectral heuristics must separate clouds (high optical + high SWIR) from salt flats (high optical + low SWIR)."""
    cfg = ValidationConfig()

    # Cloud scene: high Blue, Green, Red (0.6), high SWIR (0.4)
    p_cloud = tmp_path / "cloud_scene.tif"
    data_cloud = np.stack([
        np.full((30, 30), 0.60, dtype="float32"),  # Blue
        np.full((30, 30), 0.60, dtype="float32"),  # Green
        np.full((30, 30), 0.60, dtype="float32"),  # Red
        np.full((30, 30), 0.40, dtype="float32"),  # SWIR
    ])
    _create_synthetic_geotiff(p_cloud, data_cloud, descriptions=["Blue", "Green", "Red", "SWIR"])

    rep_cloud = inspect_raster_quality(p_cloud, cfg)
    assert rep_cloud.cloud_detection_method == "spectral_heuristic"
    assert rep_cloud.cloud_fraction > 0.80

    # Salt flat scene: high Blue, Green, Red (0.65), but low SWIR (0.05 due to mineral absorption)
    p_salt = tmp_path / "salt_flat.tif"
    data_salt = np.stack([
        np.full((30, 30), 0.65, dtype="float32"),  # Blue
        np.full((30, 30), 0.65, dtype="float32"),  # Green
        np.full((30, 30), 0.65, dtype="float32"),  # Red
        np.full((30, 30), 0.05, dtype="float32"),  # SWIR (low!)
    ])
    _create_synthetic_geotiff(p_salt, data_salt, descriptions=["Blue", "Green", "Red", "SWIR"])

    rep_salt = inspect_raster_quality(p_salt, cfg)
    assert rep_salt.cloud_detection_method == "spectral_heuristic"
    assert rep_salt.cloud_fraction < 0.10  # Correctly recognized as non-cloud!


def test_compute_mutual_valid_mask(tmp_path):
    """Multi-date intersection must accurately compute the mutual valid area."""
    p1 = tmp_path / "date1.tif"
    p2 = tmp_path / "date2.tif"

    # Date 1 has nodata on the left half
    d1 = np.ones((40, 40), dtype="float32") * 0.5
    d1[:, :20] = np.nan
    _create_synthetic_geotiff(p1, d1, nodata=np.nan)

    # Date 2 has nodata on the top half
    d2 = np.ones((40, 40), dtype="float32") * 0.5
    d2[:20, :] = np.nan
    _create_synthetic_geotiff(p2, d2, nodata=np.nan)

    res = compute_mutual_valid_mask([p1, p2])
    assert res.is_sufficient is True
    assert res.verdict == "valid"
    # Only bottom-right quadrant is valid in both (25% overlap)
    assert np.isclose(res.mutual_valid_fraction, 0.25, atol=0.05)
    assert res.valid_intersection_mask[30, 30] == True   # Bottom right: valid
    assert res.valid_intersection_mask[10, 10] == False  # Top left: invalid
    assert res.valid_intersection_mask[10, 30] == False  # Top right: invalid in d2
    assert res.valid_intersection_mask[30, 10] == False  # Bottom left: invalid in d1


def test_evaluate_quality_gate(tmp_path):
    """Quality gate must approve clean inputs and reject poor inputs with clear reasons."""
    p_good = tmp_path / "good.tif"
    _create_synthetic_geotiff(p_good, np.ones((30, 30), dtype="float32") * 0.3)

    gate_ok = evaluate_quality_gate([p_good])
    assert gate_ok.is_approved is True
    assert gate_ok.verdict == "valid"

    p_bad = tmp_path / "bad.tif"
    _create_synthetic_geotiff(p_bad, np.full((30, 30), np.nan, dtype="float32"), nodata=np.nan)

    gate_bad = evaluate_quality_gate([p_bad])
    assert gate_bad.is_approved is False
    assert gate_bad.verdict == "insufficient_data"


def test_input_gate_blocks_all_nodata_raster(tmp_path):
    """An all-nodata GeoTIFF must block the gate (return None) and emit
    vision_input_gate + vision_insufficient_data with zero model calls."""
    from harness.validation.input_gate import run_input_gate

    p = tmp_path / "nodata.tif"
    _create_synthetic_geotiff(p, np.zeros((30, 30), dtype="float32"), nodata=0.0)

    events = []
    result = run_input_gate([str(p)], on_step=events.append)

    assert result is None
    types = [e["type"] for e in events]
    assert "vision_input_gate" in types
    assert "vision_insufficient_data" in types
    ins = [e for e in events if e["type"] == "vision_insufficient_data"][0]
    assert ins["area_verified_pct"] == 0.0
    assert ins["raster_count"] == 1
    assert ins["files"][0]["nodata_pct"] == 100.0
    assert any("nodata" in i.lower() for i in ins["files"][0]["issues"])
    stopped = [e for e in events if e["type"] == "vision_stopped"]
    assert stopped and stopped[0]["reason"] == "insufficient_data"


def test_input_gate_approves_clean_raster(tmp_path):
    """A clean GeoTIFF must pass the gate and return a QualityGateResult."""
    from harness.validation.input_gate import run_input_gate

    p = tmp_path / "good.tif"
    _create_synthetic_geotiff(p, np.ones((30, 30), dtype="float32") * 0.3)

    events = []
    result = run_input_gate([str(p)], on_step=events.append)

    assert result is not None
    assert result.is_approved is True
    assert result.verdict == "valid"
    types = [e["type"] for e in events]
    assert types.count("vision_input_gate") == 2  # started + done
    assert "vision_insufficient_data" not in types


def test_input_gate_ignores_non_raster_inputs(tmp_path):
    """PNG/map outputs are not rasters — the gate must not block on them."""
    from harness.validation.input_gate import run_input_gate

    png = tmp_path / "map.png"
    Image.new("RGB", (64, 64), color=(100, 150, 200)).save(str(png))

    events = []
    result = run_input_gate([str(png)], on_step=events.append)

    # No rasters → evaluate_quality_gate returns not_valid (no rasters), which
    # is NOT "insufficient_data", so the gate does not block.
    assert result is not None
    assert "vision_insufficient_data" not in [e["type"] for e in events]


def test_extract_crop_and_side_by_side(tmp_path):
    """Crop extraction and side-by-side comparison rendering must generate correct outputs."""
    p_input = tmp_path / "input.tif"
    p_output = tmp_path / "output_mask.tif"
    p_png = tmp_path / "map.png"
    p_comp = tmp_path / "comparison.png"

    # Multi-band input
    input_data = np.random.randint(100, 3000, size=(3, 100, 100), dtype="uint16")
    _create_synthetic_geotiff(p_input, input_data)

    # Binary mask output
    mask_data = np.zeros((1, 100, 100), dtype="uint8")
    mask_data[0, 20:60, 20:60] = 1
    _create_synthetic_geotiff(p_output, mask_data)

    # Synthetic map PNG
    img = Image.new("RGB", (200, 200), color=(100, 150, 200))
    img.save(p_png)

    # Normalized crop (0.2 to 0.6)
    crop = extract_raster_crop(p_input, bbox_norm=(0.2, 0.2, 0.6, 0.6))
    assert crop.array.shape[1] == 40
    assert crop.array.shape[2] == 40

    # Side-by-side multi-panel comparison generator
    out_file = generate_side_by_side_comparison(
        input_raster_path=p_input,
        output_raster_path=p_output,
        png_map_path=p_png,
        bbox_norm=(0.2, 0.2, 0.6, 0.6),
        out_path=p_comp,
    )

    assert out_file.is_file()
    assert out_file.stat().st_size > 500  # Valid rendered PNG

