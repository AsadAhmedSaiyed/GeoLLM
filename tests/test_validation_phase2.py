"""Phase 2 tests — Tool Registry & Pixel Execution Backend.

Covers all 7 tools (make_grid, crop, get_stats, get_source_info,
mark_result, report_insufficient_data, finish) and the dispatch_tool
dispatcher.  All tests are fully offline — no LLM calls, no network.
Synthetic GeoTIFFs and PNGs are generated in pytest's tmp_path.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from PIL import Image
from rasterio.crs import CRS
from rasterio.transform import from_bounds

from harness.validation.config import get_validation_config
from harness.validation.tools import (
    InspectionSession,
    dispatch_tool,
    finish,
    get_source_info,
    get_stats,
    make_grid,
    mark_result,
    report_insufficient_data,
    crop,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_geotiff(path: Path, width: int = 64, height: int = 64) -> Path:
    """Write a synthetic single-band uint8 GeoTIFF with known class pattern.

    Top-left quadrant (rows 0..31, cols 0..31) is class 1.
    Everything else is class 0.
    """
    data = np.zeros((1, height, width), dtype=np.uint8)
    data[0, : height // 2, : width // 2] = 1
    transform = from_bounds(0.0, 0.0, 1.0, 1.0, width, height)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="uint8",
        crs=CRS.from_epsg(4326),
        transform=transform,
    ) as dst:
        dst.write(data)
    return path


def _make_png(path: Path, width: int = 128, height: int = 128) -> Path:
    """Write a synthetic colorful RGB PNG."""
    arr = np.random.randint(0, 255, (height, width, 3), dtype=np.uint8)
    Image.fromarray(arr).save(str(path))
    return path


def _session(
    tmp_path: Path,
    input_rasters: list[Path] | None = None,
    output_rasters: list[Path] | None = None,
    png_path: Path | None = None,
) -> InspectionSession:
    """Create a minimal InspectionSession for testing."""
    return InspectionSession(
        image_name="test.png",
        output_dir=tmp_path,
        input_raster_paths=input_rasters or [],
        output_raster_paths=output_rasters or [],
        png_map_path=png_path,
        feedback_dir=tmp_path / "feedback",
        cfg=get_validation_config(),
    )


# ---------------------------------------------------------------------------
# make_grid
# ---------------------------------------------------------------------------

class TestMakeGrid:
    def test_basic_creates_correct_tile_count(self, tmp_path):
        s = _session(tmp_path)
        result = make_grid(s, rows=2, cols=3)
        assert result["ok"] is True
        assert len(s.tiles) == 6
        assert s.grid_rows == 2
        assert s.grid_cols == 3

    def test_tile_ids_follow_naming(self, tmp_path):
        s = _session(tmp_path)
        make_grid(s, rows=2, cols=2)
        assert set(s.tiles.keys()) == {"T0_0", "T0_1", "T1_0", "T1_1"}

    def test_emits_vision_grid_event(self, tmp_path):
        s = _session(tmp_path)
        make_grid(s, rows=2, cols=2)
        events = s.drain_events()
        assert len(events) == 1
        ev = events[0]
        assert ev["type"] == "vision_grid"
        assert ev["rows"] == 2
        assert ev["cols"] == 2
        assert len(ev["tiles"]) == 4

    def test_clamps_rows_and_cols_to_max_6(self, tmp_path):
        s = _session(tmp_path)
        result = make_grid(s, rows=10, cols=10)
        assert result["ok"] is True
        assert s.grid_rows == 6
        assert s.grid_cols == 6
        assert len(s.tiles) == 36

    def test_bbox_norm_covers_full_unit_square(self, tmp_path):
        s = _session(tmp_path)
        make_grid(s, rows=1, cols=1)
        tile = s.tiles["T0_0"]
        assert tile.bbox_norm == (0.0, 0.0, 1.0, 1.0)

    def test_geo_bounds_populated_when_raster_present(self, tmp_path):
        tif = _make_geotiff(tmp_path / "out.tif")
        s = _session(tmp_path, output_rasters=[tif])
        make_grid(s, rows=2, cols=2)
        tile = s.tiles["T0_0"]
        assert tile.bounds_geo is not None
        assert len(tile.bounds_geo) == 4


# ---------------------------------------------------------------------------
# crop
# ---------------------------------------------------------------------------

class TestCrop:
    def test_no_files_returns_error(self, tmp_path):
        s = _session(tmp_path)
        result = crop(s, bbox_norm=[0.0, 0.0, 0.5, 0.5])
        assert result["ok"] is False
        assert "error" in result

    def test_png_only_session_succeeds(self, tmp_path):
        png = _make_png(tmp_path / "map.png")
        s = _session(tmp_path, png_path=png)
        make_grid(s, 2, 2)
        result = crop(s, tile_id="T0_0")
        assert result["ok"] is True
        assert "image_b64" in result
        assert len(result["image_b64"]) > 100

    def test_thumbnail_saved_to_feedback_dir(self, tmp_path):
        png = _make_png(tmp_path / "map.png")
        s = _session(tmp_path, png_path=png)
        make_grid(s, 2, 2)
        crop(s, tile_id="T0_0")
        thumb = tmp_path / "feedback" / "thumbs" / "T0_0_z1.png"
        assert thumb.is_file()

    def test_emits_vision_inspecting_tile_event(self, tmp_path):
        png = _make_png(tmp_path / "map.png")
        s = _session(tmp_path, png_path=png)
        make_grid(s, 2, 2)
        s.drain_events()  # discard grid event
        crop(s, tile_id="T0_0")
        events = s.drain_events()
        types = [e["type"] for e in events]
        assert "vision_inspecting_tile" in types

    def test_unknown_tile_id_returns_error(self, tmp_path):
        png = _make_png(tmp_path / "map.png")
        s = _session(tmp_path, png_path=png)
        result = crop(s, tile_id="NONEXISTENT")
        assert result["ok"] is False

    def test_zoom_narrows_bbox(self, tmp_path):
        png = _make_png(tmp_path / "map.png")
        s = _session(tmp_path, png_path=png)
        make_grid(s, 2, 2)
        result_z1 = crop(s, tile_id="T0_0", zoom_level=1)
        result_z2 = crop(s, tile_id="T0_0", zoom_level=2)
        assert result_z1["ok"] is True
        assert result_z2["ok"] is True
        # zoom 2 bbox should be strictly smaller in area
        b1 = result_z1["bbox_norm"]
        b2 = result_z2["bbox_norm"]
        area1 = (b1[2] - b1[0]) * (b1[3] - b1[1])
        area2 = (b2[2] - b2[0]) * (b2[3] - b2[1])
        assert area2 < area1

    def test_crop_with_geotiff_aligns_panels(self, tmp_path):
        tif = _make_geotiff(tmp_path / "out.tif")
        png = _make_png(tmp_path / "map.png")
        s = _session(tmp_path, output_rasters=[tif], png_path=png)
        make_grid(s, 2, 2)
        res = crop(s, tile_id="T0_0")
        assert res["ok"] is True
        tile = s.tiles["T0_0"]
        assert tile.bounds_geo is not None

    def test_crop_missing_transform_marks_tile_not_verifiable(self, tmp_path):
        # Create GeoTIFF without CRS / transform
        raw_tif = tmp_path / "raw.tif"
        data = np.zeros((1, 32, 32), dtype=np.uint8)
        with rasterio.open(
            raw_tif, "w", driver="GTiff", height=32, width=32, count=1, dtype="uint8"
        ) as dst:
            dst.write(data)
        png = _make_png(tmp_path / "map.png")
        s = _session(tmp_path, output_rasters=[raw_tif], png_path=png)
        make_grid(s, 2, 2)
        tile = s.tiles["T0_0"]
        assert tile.bounds_geo is None
        crop(s, tile_id="T0_0")
        assert tile.verdict == "not_verifiable"


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------

class TestGetStats:
    def test_pixel_exact_nodata_pct(self, tmp_path):
        # GeoTIFF is all zeros, no nodata mask — nodata_pct should be 0
        tif = _make_geotiff(tmp_path / "out.tif")
        s = _session(tmp_path, output_rasters=[tif])
        make_grid(s, 1, 1)
        result = get_stats(s, tile_id="T0_0")
        assert result["ok"] is True
        assert result["nodata_pct"] == 0.0

    def test_class_counts_match_known_pattern(self, tmp_path):
        # Top-left quadrant is class 1 (32×32 = 1024 px out of 64×64 = 4096)
        tif = _make_geotiff(tmp_path / "out.tif", width=64, height=64)
        s = _session(tmp_path, output_rasters=[tif])
        make_grid(s, 1, 1)
        result = get_stats(s, tile_id="T0_0")
        assert result["ok"] is True
        assert "class_counts" in result
        counts = result["class_counts"]
        assert 1 in counts
        assert counts[1] == 1024
        assert counts[0] == 4096 - 1024

    def test_no_raster_returns_error(self, tmp_path):
        s = _session(tmp_path)
        make_grid(s, 1, 1)
        result = get_stats(s, tile_id="T0_0")
        assert result["ok"] is False

    def test_unknown_tile_id_returns_error(self, tmp_path):
        tif = _make_geotiff(tmp_path / "out.tif")
        s = _session(tmp_path, output_rasters=[tif])
        result = get_stats(s, tile_id="BOGUS")
        assert result["ok"] is False

    def test_stats_stored_on_tile_record(self, tmp_path):
        tif = _make_geotiff(tmp_path / "out.tif")
        s = _session(tmp_path, output_rasters=[tif])
        make_grid(s, 1, 1)
        get_stats(s, tile_id="T0_0")
        assert s.tiles["T0_0"].stats is not None


# ---------------------------------------------------------------------------
# get_source_info
# ---------------------------------------------------------------------------

class TestGetSourceInfo:
    def test_returns_metadata_from_geotiff(self, tmp_path):
        tif = _make_geotiff(tmp_path / "input.tif")
        s = _session(tmp_path, input_rasters=[tif])
        result = get_source_info(s)
        assert result["ok"] is True
        assert result["crs"] is not None
        assert result["band_count"] == 1
        assert result["width"] == 64
        assert result["height"] == 64

    def test_no_input_raster_still_returns_ok(self, tmp_path):
        s = _session(tmp_path)
        result = get_source_info(s)
        # No rasters — should still return ok with empty info
        assert result["ok"] is True
        assert "input_files" in result

    def test_increments_step_counter(self, tmp_path):
        s = _session(tmp_path)
        before = s.steps_used
        get_source_info(s)
        assert s.steps_used == before + 1


# ---------------------------------------------------------------------------
# mark_result
# ---------------------------------------------------------------------------

class TestMarkResult:
    def test_records_verdict_on_tile(self, tmp_path):
        s = _session(tmp_path)
        make_grid(s, 2, 2)
        result = mark_result(s, tile_id="T0_0", verdict="correct",
                             rationale="Looks good", confidence=0.95)
        assert result["ok"] is True
        assert s.tiles["T0_0"].verdict == "correct"

    def test_emits_vision_tile_verdict_event(self, tmp_path):
        s = _session(tmp_path)
        make_grid(s, 2, 2)
        s.drain_events()
        mark_result(s, tile_id="T0_0", verdict="wrong",
                    rationale="Blank region", confidence=0.9)
        events = s.drain_events()
        types = [e["type"] for e in events]
        assert "vision_tile_verdict" in types

    def test_invalid_verdict_returns_error(self, tmp_path):
        s = _session(tmp_path)
        make_grid(s, 2, 2)
        result = mark_result(s, tile_id="T0_0", verdict="invalid_value",
                             rationale="test")
        assert result["ok"] is False

    def test_unknown_tile_id_returns_error(self, tmp_path):
        s = _session(tmp_path)
        result = mark_result(s, tile_id="DOES_NOT_EXIST", verdict="correct",
                             rationale="test")
        assert result["ok"] is False

    def test_verified_area_pct_increases(self, tmp_path):
        s = _session(tmp_path)
        make_grid(s, 2, 2)
        assert s.verified_area_pct() == 0.0
        mark_result(s, "T0_0", "correct", "ok")
        assert s.verified_area_pct() > 0.0

    def test_verdict_color_in_event(self, tmp_path):
        s = _session(tmp_path)
        make_grid(s, 1, 1)
        s.drain_events()
        mark_result(s, "T0_0", "wrong", "bad")
        ev = next(e for e in s.drain_events() if e["type"] == "vision_tile_verdict")
        assert ev["color"] == "#EF4444"  # red for wrong

    def test_confidence_clamped_to_unit_interval(self, tmp_path):
        s = _session(tmp_path)
        make_grid(s, 1, 1)
        mark_result(s, "T0_0", "unsure", "not sure", confidence=5.0)
        assert s.tiles["T0_0"].confidence <= 1.0

    def test_subtile_crop_missing_legend_rejected(self, tmp_path):
        s = _session(tmp_path)
        make_grid(s, 2, 2)
        res = mark_result(s, "T0_0", "wrong", "The title is cut off and there is no legend", defect_category="missing_legend")
        assert res["ok"] is False
        assert "cropped sub-region" in res["error"]

    def test_whole_image_missing_legend_allowed(self, tmp_path):
        s = _session(tmp_path)
        make_grid(s, 1, 1)
        res = mark_result(s, "T0_0", "wrong", "No legend present on deliverable", defect_category="missing_legend")
        assert res["ok"] is True


# ---------------------------------------------------------------------------
# report_insufficient_data
# ---------------------------------------------------------------------------

class TestReportInsufficientData:
    def test_sets_aborted_flag(self, tmp_path):
        s = _session(tmp_path)
        report_insufficient_data(s, reason="Cloud cover 90%",
                                 missing_data_fraction=0.9)
        assert s.aborted is True

    def test_stores_abort_reason(self, tmp_path):
        s = _session(tmp_path)
        report_insufficient_data(s, reason="No valid pixels")
        assert "No valid pixels" in s.abort_reason

    def test_emits_vision_insufficient_data_event(self, tmp_path):
        s = _session(tmp_path)
        report_insufficient_data(s, reason="Bad data", evidence_tile_id="T0_0",
                                 missing_data_fraction=0.8)
        events = s.drain_events()
        assert any(e["type"] == "vision_insufficient_data" for e in events)

    def test_missing_data_fraction_clamped(self, tmp_path):
        s = _session(tmp_path)
        report_insufficient_data(s, reason="test", missing_data_fraction=99.0)
        assert s.abort_missing_fraction <= 1.0


# ---------------------------------------------------------------------------
# finish
# ---------------------------------------------------------------------------

class TestFinish:
    def test_all_correct_gives_valid_verdict(self, tmp_path):
        s = _session(tmp_path)
        make_grid(s, 2, 2)
        for tid in list(s.tiles):
            mark_result(s, tid, "correct", "ok")
        result = finish(s, summary="All good")
        assert result["ok"] is True
        assert result["final_verdict"] == "valid"

    def test_any_wrong_gives_not_valid(self, tmp_path):
        s = _session(tmp_path)
        make_grid(s, 2, 2)
        mark_result(s, "T0_0", "wrong", "bad")
        for tid in ["T0_1", "T1_0", "T1_1"]:
            mark_result(s, tid, "correct", "ok")
        result = finish(s, summary="One defect")
        assert result["final_verdict"] == "not_valid"

    def test_unsure_without_wrong_gives_needs_review(self, tmp_path):
        s = _session(tmp_path)
        make_grid(s, 2, 2)
        for tid in list(s.tiles):
            mark_result(s, tid, "unsure", "not sure")
        result = finish(s, summary="Unclear")
        assert result["final_verdict"] == "needs_review"

    def test_auto_closes_unjudged_tiles_as_not_verifiable(self, tmp_path):
        s = _session(tmp_path)
        make_grid(s, 2, 2)
        mark_result(s, "T0_0", "correct", "ok")
        finish(s, summary="Done")
        # Remaining 3 tiles should be auto-closed
        for tid in ["T0_1", "T1_0", "T1_1"]:
            assert s.tiles[tid].verdict == "not_verifiable"

    def test_all_not_verifiable_gives_not_verifiable_verdict(self, tmp_path):
        s = _session(tmp_path)
        make_grid(s, 1, 1)
        mark_result(s, "T0_0", "not_verifiable", "Crop memory failure")
        result = finish(s, summary="Could not verify")
        assert result["final_verdict"] == "not_verifiable"

    def test_aborted_session_gives_insufficient_data_verdict(self, tmp_path):
        s = _session(tmp_path)
        report_insufficient_data(s, reason="No data")
        result = finish(s, summary="Aborted")
        assert result["final_verdict"] == "insufficient_data"

    def test_emits_vision_summary_event(self, tmp_path):
        s = _session(tmp_path)
        make_grid(s, 1, 1)
        mark_result(s, "T0_0", "correct", "ok")
        s.drain_events()
        finish(s, summary="Complete")
        events = s.drain_events()
        assert any(e["type"] == "vision_summary" for e in events)

    def test_persists_json_to_feedback_dir(self, tmp_path):
        s = _session(tmp_path)
        make_grid(s, 1, 1)
        mark_result(s, "T0_0", "correct", "ok")
        finish(s, summary="Done")
        json_file = tmp_path / "feedback" / "validation_test.png.json"
        assert json_file.is_file()
        data = json.loads(json_file.read_text())
        assert "final_verdict" not in data  # summary dict uses different keys
        assert "image" in data


# ---------------------------------------------------------------------------
# dispatch_tool
# ---------------------------------------------------------------------------

class TestDispatchTool:
    def test_dispatches_make_grid_successfully(self, tmp_path):
        s = _session(tmp_path)
        result = dispatch_tool(s, "make_grid", {"rows": 2, "cols": 2})
        assert result["ok"] is True
        assert len(s.tiles) == 4

    def test_unknown_tool_returns_error(self, tmp_path):
        s = _session(tmp_path)
        result = dispatch_tool(s, "nonexistent_tool", {})
        assert result["ok"] is False
        assert "Unknown tool" in result["error"]

    def test_budget_exceeded_auto_finishes(self, tmp_path):
        s = _session(tmp_path)
        make_grid(s, 1, 1)
        mark_result(s, "T0_0", "correct", "ok")
        # Exhaust the step budget
        s.steps_used = s.cfg.step_budget
        result = dispatch_tool(s, "get_source_info", {})
        # Should have triggered auto-finish
        assert s.finish_called is True
        assert "final_verdict" in result

    def test_bad_arguments_returns_error(self, tmp_path):
        s = _session(tmp_path)
        result = dispatch_tool(s, "make_grid", {"rows": "not_an_int", "cols": 2})
        assert result["ok"] is False

    def test_aborted_session_blocks_non_finish_tools(self, tmp_path):
        s = _session(tmp_path)
        report_insufficient_data(s, reason="bad data")
        s.drain_events()
        result = dispatch_tool(s, "make_grid", {"rows": 2, "cols": 2})
        assert result["ok"] is False
        assert "aborted" in result["error"].lower()

    def test_finish_called_blocks_subsequent_calls(self, tmp_path):
        s = _session(tmp_path)
        make_grid(s, 1, 1)
        mark_result(s, "T0_0", "correct", "ok")
        finish(s, summary="Done")
        result = dispatch_tool(s, "make_grid", {"rows": 1, "cols": 1})
        assert result["ok"] is False
        assert "finish" in result["error"].lower()

