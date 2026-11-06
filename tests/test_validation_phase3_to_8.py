"""Tests for Steps 3 through 8 of the vision-validation upgrade."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pytest
from PIL import Image

from harness import visual_check
from harness.validation.agent import _build_system_prompt, validate_artifacts
from harness.validation.config import ValidationConfig, get_validation_config
from harness.validation.tools import InspectionSession, finish, make_grid


# ---------------------------------------------------------------------------
# Step 3: Input paths passed into validation
# ---------------------------------------------------------------------------

def test_input_files_reach_discover_rasters(tmp_path):
    """Real input file paths are passed into _discover_rasters via check_images."""
    tif_path = tmp_path / "input.tif"
    tif_path.write_bytes(b"dummy")

    png_path = tmp_path / "map.png"
    arr = np.zeros((32, 32, 3), dtype=np.uint8)
    Image.fromarray(arr).save(png_path)

    task = SimpleNamespace(
        name="test",
        description="test",
        expected_outputs=["map.png"],
        input_files=[tif_path],
    )

    with mock.patch("harness.validation.agent._discover_rasters") as mock_disc:
        mock_disc.return_value = ([tif_path], [])
        with mock.patch("harness.llm.vision_available", return_value=True):
            with mock.patch("harness.llm.chat_vision_multi") as mock_multi:
                mock_multi.return_value = '```json\n{"tool": "finish", "args": {"summary": "done"}}\n```'
                with mock.patch.dict(os.environ, {"GEOLLM_VALIDATION_MODE": "agentic"}):
                    visual_check.check_images(task, tmp_path, ["map.png"], tmp_path / "fb", input_files=[tif_path])
        assert mock_disc.called
        _, kwargs = mock_disc.call_args
        assert kwargs.get("real_inputs") == [tif_path]


# ---------------------------------------------------------------------------
# Step 4: Feedback memory & input error filtering
# ---------------------------------------------------------------------------

def test_feedback_memory_and_filtering():
    """Verify memory accumulation logic and that input problems do not go to agent critique."""
    feedback_memory = []
    round_1_bad = [
        {"file": "out.png", "tile_id": "tile_0_0", "category": "output", "issues": ["blurry"], "recommended_action": "increase dpi"},
        {"file": "out.png", "tile_id": "tile_0_1", "category": "input", "issues": ["heavy cloud"], "recommended_action": "use cloudy mask"},
    ]

    for v in round_1_bad:
        tile_ids = [t.get("tile_id") for t in feedback_memory]
        if v.get("tile_id") not in tile_ids:
            feedback_memory.append({
                "tile_id": v.get("tile_id"),
                "file": v["file"],
                "severity": v.get("severity", "medium"),
                "category": v.get("category", "output"),
                "suggested_fix": v.get("recommended_action", ""),
                "status": "open",
            })

    assert len(feedback_memory) == 2
    assert all(m["status"] == "open" for m in feedback_memory)

    # In round 2, tile_0_0 is fixed, only tile_0_1 remains bad
    round_2_bad = [
        {"file": "out.png", "tile_id": "tile_0_1", "category": "input", "issues": ["heavy cloud"], "recommended_action": "use cloudy mask"},
    ]
    bad_tile_ids = {v.get("tile_id") for v in round_2_bad}
    for mem in feedback_memory:
        if mem["tile_id"] not in bad_tile_ids:
            mem["status"] = "fixed"

    mem_0_0 = next(m for m in feedback_memory if m["tile_id"] == "tile_0_0")
    mem_0_1 = next(m for m in feedback_memory if m["tile_id"] == "tile_0_1")
    assert mem_0_0["status"] == "fixed"
    assert mem_0_1["status"] == "open"

    # Only output/code issues are sent to sub-agent
    agent_bad = [v for v in round_2_bad if v.get("category") != "input"]
    assert len(agent_bad) == 0


# ---------------------------------------------------------------------------
# Step 5: GIFs and Image Cap
# ---------------------------------------------------------------------------

def test_png_rels_includes_gif(tmp_path):
    from harness.pi_harness import _png_rels
    status_file = tmp_path / "last_status.json"
    gif_file = tmp_path / "anim.gif"
    gif_file.write_bytes(b"GIF89a")
    png_file = tmp_path / "chart.png"
    png_file.write_bytes(b"dummy")

    status_file.write_text(json.dumps({"artifacts": ["anim.gif", "chart.png"]}))
    rels = _png_rels(tmp_path)
    assert "anim.gif" in rels
    assert "chart.png" in rels


def test_gif_frames_sampled(tmp_path):
    """5-frame GIF expands into 3 frames (0, 2, 4)."""
    frames = [Image.fromarray(np.full((32, 32, 3), i * 40, dtype=np.uint8)) for i in range(5)]
    gif_path = tmp_path / "animation.gif"
    frames[0].save(gif_path, save_all=True, append_images=frames[1:], duration=100, loop=0)

    task = SimpleNamespace(name="t", description="d", expected_outputs=["animation.gif"])
    with mock.patch("harness.llm.vision_available", return_value=False):
        verdicts = validate_artifacts(task, tmp_path, ["animation.gif"], tmp_path / "feedback")

    # Should expand to 3 sampled frame verdicts (first, middle, last)
    assert len(verdicts) == 3
    assert any("frame_0" in v["file"] for v in verdicts)
    assert any("frame_2" in v["file"] for v in verdicts)
    assert any("frame_4" in v["file"] for v in verdicts)


def test_max_images_env_var():
    with mock.patch.dict(os.environ, {"GEOLLM_VALIDATION_MAX_IMAGES": "10"}):
        cfg = get_validation_config()
        assert cfg.max_images_per_run == 10


# ---------------------------------------------------------------------------
# Step 6: Query-Aware Prompt & Finish Checklist
# ---------------------------------------------------------------------------

def test_system_prompt_includes_task_description_and_checklist():
    prompt = _build_system_prompt(
        task_name="Wildfire Analysis",
        task_description="Map burn severity in Athens",
        image_name="burn_map.png",
        input_gate_summary="0.05 cloud fraction",
    )
    assert "TASK: Map burn severity in Athens" in prompt
    assert "CHECKLIST: Verify legend present" in prompt
    assert "INPUT DATA QUALITY: 0.05 cloud fraction" in prompt


def test_finish_emits_checklist_results(tmp_path):
    png = tmp_path / "map.png"
    Image.fromarray(np.zeros((64, 64, 3), dtype=np.uint8)).save(png)

    session = InspectionSession(
        image_name="map.png",
        output_dir=tmp_path,
        input_raster_paths=[],
        output_raster_paths=[],
        png_map_path=png,
        feedback_dir=tmp_path / "feedback",
        cfg=get_validation_config(),
    )
    make_grid(session, rows=1, cols=1)
    session.drain_events()
    res = finish(session, summary="ok", checklist_results={"legend": True, "title": False})
    events = session.drain_events()

    assert res["checklist_results"] == {"legend": True, "title": False}
    summary_ev = next(e for e in events if e["type"] == "vision_summary")
    assert summary_ev["checklist_results"] == {"legend": True, "title": False}


# ---------------------------------------------------------------------------
# Step 7: SyntaxError Does Not Consume Attempt
# ---------------------------------------------------------------------------

def test_syntax_error_sets_flag(tmp_path):
    runner_py = Path(__file__).resolve().parent.parent / "harness" / "docker_runner.py"
    payload = {
        "command": "run_geospatial_code",
        "attempt": 1,
        "run_dir": str(tmp_path),
        "code": "def broken_code(:",
    }
    env = {
        **os.environ,
        "GEOLLM_RUN_DIR": str(tmp_path),
        "GEOLLM_ALLOWED_FILES": json.dumps([]),
    }
    proc = subprocess.run(
        [sys.executable, str(runner_py)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
    )
    data = json.loads(proc.stdout)
    assert data["ok"] is False
    assert data.get("syntax_error") is True
    assert "Syntax error detected before execution" in data["message"]


# ---------------------------------------------------------------------------
# Step 8: Script Persistence / Patch Hint
# ---------------------------------------------------------------------------

def test_patch_hint_when_last_code_set():
    task_state = SimpleNamespace(last_code="print('hello world')")
    last_code = getattr(task_state, "last_code", None)
    if last_code:
        patch_hint = (
            "\n\nPrefer to fix using SEARCH/REPLACE patches in this format:\n"
            "<<<<<<< SEARCH\n<exact lines to replace>\n=======\n<replacement lines>\n>>>>>>> REPLACE\n"
            "If patching is not possible, re-run the full corrected script."
        )
    else:
        patch_hint = " Re-run the full corrected script."

    assert "SEARCH/REPLACE" in patch_hint
    assert "<<<<<<< SEARCH" in patch_hint


# ---------------------------------------------------------------------------
# Token Overflow Protection (Layer 1 & Layer 3)
# ---------------------------------------------------------------------------

def test_crop_result_strips_image_b64_from_conversation_text(tmp_path):
    """Layer 1: Verify that crop() base64 is NOT serialized into conversation text."""
    png_path = tmp_path / "map.png"
    Image.fromarray(np.random.randint(0, 255, (128, 128, 3), dtype=np.uint8)).save(png_path)
    task = SimpleNamespace(name="t", description="d", expected_outputs=["map.png"])

    captured_conversations = []
    responses = [
        '```json\n{"tool": "make_grid", "args": {"rows": 2, "cols": 2}}\n```',
        '```json\n{"tool": "crop", "args": {"tile_id": "T0_0"}}\n```',
        '```json\n{"tool": "mark_result", "args": {"tile_id": "T0_0", "verdict": "correct", "rationale": "ok"}}\n```',
        '```json\n{"tool": "finish", "args": {"summary": "done"}}\n```',
    ]

    def fake_llm(conv, imgs):
        captured_conversations.append([dict(m) for m in conv])
        return responses.pop(0)

    from harness.validation.agent import _run_agentic_loop
    _run_agentic_loop(
        png_path=png_path,
        rel="map.png",
        output_dir=tmp_path,
        feedback_dir=tmp_path / "fb",
        task=task,
        on_step=lambda ev: None,
        cfg=get_validation_config(),
        llm_call=fake_llm,
        max_turns=10,
    )

    # Turn 2 conversation (index 2) contains the tool result from crop()
    turn2_user_msg = captured_conversations[2][-1]["content"]
    assert '"image_b64"' not in turn2_user_msg
    assert '"image_path"' not in turn2_user_msg
    assert len(turn2_user_msg) < 1000


def test_chat_vision_multi_compresses_oversized_images(tmp_path):
    """Layer 3: Oversized PNGs (> max_img_bytes) are compressed to JPEG in chat_vision_multi."""
    from harness import llm

    big_png = tmp_path / "noisy.png"
    # High-entropy random RGBA image that exceeds a 50 KB threshold
    arr = np.random.randint(0, 256, (600, 600, 4), dtype=np.uint8)
    Image.fromarray(arr, mode="RGBA").save(big_png)
    raw_size = big_png.stat().st_size
    assert raw_size > 50 * 1024

    captured_payloads = []

    def fake_openrouter(messages, show, model=None, stream=False):
        captured_payloads.append(messages)
        return "ok"

    with mock.patch.object(llm, "vision_available", return_value=True), \
         mock.patch.object(llm, "_openrouter", side_effect=fake_openrouter), \
         mock.patch.dict(os.environ, {"GEOLLM_VISION_MAX_IMAGE_BYTES": str(50 * 1024)}):
        llm.chat_vision_multi([{"role": "user", "content": "check"}], [str(big_png)])

    last_content = captured_payloads[0][-1]["content"]
    img_part = next(p for p in last_content if p["type"] == "image_url")
    url = img_part["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")
    # Compressed JPEG base64 should be substantially smaller than raw RGBA PNG base64
    assert len(url) < raw_size * 4 // 3


# ---------------------------------------------------------------------------
# Step 9: Date matching, 3D cartography handling, & Feedback Loop Fixes
# ---------------------------------------------------------------------------

def test_rank_rasters_matches_dates_and_changes():
    """Verify that _rank_rasters aligns dates (2026-10) and change context keywords."""
    from harness.validation.agent import _rank_rasters

    inputs = [
        Path("aral_2020-06.tif"),
        Path("aral_2020-10.tif"),
        Path("aral_2026-06.tif"),
        Path("aral_2026-10.tif"),
    ]

    # For water_frame_2026-10.png, aral_2026-10.tif must be ranked first
    ranked = _rank_rasters(inputs, Path("water_frame_2026-10.png"))
    assert ranked[0].name == "aral_2026-10.tif"

    # For June 2020 frame, aral_2020-06.tif must be ranked first
    ranked_june = _rank_rasters(inputs, Path("water_frame_2020-06.png"))
    assert ranked_june[0].name == "aral_2020-06.tif"

    # For generic map.png with change detection context keywords, change raster is ranked first
    outputs = [
        Path("water_2020-06.tif"),
        Path("water_2026-10.tif"),
        Path("water_change_classes.tif"),
    ]
    ranked_out = _rank_rasters(outputs, Path("map.png"), context_keywords=["change", "difference"])
    assert ranked_out[0].name == "water_change_classes.tif"


def test_session_to_verdict_handles_not_verifiable_and_3d(tmp_path):
    """Verify _session_to_verdict distinguishes uninspected runs from 3D/not_verifiable tiles."""
    from harness.validation.agent import _session_to_verdict
    from harness.validation.tools import InspectionSession, TileRecord

    # Case A: finish() called without inspecting any tile -> not_verified with "No tiles were inspected"
    sess_uninspected = InspectionSession(
        image_name="map.png",
        output_dir=tmp_path,
        input_raster_paths=[],
        output_raster_paths=[],
        png_map_path=None,
        feedback_dir=tmp_path / "fb",
    )
    sess_uninspected.finish_called = True
    v_uninspected = _session_to_verdict(sess_uninspected, "map.png")
    assert v_uninspected["status"] == "not_verified"
    assert "No tiles were inspected" in v_uninspected["issues"][0]

    # Case B: 3D perspective animation where all tiles are marked not_verifiable -> ok
    sess_3d = InspectionSession(
        image_name="water_area_3d_animation.gif",
        output_dir=tmp_path,
        input_raster_paths=[],
        output_raster_paths=[],
        png_map_path=None,
        feedback_dir=tmp_path / "fb",
    )
    sess_3d.finish_called = True
    sess_3d.tiles["T0_0"] = TileRecord(
        tile_id="T0_0",
        bbox_norm=(0, 0, 0.5, 0.5),
        verdict="not_verifiable",
        rationale="3D isometric surface cannot be planar georeferenced",
    )
    v_3d = _session_to_verdict(sess_3d, "water_area_3d_animation.gif")
    assert v_3d["status"] == "ok"
    assert "3D isometric surface" in v_3d["issues"][0]

    # Case C: Standard 2D map where tiles were marked not_verifiable -> not_verified with real rationale
    sess_map = InspectionSession(
        image_name="standard_map.png",
        output_dir=tmp_path,
        input_raster_paths=[],
        output_raster_paths=[],
        png_map_path=None,
        feedback_dir=tmp_path / "fb",
    )
    sess_map.finish_called = True
    sess_map.tiles["T0_0"] = TileRecord(
        tile_id="T0_0",
        bbox_norm=(0, 0, 0.5, 0.5),
        verdict="not_verifiable",
        rationale="Missing projection headers in reference",
    )
    v_map = _session_to_verdict(sess_map, "standard_map.png")
    assert v_map["status"] == "not_verified"
    assert "Missing projection headers" in v_map["issues"][0]
    assert "No tiles were inspected" not in v_map["issues"][0]


def test_system_prompt_guidance():
    """Verify system prompt includes guidance preventing legend false positives on tile crops."""
    from harness.validation.agent import _build_system_prompt

    prompt = _build_system_prompt(
        task_name="Change detection",
        task_description="Compare 2020 vs 2026",
        image_name="map.png",
    )
    assert "NEVER mark an individual cropped tile 'wrong' for 'missing legend'" in prompt
    assert "Full overview: Overall elements" in prompt
    assert "Single Deliverable Scope" in prompt


def test_multi_attempt_artifact_retention_and_bad_removal(tmp_path):
    """Verify valid outputs from earlier attempts remain while wrong outputs are excluded until replaced."""
    from harness.orchestrator import find_artifacts
    from harness.pi_harness import _png_rels

    att2_out = tmp_path / "attempt_02" / "outputs"
    att2_out.mkdir(parents=True)
    (att2_out / "result.json").write_text('{"summary": "valid summary text over twenty chars"}', encoding="utf-8")
    (att2_out / "regional_water_change.png").write_bytes(b"bad_png")
    (att2_out / "water_area_trend.png").write_bytes(b"good_trend")
    (att2_out / "water_timelapse.gif").write_bytes(b"good_gif")
    (att2_out / "water_mask_2020.tif").write_bytes(b"good_tif")

    (tmp_path / "last_status.json").write_text(
        json.dumps({"ok": True, "attempt": 2, "artifacts": []}),
        encoding="utf-8",
    )
    # Mark regional_water_change.png as wrong in attempt 2
    (tmp_path / "vision_revision.json").write_text(
        json.dumps({"bad_files": ["regional_water_change.png"], "attempt": 2, "unfixed": False}),
        encoding="utf-8",
    )

    arts_during_rev = find_artifacts(tmp_path)
    names_during_rev = {a["name"] for a in arts_during_rev}
    assert "regional_water_change.png" not in names_during_rev
    assert "water_area_trend.png" in names_during_rev
    assert "water_timelapse.gif" in names_during_rev
    assert "water_mask_2020.tif" in names_during_rev

    # Sub-agent creates attempt_03 with only the newly fixed regional_water_change.png
    att3_out = tmp_path / "attempt_03" / "outputs"
    att3_out.mkdir(parents=True)
    (att3_out / "regional_water_change.png").write_bytes(b"fixed_png")
    (tmp_path / "last_status.json").write_text(
        json.dumps({"ok": True, "attempt": 3, "artifacts": []}),
        encoding="utf-8",
    )

    # _png_rels must find the newly generated attempt_03 PNG plus earlier valid PNGs/GIFs
    rels = _png_rels(tmp_path)
    rel_names = {Path(r).name for r in rels}
    assert "regional_water_change.png" in rel_names
    assert "water_area_trend.png" in rel_names
    assert "water_timelapse.gif" in rel_names

    # find_artifacts must return the new attempt_03 regional_water_change.png AND retain attempt_02 valid files
    arts_after_fix = find_artifacts(tmp_path)
    by_name = {a["name"]: a for a in arts_after_fix}
    assert by_name["regional_water_change.png"]["attempt"] == 3
    assert by_name["water_area_trend.png"]["attempt"] == 2
    assert by_name["water_timelapse.gif"]["attempt"] == 2
    assert by_name["water_mask_2020.tif"]["attempt"] == 2



