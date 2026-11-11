"""Unit tests for Autonomous STAC Discovery, Preview, and 100% Native-Resolution Staging."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds
from rasterio.warp import transform_bounds

from harness.stac_service import _sync_stage_cog_window_native


def _create_synthetic_cog(path: Path, width: int = 400, height: int = 400) -> tuple[float, float]:
    """Create a synthetic UTM GeoTIFF with exact 10m native pixel resolution."""
    # 400 x 400 pixels at 10.0m resolution -> 4000m x 4000m
    west, south, east, north = 500000.0, 3300000.0, 504000.0, 3304000.0
    transform = from_bounds(west, south, east, north, width, height)
    data = np.arange(width * height, dtype=np.uint16).reshape((height, width)) % 10000

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="uint16",
        crs="EPSG:32638",
        transform=transform,
        nodata=0,
    ) as dst:
        dst.write(data, 1)

    return abs(transform.a), abs(transform.e)


def test_native_resolution_preserved_exact(tmp_path: Path):
    """Verify _sync_stage_cog_window_native preserves 100% original pixel resolution, CRS, and dtype."""
    src_tif = tmp_path / "source_native_10m.tif"
    orig_res_x, orig_res_y = _create_synthetic_cog(src_tif, width=400, height=400)
    assert orig_res_x == pytest.approx(10.0)
    assert orig_res_y == pytest.approx(10.0)

    wgs84_bbox = list(
        transform_bounds("EPSG:32638", "EPSG:4326", 501000.0, 3301000.0, 503000.0, 3303000.0)
    )

    out_tif = tmp_path / "staged_native.tif"
    meta = _sync_stage_cog_window_native(
        signed_href=str(src_tif),
        dest_path=out_tif,
        bbox_wgs84=wgs84_bbox,
        max_native_pixels=36_000_000,
    )

    assert meta["ok"] is True
    assert out_tif.exists()
    assert meta["native_resolution"] == [10.0, 10.0]

    with rasterio.open(out_tif) as staged:
        # Resolution must remain 100% identical (10.0m x 10.0m)
        assert abs(staged.transform.a) == pytest.approx(orig_res_x, rel=1e-6)
        assert abs(staged.transform.e) == pytest.approx(orig_res_y, rel=1e-6)
        assert str(staged.crs) == "EPSG:32638"
        assert staged.dtypes[0] == "uint16"
        assert staged.nodata == 0
        # 2000m / 10m = ~200 pixels on each side
        assert 195 <= staged.width <= 205
        assert 195 <= staged.height <= 205


def test_native_resolution_memory_guard_blocks_oversized_aoi(tmp_path: Path):
    """Verify oversized AOI returns memory_limit_exceeded instead of silently downscaling."""
    src_tif = tmp_path / "source_native_10m.tif"
    _create_synthetic_cog(src_tif, width=400, height=400)

    wgs84_bbox = list(
        transform_bounds("EPSG:32638", "EPSG:4326", 500000.0, 3300000.0, 504000.0, 3304000.0)
    )

    out_tif = tmp_path / "should_not_exist.tif"
    # Set max_native_pixels to 10,000 so a 400x400 (160,000 px) window exceeds the limit
    res = _sync_stage_cog_window_native(
        signed_href=str(src_tif),
        dest_path=out_tif,
        bbox_wgs84=wgs84_bbox,
        max_native_pixels=10_000,
    )
    assert res["ok"] is False
    assert res.get("memory_limit_exceeded") is True
    assert "safe container memory limit" in res.get("error", "")
    assert not out_tif.exists()


def test_stac_tool_cli_propose_preview(tmp_path: Path):
    """Verify stac_tool_cli.py propose_preview writes stac_preview.json with native grid estimate."""
    req_payload = {
        "bbox": [47.75, 30.45, 47.85, 30.55],
        "location_name": "Basra, Iraq",
        "explanation": "Selected cloud-free Sentinel-2 scenes for May 2020 and May 2025.",
        "scenes": [
            {
                "item_id": "S2A_MSIL2A_20200512",
                "collection": "sentinel-2-l2a",
                "datetime": "2020-05-12T07:36:21Z",
                "cloud_cover": 1.2,
                "aoi_coverage_pct": 100.0,
                "thumbnail": "https://example.com/thumb1.png",
                "assets": ["B04", "B08", "SCL"],
                "label": "May 2020 Baseline",
            },
            {
                "item_id": "S2B_MSIL2A_20250515",
                "collection": "sentinel-2-l2a",
                "datetime": "2025-05-15T07:36:19Z",
                "cloud_cover": 0.5,
                "aoi_coverage_pct": 100.0,
                "thumbnail": "https://example.com/thumb2.png",
                "assets": ["B04", "B08", "SCL"],
                "label": "May 2025 Comparison",
            },
        ],
    }

    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["SYSTEMROOT"] = os.environ.get("SystemRoot", "C:\\WINDOWS")
    env["SystemRoot"] = env["SYSTEMROOT"]
    env["GEOLLM_RUN_DIR"] = str(tmp_path)

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "harness.stac_tool_cli",
            "propose_preview",
        ],
        input=json.dumps(req_payload),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    resp = json.loads(proc.stdout)
    assert resp["ok"] is True

    preview_file = tmp_path / "stac_preview.json"
    assert preview_file.exists()
    saved = json.loads(preview_file.read_text(encoding="utf-8"))
    assert saved["location_name"] == "Basra, Iraq"
    assert len(saved["scenes"]) == 2
    assert saved["scenes"][0]["label"] == "May 2020 Baseline"
    # Verify full scientific band suite is automatically enriched
    for req_b in ["B02", "B03", "B04", "B08", "B11", "B12", "SCL"]:
        assert req_b in saved["scenes"][0]["assets"]
    assert saved["native_grid_estimate"]["within_memory_limit"] is True
    assert saved["native_grid_estimate"]["native_resolution_m"] == 10.0


def test_stac_propose_preview_rejects_half_coverage(tmp_path: Path):
    """Verify propose_preview rejects a single scene covering < 50% of the AOI bbox."""
    req_payload = {
        "bbox": [34.20, 31.20, 34.55, 31.60],
        "location_name": "Gaza Strip",
        "explanation": "Partial coverage test",
        "scenes": [
            {
                "item_id": "S2A_PARTIAL_2020",
                "collection": "sentinel-2-l2a",
                "datetime": "2020-05-25T08:16:00Z",
                "cloud_cover": 0.0,
                "aoi_coverage_pct": 32.5,
                "thumbnail": "https://example.com/thumb.png",
                "assets": ["B04", "B08"],
            }
        ],
    }
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["SYSTEMROOT"] = os.environ.get("SystemRoot", "C:\\WINDOWS")
    env["SystemRoot"] = env["SYSTEMROOT"]
    env["GEOLLM_RUN_DIR"] = str(tmp_path)
    proc = subprocess.run(
        [sys.executable, "-m", "harness.stac_tool_cli", "propose_preview"],
        input=json.dumps(req_payload),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    resp = json.loads(proc.stdout)
    assert resp["ok"] is False
    assert "Insufficient AOI coverage" in resp["error"]


def test_timeline_json_copies_tmp_frames_to_output(tmp_path: Path):
    """Verify make_timeline_json copies frame PNGs from /tmp into /workspace/output so they never 404."""
    from PIL import Image
    from geollm_lib.viz_ts import make_timeline_json

    tmp_frames_dir = tmp_path / "tmp_frames"
    out_dir = tmp_path / "outputs"
    tmp_frames_dir.mkdir()
    out_dir.mkdir()

    frame_paths = []
    dates = ["2020-05-25", "2022-05-30", "2024-05-24", "2026-05-24"]
    for d in dates:
        fp = tmp_frames_dir / f"frame_{d[:4]}.png"
        Image.new("RGB", (64, 64), color=(20, 120, 60)).save(fp)
        frame_paths.append(str(fp))

    tl_path = make_timeline_json(
        dates=dates,
        frame_files=frame_paths,
        series_values=[100.0, 95.0, 60.0, 52.0],
        metric_name="Green Area",
        unit="ha",
        out_path=str(out_dir / "timeline.json"),
    )
    assert Path(tl_path).exists()
    for d in dates:
        copied = out_dir / f"frame_{d[:4]}.png"
        assert copied.exists(), f"Expected {copied} to be persisted in outputs/"


def test_scientific_indices_and_s2_boa_offset_harmonization():
    """Verify Sentinel-2 BOA_ADD_OFFSET (-1000) harmonization and scientific indices (msavi2, ibi, bsi, ui)."""
    from geollm_lib.indices import INDEX_DEFS, to_surface_reflectance

    # Pre-2022 Sentinel-2 DN (red=1000 -> 0.10, nir=4000 -> 0.40)
    raw_2020_red = np.full((4, 4), 1000.0, dtype="float32")
    raw_2020_nir = np.full((4, 4), 4000.0, dtype="float32")
    # Post-2022 Baseline 04.00+ DN has +1000 offset (red=2000 -> 0.10, nir=5000 -> 0.40)
    raw_2026_red = np.full((4, 4), 2000.0, dtype="float32")
    raw_2026_nir = np.full((4, 4), 5000.0, dtype="float32")

    r_2020 = to_surface_reflectance(raw_2020_red, tags={"collection": "sentinel-2-l2a", "acquisition_date": "2020-05-25"})
    n_2020 = to_surface_reflectance(raw_2020_nir, tags={"collection": "sentinel-2-l2a", "acquisition_date": "2020-05-25"})
    r_2026 = to_surface_reflectance(raw_2026_red, tags={"collection": "sentinel-2-l2a", "acquisition_date": "2026-05-24", "BOA_ADD_OFFSET": "-1000"})
    n_2026 = to_surface_reflectance(raw_2026_nir, tags={"collection": "sentinel-2-l2a", "acquisition_date": "2026-05-24", "BOA_ADD_OFFSET": "-1000"})

    assert np.allclose(r_2020, r_2026, atol=1e-5)
    assert np.allclose(n_2020, n_2026, atol=1e-5)

    for idx_name in ("msavi2", "ibi", "bsi", "ui"):
        assert idx_name in INDEX_DEFS
        roles, _, fn = INDEX_DEFS[idx_name]
        sample_bands = {
            "blue": np.full((4, 4), 0.08, dtype="float32"),
            "green": np.full((4, 4), 0.12, dtype="float32"),
            "red": np.full((4, 4), 0.15, dtype="float32"),
            "nir": np.full((4, 4), 0.35, dtype="float32"),
            "swir1": np.full((4, 4), 0.28, dtype="float32"),
            "swir2": np.full((4, 4), 0.22, dtype="float32"),
        }
        out = fn({k: sample_bands[k] for k in roles})
        assert out.shape == (4, 4)
        assert np.isfinite(out).all()

