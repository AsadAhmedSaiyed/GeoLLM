"""Phase 5 & 6 tests — Graph validation and Structured feedback."""
from pathlib import Path
from harness.validation.graph_check import validate_graph_deliverable
from harness.validation.feedback import format_structured_feedback
from harness.validation.tools import InspectionSession, make_grid, mark_result
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
