"""Phase 3 tests — Agentic Vision Validation Loop.

All LLM calls are mocked; no network access is used.  Tests cover:
- JSON tool-call parsing (fenced and bare)
- Raster discovery heuristics
- The full agentic loop (scripted model responses)
- Feature-gate routing in visual_check.check_images
- Error handling (LLM failure, malformed responses, budget exhaustion)
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pytest
import rasterio
from PIL import Image
from rasterio.crs import CRS
from rasterio.transform import from_bounds

# ── helpers ────────────────────────────────────────────────────────────────

def _make_png(path: Path, w: int = 128, h: int = 64) -> Path:
    arr = np.random.randint(50, 200, (h, w, 3), dtype=np.uint8)
    Image.fromarray(arr).save(str(path))
    return path


def _make_tif(path: Path, w: int = 32, h: int = 32) -> Path:
    data = np.ones((1, h, w), dtype=np.uint8)
    transform = from_bounds(0, 0, 1, 1, w, h)
    with rasterio.open(path, "w", driver="GTiff", height=h, width=w,
                       count=1, dtype="uint8", crs=CRS.from_epsg(4326),
                       transform=transform) as dst:
        dst.write(data)
    return path


def _task(name: str = "test task", desc: str = "test") -> SimpleNamespace:
    return SimpleNamespace(name=name, description=desc, expected_outputs=["output.png"])


def _json_block(tool: str, args: dict) -> str:
    return f"```json\n{json.dumps({'tool': tool, 'args': args})}\n```"


# ── parsing tests ──────────────────────────────────────────────────────────

class TestParseToolCall:
    """Unit-test the _parse_tool_call helper directly."""

    def _parse(self, text: str):
        from harness.validation.agent import _parse_tool_call
        return _parse_tool_call(text)

    def test_fenced_json_block(self):
        text = '```json\n{"tool": "finish", "args": {"summary": "done"}}\n```'
        result = self._parse(text)
        assert result is not None
        assert result["tool"] == "finish"
        assert result["args"]["summary"] == "done"

    def test_fenced_block_without_json_label(self):
        text = '```\n{"tool": "make_grid", "args": {"rows": 2, "cols": 3}}\n```'
        result = self._parse(text)
        assert result is not None
        assert result["tool"] == "make_grid"

    def test_bare_json_object(self):
        text = 'Here is my call: {"tool": "get_stats", "args": {"tile_id": "T0_0"}}'
        result = self._parse(text)
        assert result is not None
        assert result["tool"] == "get_stats"

    def test_returns_none_when_no_tool_key(self):
        from harness.validation.agent import _parse_tool_call
        text = '{"foo": "bar", "baz": 1}'
        assert _parse_tool_call(text) is None

    def test_returns_none_for_empty_string(self):
        from harness.validation.agent import _parse_tool_call
        assert _parse_tool_call("") is None

    def test_returns_none_for_plain_text(self):
        from harness.validation.agent import _parse_tool_call
        assert _parse_tool_call("I cannot help with this.") is None

    def test_first_valid_block_returned_when_multiple(self):
        text = (
            '```json\n{"tool": "make_grid", "args": {"rows": 2, "cols": 2}}\n```\n'
            '```json\n{"tool": "finish", "args": {"summary": "ok"}}\n```'
        )
        result = self._parse(text)
        assert result["tool"] == "make_grid"


# ── raster discovery tests ─────────────────────────────────────────────────

class TestDiscoverRasters:
    def _discover(self, png_path, output_dir):
        from harness.validation.agent import _discover_rasters
        return _discover_rasters(png_path, output_dir)

    def test_finds_exact_stem_match(self, tmp_path):
        png = _make_png(tmp_path / "ndvi_map.png")
        tif = _make_tif(tmp_path / "ndvi_map.tif")
        inp, out = self._discover(png, tmp_path)
        assert tif in out

    def test_finds_stripped_stem(self, tmp_path):
        """'ndvi_map.png' should find 'ndvi.tif' after stripping '_map'."""
        png = _make_png(tmp_path / "ndvi_map.png")
        tif = _make_tif(tmp_path / "ndvi.tif")
        inp, out = self._discover(png, tmp_path)
        assert tif in out

    def test_falls_back_to_any_tif_in_dir(self, tmp_path):
        png = _make_png(tmp_path / "result.png")
        tif = _make_tif(tmp_path / "completely_different.tif")
        inp, out = self._discover(png, tmp_path)
        assert tif in out

    def test_empty_when_no_tifs(self, tmp_path):
        png = _make_png(tmp_path / "result.png")
        inp, out = self._discover(png, tmp_path)
        assert inp == []
        assert out == []

    def test_deduplicates_results(self, tmp_path):
        png = _make_png(tmp_path / "ndvi.png")
        tif = _make_tif(tmp_path / "ndvi.tif")
        inp, out = self._discover(png, tmp_path)
        # ndvi.tif matches both exact stem and the scan — must not appear twice
        assert out.count(tif) == 1


# ── agentic loop tests ─────────────────────────────────────────────────────

class TestAgenticLoop:
    """Full loop tests with mocked llm.chat_vision."""

    def _call(self, tmp_path, scripted_responses, env_extra=None):
        """Run validate_artifacts with scripted model turns."""
        from harness.validation.agent import validate_artifacts

        png = _make_png(tmp_path / "map.png")
        feedback = tmp_path / "feedback"
        task = _task()

        responses = iter(scripted_responses)

        def mock_llm(prompt, images):
            return next(responses)

        events = []
        env = {"GEOLLM_VALIDATION_MODE": "agentic", **(env_extra or {})}
        with mock.patch("harness.llm.vision_available", return_value=True), \
             mock.patch("harness.llm.chat_vision", side_effect=mock_llm), \
             mock.patch.dict(os.environ, env):
            result = validate_artifacts(task, tmp_path, ["map.png"], feedback,
                                        on_step=events.append)
        return result, events

    # ----

    def test_simple_happy_path(self, tmp_path):
        """make_grid → mark all correct → finish → status 'ok'."""
        responses = [
            _json_block("make_grid", {"rows": 1, "cols": 1}),
            _json_block("mark_result", {"tile_id": "T0_0", "verdict": "correct",
                                        "rationale": "Looks good", "confidence": 0.95}),
            _json_block("finish", {"summary": "All tiles correct."}),
        ]
        result, events = self._call(tmp_path, responses)
        assert len(result) == 1
        assert result[0]["status"] == "ok"
        assert result[0]["file"] == "map.png"

    def test_wrong_tile_gives_needs_revision(self, tmp_path):
        responses = [
            _json_block("make_grid", {"rows": 1, "cols": 1}),
            _json_block("mark_result", {"tile_id": "T0_0", "verdict": "wrong",
                                        "rationale": "Blank output", "defect_category": "blank_output"}),
            _json_block("finish", {"summary": "One defect found."}),
        ]
        result, _ = self._call(tmp_path, responses)
        assert result[0]["status"] == "needs_revision"
        assert any("T0_0" in iss for iss in result[0]["issues"])

    def test_insufficient_data_verdict(self, tmp_path):
        responses = [
            _json_block("report_insufficient_data", {
                "reason": "Cloud cover > 90%", "missing_data_fraction": 0.92}),
            _json_block("finish", {"summary": "Aborted."}),
        ]
        result, _ = self._call(tmp_path, responses)
        assert result[0]["status"] == "insufficient_data"
        assert "Cloud cover" in result[0]["issues"][0]

    def test_llm_failure_returns_skipped(self, tmp_path):
        from harness.validation.agent import validate_artifacts

        png = _make_png(tmp_path / "map.png")
        task = _task()

        def failing_llm(prompt, images):
            raise RuntimeError("Network error")

        with mock.patch("harness.llm.vision_available", return_value=True), \
             mock.patch("harness.llm.chat_vision", side_effect=failing_llm), \
             mock.patch.dict(os.environ, {"GEOLLM_VALIDATION_MODE": "agentic"}):
            result = validate_artifacts(task, tmp_path, ["map.png"],
                                        tmp_path / "feedback")
        assert result[0]["status"] == "skipped"
        assert "failed" in result[0]["issues"][0].lower()

    def test_no_vision_model_returns_skipped(self, tmp_path):
        from harness.validation.agent import validate_artifacts

        png = _make_png(tmp_path / "map.png")
        task = _task()

        with mock.patch("harness.llm.vision_available", return_value=False), \
             mock.patch.dict(os.environ, {"GEOLLM_VALIDATION_MODE": "agentic"}):
            result = validate_artifacts(task, tmp_path, ["map.png"],
                                        tmp_path / "feedback")
        assert result[0]["status"] == "skipped"

    def test_malformed_response_gets_nudged_then_finish(self, tmp_path):
        """If the model returns garbage, the loop sends a nudge and tries again."""
        responses = [
            "Sorry, I cannot help.",                          # garbage turn 1
            _json_block("finish", {"summary": "done"}),       # valid after nudge
        ]
        result, _ = self._call(tmp_path, responses)
        # finish without any marks → budget not exhausted, tiles=0, no wrong → ok
        assert result[0]["status"] == "ok"

    def test_budget_exhaustion_returns_verdict(self, tmp_path):
        """Loop terminates when step budget is hit; result is never None."""
        # Return make_grid over and over — budget will be hit
        responses = [_json_block("make_grid", {"rows": 1, "cols": 1})] * 30
        result, _ = self._call(tmp_path, responses,
                               env_extra={"GEOLLM_VALIDATION_STEP_BUDGET": "3"})
        assert result[0]["status"] in ("ok", "skipped", "needs_revision",
                                       "insufficient_data")

    def test_multi_png_capped_at_3(self, tmp_path):
        """Only first 3 PNGs are validated (mirrors legacy behaviour)."""
        from harness.validation.agent import validate_artifacts

        pngs = []
        for i in range(5):
            p = tmp_path / f"map{i}.png"
            _make_png(p)
            pngs.append(f"map{i}.png")

        task = _task()
        call_count = 0

        def counting_llm(prompt, images):
            nonlocal call_count
            call_count += 1
            return _json_block("finish", {"summary": "done"})

        with mock.patch("harness.llm.vision_available", return_value=True), \
             mock.patch("harness.llm.chat_vision", side_effect=counting_llm), \
             mock.patch.dict(os.environ, {"GEOLLM_VALIDATION_MODE": "agentic"}):
            result = validate_artifacts(task, tmp_path, pngs, tmp_path / "feedback")
        assert len(result) == 3

    def test_missing_png_returns_skipped(self, tmp_path):
        from harness.validation.agent import validate_artifacts

        task = _task()
        with mock.patch("harness.llm.vision_available", return_value=True), \
             mock.patch.dict(os.environ, {"GEOLLM_VALIDATION_MODE": "agentic"}):
            result = validate_artifacts(task, tmp_path, ["does_not_exist.png"],
                                        tmp_path / "feedback")
        assert result[0]["status"] == "skipped"

    def test_sse_events_emitted(self, tmp_path):
        """vision_check started/done events must be forwarded."""
        responses = [_json_block("finish", {"summary": "done"})]
        _, events = self._call(tmp_path, responses)
        types = [e["type"] for e in events]
        assert types.count("vision_check") >= 2  # started + done

    def test_visual_json_written(self, tmp_path):
        responses = [_json_block("finish", {"summary": "done"})]
        self._call(tmp_path, responses)
        assert (tmp_path / "feedback" / "visual.json").is_file()


# ── feature-gate tests ──────────────────────────────────────────────────────

class TestFeatureGate:
    def test_legacy_mode_uses_legacy_path(self, tmp_path):
        """With GEOLLM_VALIDATION_MODE=legacy, agentic agent must NOT be imported."""
        from harness import visual_check

        task = _task()
        with mock.patch.dict(os.environ, {"GEOLLM_VALIDATION_MODE": "legacy"}), \
             mock.patch("harness.llm.vision_available", return_value=False):
            result = visual_check.check_images(task, tmp_path, [], tmp_path / "fb")
        # Empty PNG list → empty result, no crash
        assert result == []

    def test_agentic_mode_routes_to_agent(self, tmp_path):
        from harness import visual_check

        png = _make_png(tmp_path / "map.png")
        task = _task()

        with mock.patch.dict(os.environ, {"GEOLLM_VALIDATION_MODE": "agentic"}), \
             mock.patch("harness.llm.vision_available", return_value=True), \
             mock.patch("harness.llm.chat_vision",
                        return_value=_json_block("finish", {"summary": "ok"})):
            result = visual_check.check_images(task, tmp_path, ["map.png"],
                                               tmp_path / "feedback")
        assert len(result) == 1
        assert result[0]["file"] == "map.png"

    def test_default_mode_is_legacy(self, tmp_path):
        """When GEOLLM_VALIDATION_MODE is not set, legacy path runs."""
        from harness import visual_check

        task = _task()
        env_without_mode = {k: v for k, v in os.environ.items()
                            if k != "GEOLLM_VALIDATION_MODE"}
        with mock.patch.dict(os.environ, env_without_mode, clear=True), \
             mock.patch("harness.llm.vision_available", return_value=False):
            result = visual_check.check_images(task, tmp_path, [], tmp_path / "fb")
        assert result == []


# ── pi_config tests ─────────────────────────────────────────────────────────

class TestPiConfigNewFields:
    def test_new_fields_have_defaults(self):
        from harness.pi_config import load_config
        cfg = load_config()
        assert hasattr(cfg, "validation_step_budget")
        assert hasattr(cfg, "validation_cost_limit_usd")

    def test_validation_mode_removed_from_config(self):
        """validation_mode is no longer a pi_config field — it lives in
        harness.validation.config.get_mode() as the single source of truth."""
        from harness.pi_config import load_config
        cfg = load_config()
        assert not hasattr(cfg, "validation_mode")

    def test_step_budget_default(self):
        from harness.pi_config import load_config
        env = {k: v for k, v in os.environ.items() if k != "GEOLLM_VALIDATION_STEP_BUDGET"}
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = load_config()
        assert cfg.validation_step_budget == 12

    def test_cost_limit_default(self):
        from harness.pi_config import load_config
        env = {k: v for k, v in os.environ.items() if k != "GEOLLM_VALIDATION_COST_LIMIT_USD"}
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = load_config()
        assert cfg.validation_cost_limit_usd == 0.20

    def test_existing_fields_unchanged(self):
        """Adding new fields must not break existing Config consumers."""
        from harness.pi_config import load_config
        cfg = load_config()
        assert isinstance(cfg.vision_max_retries, int)
        assert isinstance(cfg.max_concurrent_tasks, int)
        assert isinstance(cfg.runs_dir, Path)


class TestGetMode:
    """Single source of truth for the validation mode (validation.config.get_mode)."""

    def _mode(self):
        from harness.validation.config import get_mode
        return get_mode()

    def test_default_is_legacy(self):
        env = {k: v for k, v in os.environ.items() if k != "GEOLLM_VALIDATION_MODE"}
        with mock.patch.dict(os.environ, env, clear=True):
            assert self._mode() == "legacy"

    def test_agentic_when_set(self):
        with mock.patch.dict(os.environ, {"GEOLLM_VALIDATION_MODE": "agentic"}):
            assert self._mode() == "agentic"

    def test_invalid_value_falls_back_to_legacy(self, caplog):
        import logging
        env = {k: v for k, v in os.environ.items() if k != "GEOLLM_VALIDATION_MODE"}
        env["GEOLLM_VALIDATION_MODE"] = "bogus"
        with mock.patch.dict(os.environ, env, clear=True):
            with caplog.at_level(logging.WARNING, logger="harness.validation"):
                assert self._mode() == "legacy"
        assert any("falling back" in r.message for r in caplog.records)

    def test_visual_check_uses_get_mode(self):
        """visual_check.check_images must route on get_mode(), not a raw env read."""
        import inspect
        from harness import visual_check
        src = inspect.getsource(visual_check.check_images)
        # Strip the docstring so the assertion targets executable code only.
        code = src.split('"""', 2)[-1] if src.count('"""') >= 2 else src
        assert "get_mode()" in code
        assert "os.environ.get(" not in code
        assert 'os.environ["GEOLLM_VALIDATION_MODE"]' not in code

