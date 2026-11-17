"""Phase 5 & 6 tests — Graph validation and Structured feedback."""
from pathlib import Path
from harness.validation.graph_check import validate_graph_deliverable
from harness.validation.feedback import format_structured_feedback
from harness.validation.tools import InspectionSession, finish, make_grid, mark_result
from harness.validation.config import get_validation_config

def test_graph_validation_missing_csv(tmp_path):
    png = tmp_path / "chart.png"
    png.write_bytes(b"dummy")
    res = validate_graph_deliverable(png, tmp_path)
    assert not res["csv_found"]
    assert res["verdict"] == "unsure"

def test_graph_validation_with_csv(tmp_path):
    png = tmp_path / "chart.png"
    png.write_bytes(b"dummy")
    csv = tmp_path / "chart.csv"
    csv.write_text("x,y\n1,2\n")
    res = validate_graph_deliverable(png, tmp_path)
    assert res["csv_found"]
    assert res["verdict"] == "valid"

def test_structured_feedback_formatting(tmp_path):
    session = InspectionSession(
        image_name="map.png",
        output_dir=tmp_path,
        input_raster_paths=[],
        output_raster_paths=[],
        png_map_path=tmp_path / "map.png",
        feedback_dir=tmp_path / "feedback",
        cfg=get_validation_config(),
    )
    make_grid(session, 2, 2)
    mark_result(session, "T0_0", "wrong", "Misclassified water", defect_category="semantic_mismatch")
    
    fb = format_structured_feedback(session)
    assert fb["feedback_version"] == "2.0"
    assert fb["overall_verdict"] == "not_valid"
    assert len(fb["defects"]) == 1
    assert fb["defects"][0]["tile_id"] == "T0_0"
    assert fb["defects"][0]["type"] == "semantic_mismatch"


def test_agent_verdict_includes_structured_feedback_and_graph_check(tmp_path):
    from PIL import Image
    import numpy as np
    from harness.validation.agent import _session_to_verdict

    png = tmp_path / "trend_chart.png"
    Image.fromarray(np.zeros((32, 32, 3), dtype=np.uint8)).save(png)
    csv = tmp_path / "trend_chart.csv"
    csv.write_text("date,ndvi\n2024-01-01,0.45\n", encoding="utf-8")

    session = InspectionSession(
        image_name="trend_chart.png",
        output_dir=tmp_path,
        input_raster_paths=[],
        output_raster_paths=[],
        png_map_path=png,
        feedback_dir=tmp_path / "feedback",
        cfg=get_validation_config(),
    )
    make_grid(session, 1, 1)
    mark_result(session, "T0_0", "correct", "Valid chart")
    finish(session, summary="Chart verified")

    verdict = _session_to_verdict(session, "trend_chart.png")
    assert verdict["status"] == "ok"
    assert "structured_feedback" in verdict
    assert verdict["structured_feedback"]["overall_verdict"] == "valid"
    assert "graph_check" in verdict
    assert verdict["graph_check"]["csv_found"] is True


def test_executor_stage_input_file_uses_hardlink(tmp_path):
    from harness.executor import _stage_input_file

    src = tmp_path / "source.tif"
    src.write_bytes(b"FAKE_GEOTIFF_BYTES" * 100)
    dest = tmp_path / "dest.tif"

    _stage_input_file(src, dest)
    assert dest.is_file()
    assert dest.read_bytes() == src.read_bytes()
    # On the same filesystem, hardlink shares the same inode / st_ino and increments st_nlink
    assert src.stat().st_nlink >= 2
