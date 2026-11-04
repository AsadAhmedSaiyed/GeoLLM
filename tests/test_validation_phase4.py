"""Phase 4 tests — Reliability Layer & Consensus Voting.

Tests the consensus re-verification mechanism:
- _parse_verdict_from_text keyword and boundary parsing
- re_verify_flagged_tiles confirmation and disagreement escalation
- GEOLLM_CONSENSUS_MAX_TILES limit enforcement
- Graceful error recovery on crop or LLM failures
- Integration with agent.py and SSE emission
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pytest
from PIL import Image

from harness.validation.config import get_validation_config
from harness.validation.consensus import _parse_verdict_from_text, re_verify_flagged_tiles
from harness.validation.tools import (
    InspectionSession,
    finish,
    make_grid,
    mark_result,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_png(path: Path, width: int = 128, height: int = 128) -> Path:
    arr = np.random.randint(50, 200, (height, width, 3), dtype=np.uint8)
    Image.fromarray(arr).save(str(path))
    return path


def _make_session(tmp_path: Path, png_path: Path | None = None) -> InspectionSession:
    png = png_path or _make_png(tmp_path / "map.png")
    return InspectionSession(
        image_name="map.png",
        output_dir=tmp_path,
        input_raster_paths=[],
        output_raster_paths=[],
        png_map_path=png,
        feedback_dir=tmp_path / "feedback",
        cfg=get_validation_config(),
    )


# ---------------------------------------------------------------------------
# Unit tests: _parse_verdict_from_text
# ---------------------------------------------------------------------------

class TestParseVerdictFromText:
    def test_exact_keywords(self):
        assert _parse_verdict_from_text("correct") == "correct"
        assert _parse_verdict_from_text("wrong") == "wrong"
        assert _parse_verdict_from_text("unsure") == "unsure"
        assert _parse_verdict_from_text("not_verifiable") == "not_verifiable"

    def test_case_insensitive(self):
        assert _parse_verdict_from_text("CORRECT") == "correct"
        assert _parse_verdict_from_text("Wrong") == "wrong"
        assert _parse_verdict_from_text("UnSure") == "unsure"
        assert _parse_verdict_from_text("NOT_VERIFIABLE") == "not_verifiable"

    def test_first_line_priority(self):
        text = "wrong\nThe original check thought it was correct, but it is actually water."
        assert _parse_verdict_from_text(text) == "wrong"

    def test_multiline_fallback(self):
        text = "Analysis report:\nUpon closer inspection, the classification is correct."
        assert _parse_verdict_from_text(text) == "correct"

    def test_word_boundaries(self):
        # Should not match substrings inside longer words
        assert _parse_verdict_from_text("This was uncorrected in preprocessing.") is None
        assert _parse_verdict_from_text("A wrongful claim was made.") is None

    def test_none_or_empty(self):
        assert _parse_verdict_from_text("") is None
        assert _parse_verdict_from_text(None) is None
        assert _parse_verdict_from_text("   \n  \t  ") is None

    def test_no_matching_keywords(self):
        assert _parse_verdict_from_text("I cannot provide an opinion on this satellite image.") is None


# ---------------------------------------------------------------------------
# Unit tests: re_verify_flagged_tiles
# ---------------------------------------------------------------------------

class TestReVerifyFlaggedTiles:
    def test_confirms_original_wrong_verdict(self, tmp_path):
        session = _make_session(tmp_path)
        make_grid(session, 2, 2)
        mark_result(session, "T0_0", "wrong", "Severe cloud confusion", confidence=0.9)
        mark_result(session, "T0_1", "correct", "Clean landcover", confidence=0.95)

        def mock_llm(prompt: str, images: list[str]) -> str:
            assert len(images) == 1
            return "wrong\nConfirmed, cloud shadow detected."

        results = re_verify_flagged_tiles(session, mock_llm)

        assert results["T0_0"] == "wrong"
        assert session.tiles["T0_0"].verdict == "wrong"
        assert "cloud confusion" in session.tiles["T0_0"].rationale.lower()

    def test_disagreement_escalates_to_needs_review(self, tmp_path):
        session = _make_session(tmp_path)
        make_grid(session, 2, 2)
        mark_result(session, "T0_0", "wrong", "Suspicious artifact", confidence=0.7)

        def mock_llm(prompt: str, images: list[str]) -> str:
            return "correct\nOn second thought at zoom 2, this matches urban infrastructure."

        results = re_verify_flagged_tiles(session, mock_llm)

        assert results["T0_0"] == "needs_review"
        assert session.tiles["T0_0"].verdict == "needs_review"
        assert "[CONSENSUS DISAGREEMENT]" in session.tiles["T0_0"].rationale
        assert "Original: wrong" in session.tiles["T0_0"].rationale
        assert "Re-verification: correct" in session.tiles["T0_0"].rationale

    def test_unsure_escalates_if_disagrees(self, tmp_path):
        session = _make_session(tmp_path)
        make_grid(session, 2, 2)
        mark_result(session, "T0_0", "unsure", "Low contrast border", confidence=0.5)

        def mock_llm(prompt: str, images: list[str]) -> str:
            return "correct\nClearly delineated river bank."

        results = re_verify_flagged_tiles(session, mock_llm)

        assert results["T0_0"] == "needs_review"
        assert session.tiles["T0_0"].verdict == "needs_review"

    def test_unsure_confirmed_if_agrees(self, tmp_path):
        session = _make_session(tmp_path)
        make_grid(session, 2, 2)
        mark_result(session, "T0_0", "unsure", "Ambiguous boundary", confidence=0.5)

        def mock_llm(prompt: str, images: list[str]) -> str:
            return "unsure\nStill cannot tell with certainty."

        results = re_verify_flagged_tiles(session, mock_llm)

        assert results["T0_0"] == "unsure"
        assert session.tiles["T0_0"].verdict == "unsure"

    def test_correct_and_not_verifiable_tiles_are_not_reverified(self, tmp_path):
        session = _make_session(tmp_path)
        make_grid(session, 2, 2)
        mark_result(session, "T0_0", "correct", "Good", confidence=0.9)
        mark_result(session, "T0_1", "not_verifiable", "Nodata boundary", confidence=0.9)

        calls = []

        def mock_llm(prompt: str, images: list[str]) -> str:
            calls.append(prompt)
            return "wrong"

        results = re_verify_flagged_tiles(session, mock_llm)

        assert len(calls) == 0
        assert results["T0_0"] == "correct"
        assert results["T0_1"] == "not_verifiable"

    def test_respects_max_tiles_env_var(self, tmp_path):
        session = _make_session(tmp_path)
        make_grid(session, 2, 2)
        # Mark all 4 tiles wrong
        for tid in ("T0_0", "T0_1", "T1_0", "T1_1"):
            mark_result(session, tid, "wrong", "Error", confidence=0.8)

        calls = []

        def mock_llm(prompt: str, images: list[str]) -> str:
            calls.append(prompt)
            return "wrong"

        with mock.patch.dict(os.environ, {"GEOLLM_CONSENSUS_MAX_TILES": "2"}):
            re_verify_flagged_tiles(session, mock_llm)

        assert len(calls) == 2

    def test_crop_failure_retains_original_verdict(self, tmp_path):
        # Session without image/raster will fail crop
        session = InspectionSession(
            image_name="test.png",
            output_dir=tmp_path,
            input_raster_paths=[],
            output_raster_paths=[],
            png_map_path=None,
            feedback_dir=tmp_path / "feedback",
            cfg=get_validation_config(),
        )
        make_grid(session, 2, 2)
        mark_result(session, "T0_0", "wrong", "Error", confidence=0.8)

        calls = []

        def mock_llm(prompt: str, images: list[str]) -> str:
            calls.append(prompt)
            return "correct"

        results = re_verify_flagged_tiles(session, mock_llm)

        # Crop fails, so LLM should not be called and verdict remains "wrong"
        assert len(calls) == 0
        assert results["T0_0"] == "wrong"
        assert session.tiles["T0_0"].verdict == "wrong"

    def test_llm_exception_handled_gracefully(self, tmp_path):
        session = _make_session(tmp_path)
        make_grid(session, 2, 2)
        mark_result(session, "T0_0", "wrong", "Original error", confidence=0.8)

        def failing_llm(prompt: str, images: list[str]) -> str:
            raise ConnectionError("LLM API endpoint unavailable")

        results = re_verify_flagged_tiles(session, failing_llm)

        # Should log and retain original verdict
        assert results["T0_0"] == "wrong"
        assert session.tiles["T0_0"].verdict == "wrong"

    def test_unparseable_response_retains_original_verdict(self, tmp_path):
        session = _make_session(tmp_path)
        make_grid(session, 2, 2)
        mark_result(session, "T0_0", "wrong", "Original error", confidence=0.8)

        def gibberish_llm(prompt: str, images: list[str]) -> str:
            return "I am unable to evaluate this request."

        results = re_verify_flagged_tiles(session, gibberish_llm)

        assert results["T0_0"] == "wrong"
        assert session.tiles["T0_0"].verdict == "wrong"


# ---------------------------------------------------------------------------
# Integration tests: consensus within agentic loop
# ---------------------------------------------------------------------------

class TestConsensusIntegration:
    def test_consensus_runs_and_escalates_in_validate_artifacts(self, tmp_path):
        from harness.validation.agent import validate_artifacts

        png = _make_png(tmp_path / "map.png")
        task = SimpleNamespace(name="landcover", description="check landcover map", expected_outputs=["map.png"])

        # Agent loop turns:
        # 1. make_grid
        # 2. mark_result T0_0 wrong
        # 3. finish
        # Then consensus runs on T0_0: returns "correct" (causing disagreement -> needs_review)
        turns = [
            '```json\n{"tool": "make_grid", "args": {"rows": 1, "cols": 1}}\n```',
            '```json\n{"tool": "mark_result", "args": {"tile_id": "T0_0", "verdict": "wrong", "rationale": "Water misclassified"}}\n```',
            '```json\n{"tool": "finish", "args": {"summary": "Done inspecting"}}\n```',
            'correct\nActually this is correct at zoom level 2.',  # consensus response
        ]
        turn_iter = iter(turns)

        def mock_llm(prompt: str, images: list[str]) -> str:
            return next(turn_iter)

        events = []
        with mock.patch("harness.llm.vision_available", return_value=True), \
             mock.patch("harness.llm.chat_vision", side_effect=mock_llm), \
             mock.patch.dict(os.environ, {"GEOLLM_VALIDATION_MODE": "agentic", "GEOLLM_CONSENSUS_ENABLED": "1"}):
            verdicts = validate_artifacts(task, tmp_path, ["map.png"], tmp_path / "feedback", on_step=events.append)

        assert len(verdicts) == 1
        v = verdicts[0]
        # Should be needs_revision because tile was escalated to needs_review
        assert v["status"] == "needs_revision"
        assert any("needs_review" in iss for iss in v["issues"])

        # vision_consensus_done event should be in SSE events
        consensus_events = [e for e in events if e.get("type") == "vision_consensus_done"]
        assert len(consensus_events) == 1
        assert consensus_events[0]["re_verified"] == 1
        assert consensus_events[0]["tiles"]["T0_0"] == "needs_review"

    def test_consensus_disabled_via_env(self, tmp_path):
        from harness.validation.agent import validate_artifacts

        png = _make_png(tmp_path / "map.png")
        task = SimpleNamespace(name="landcover", description="check landcover map", expected_outputs=["map.png"])

        turns = [
            '```json\n{"tool": "make_grid", "args": {"rows": 1, "cols": 1}}\n```',
            '```json\n{"tool": "mark_result", "args": {"tile_id": "T0_0", "verdict": "wrong", "rationale": "Water misclassified"}}\n```',
            '```json\n{"tool": "finish", "args": {"summary": "Done inspecting"}}\n```',
        ]
        turn_iter = iter(turns)

        def mock_llm(prompt: str, images: list[str]) -> str:
            return next(turn_iter)

        events = []
        with mock.patch("harness.llm.vision_available", return_value=True), \
             mock.patch("harness.llm.chat_vision", side_effect=mock_llm), \
             mock.patch.dict(os.environ, {"GEOLLM_VALIDATION_MODE": "agentic", "GEOLLM_CONSENSUS_ENABLED": "0"}):
            verdicts = validate_artifacts(task, tmp_path, ["map.png"], tmp_path / "feedback", on_step=events.append)

        assert len(verdicts) == 1
        v = verdicts[0]
        assert v["status"] == "needs_revision"
        assert any("defect" in iss for iss in v["issues"])
        # No consensus event should have been emitted
        consensus_events = [e for e in events if e.get("type") == "vision_consensus_done"]
        assert len(consensus_events) == 0

