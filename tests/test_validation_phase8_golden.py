"""Phase 8 tests — Golden-Set Evaluation & End-to-End Validation Suite."""
import pytest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import numpy as np
from PIL import Image

from harness.validation.agent import validate_artifacts
from harness.validation.quality_gate import QualityGateResult

def _make_dummy_png(path: Path):
    arr = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
    Image.fromarray(arr).save(str(path))
    return path

class TestGoldenSetValidation:
    def test_positive_control_clear_scene(self, tmp_path):
        png = _make_dummy_png(tmp_path / "lake.png")
        task = SimpleNamespace(name="water_mapping", description="map clear lake", expected_outputs=["lake.png"])
        
        turns = [
            '```json\n{"tool": "make_grid", "args": {"rows": 1, "cols": 1}}\n```',
            '```json\n{"tool": "mark_result", "args": {"tile_id": "T0_0", "verdict": "correct", "rationale": "Perfect match"}}\n```',
            '```json\n{"tool": "finish", "args": {"summary": "All valid"}}\n```'
        ]
        turn_iter = iter(turns)

        with mock.patch("harness.llm.vision_available", return_value=True), \
             mock.patch("harness.llm.chat_vision", side_effect=lambda p, i: next(turn_iter)), \
             mock.patch.dict("os.environ", {"GEOLLM_VALIDATION_MODE": "agentic"}):
            verdicts = validate_artifacts(task, tmp_path, ["lake.png"], tmp_path / "feedback")
            
        assert len(verdicts) == 1
        assert verdicts[0]["status"] == "ok"

    def test_insufficient_data_control_cloudy(self, tmp_path):
        png = _make_dummy_png(tmp_path / "cloudy.png")
        task = SimpleNamespace(name="clouds", description="cloudy scene", expected_outputs=["cloudy.png"])
        
        turns = [
            '```json\n{"tool": "report_insufficient_data", "args": {"reason": "Over 90% cloud cover"}}\n```'
        ]
        turn_iter = iter(turns)

        with mock.patch("harness.llm.vision_available", return_value=True), \
             mock.patch("harness.llm.chat_vision", side_effect=lambda p, i: next(turn_iter)), \
             mock.patch.dict("os.environ", {"GEOLLM_VALIDATION_MODE": "agentic"}):
            verdicts = validate_artifacts(task, tmp_path, ["cloudy.png"], tmp_path / "feedback")
            
        assert len(verdicts) == 1
        assert verdicts[0]["status"] == "insufficient_data"

    def test_inverted_threshold_defect_control(self, tmp_path):
        png = _make_dummy_png(tmp_path / "bad_threshold.png")
        task = SimpleNamespace(name="threshold", description="bad threshold", expected_outputs=["bad_threshold.png"])
        
        turns = [
            '```json\n{"tool": "make_grid", "args": {"rows": 1, "cols": 1}}\n```',
            '```json\n{"tool": "mark_result", "args": {"tile_id": "T0_0", "verdict": "wrong", "rationale": "Inverted NDWI mask"}}\n```',
            '```json\n{"tool": "finish", "args": {"summary": "Inverted threshold error"}}\n```',
            'wrong\nConfirmed inverted threshold'
        ]
        turn_iter = iter(turns)

        with mock.patch("harness.llm.vision_available", return_value=True), \
             mock.patch("harness.llm.chat_vision", side_effect=lambda p, i: next(turn_iter)), \
             mock.patch.dict("os.environ", {"GEOLLM_VALIDATION_MODE": "agentic"}):
            verdicts = validate_artifacts(task, tmp_path, ["bad_threshold.png"], tmp_path / "feedback")
            
        assert len(verdicts) == 1
        assert verdicts[0]["status"] == "needs_revision"
