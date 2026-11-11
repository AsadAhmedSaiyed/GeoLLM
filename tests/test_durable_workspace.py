"""Unit tests for Durable Workspaces, Checkpointing, Event Replay, and Disk Cleanup."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from harness.checkpoint import (
    load_checkpoint,
    save_checkpoint,
    verify_checkpoint_files,
    delete_checkpoint,
)
from harness.workspace import (
    get_workspace_dir,
    init_workspace_layout,
    clean_workspace,
    promote_outputs,
    acquire_workspace_lock,
    cleanup_expired_workspaces,
)
from harness.orchestrator import TaskManager, find_artifacts


def test_atomic_checkpoint_lifecycle(tmp_path: Path):
    """Verify atomic write, loading, and recovery of checkpoint.json."""
    task_id = "task_1"
    runs_dir = tmp_path / "runs"

    # 1. Initial stage
    cp_path = save_checkpoint(
        task_id=task_id,
        stage="task_created",
        data={"question": "Test NDVI query", "bbox": [55.0, 25.0, 55.5, 25.5]},
        runs_dir=runs_dir,
    )
    assert cp_path.is_file()
    assert (runs_dir / task_id / "checkpoint.tmp").exists() is False

    loaded = load_checkpoint(task_id, runs_dir=runs_dir)
    assert loaded is not None
    assert loaded["task_id"] == "task_1"
    assert loaded["current_stage"] == "task_created"
    assert loaded["question"] == "Test NDVI query"
    assert loaded["bbox"] == [55.0, 25.0, 55.5, 25.5]

    # 2. Advance stage to plan_approved
    save_checkpoint(
        task_id=task_id,
        stage="plan_approved",
        data={"plan": "Step 1: calculate NDVI", "plan_approved": True},
        runs_dir=runs_dir,
    )
    updated = load_checkpoint(task_id, runs_dir=runs_dir)
    assert updated["current_stage"] == "plan_approved"
    assert updated["plan_approved"] is True
    assert "task_created" in updated["stages"]
    assert "plan_approved" in updated["stages"]

    # 3. Delete checkpoint
    assert delete_checkpoint(task_id, runs_dir=runs_dir) is True
    assert load_checkpoint(task_id, runs_dir=runs_dir) is None


def test_workspace_layout_and_cleanup(tmp_path: Path):
    """Verify canonical fixed directory structure and physical cleanup on reset."""
    task_id = "task_2"
    runs_dir = tmp_path / "runs"

    # Initialize layout
    ws = init_workspace_layout(task_id, runs_dir)
    assert (ws / "staged_inputs").is_dir()
    assert (ws / "scratch").is_dir()
    assert (ws / "outputs").is_dir()

    # Simulate scratch attempts and staged files
    staged_tif = ws / "staged_inputs" / "test_band.tif"
    staged_tif.write_bytes(b"TIFF_DATA_12345")
    scratch_file = ws / "scratch" / "temp_run.py"
    scratch_file.write_text("print('running')")
    scratch_out = ws / "scratch" / "outputs"
    scratch_out.mkdir(parents=True, exist_ok=True)
    out_map = scratch_out / "result_map.png"
    out_map.write_bytes(b"PNG_IMAGE_DATA")

    # Promote outputs
    promoted = promote_outputs(task_id, scratch_out, runs_dir)
    assert len(promoted) == 1
    assert (ws / "outputs" / "result_map.png").is_file()

    # Add 3D visualization and orthophoto files
    (ws / "terrain_3d.json").write_text('{"elevation_range_m": 0.0}')
    (ws / "lidar_3d.json").write_text('{"elevation_range_m": 0.0}')
    (ws / "orthophoto.png").write_bytes(b"ORTHO_IMAGE")

    # Clean workspace (e.g. on task reset)
    clean_workspace(task_id, runs_dir, preserve_outputs=False)
    assert (ws / "scratch" / "temp_run.py").exists() is False
    assert (ws / "staged_inputs" / "test_band.tif").exists() is False
    assert (ws / "outputs" / "result_map.png").exists() is False
    assert (ws / "terrain_3d.json").exists() is False
    assert (ws / "lidar_3d.json").exists() is False
    assert (ws / "orthophoto.png").exists() is False


def test_workspace_file_locking(tmp_path: Path):
    """Verify mutual exclusion file locking on task.lock."""
    task_id = "task_3"
    runs_dir = tmp_path / "runs"

    with acquire_workspace_lock(task_id, runs_dir) as locked:
        assert locked is True
        # Attempt concurrent lock in same process should fail/be denied
        with acquire_workspace_lock(task_id, runs_dir) as second_lock:
            # On Windows or POSIX non-blocking lock, second attempt must fail
            assert second_lock is False


def test_orchestrator_disk_recovery(tmp_path: Path):
    """Verify TaskManager restores state and event logs from disk on server startup."""
    runs_dir = tmp_path / "runs"
    task_id = "task_1"
    ws = init_workspace_layout(task_id, runs_dir)

    # 1. Create a checkpoint as if server had completed a task earlier
    save_checkpoint(
        task_id=task_id,
        stage="task_completed",
        data={
            "question": "Show vegetation changes",
            "status": "done",
            "step": "Completed",
            "answer": "Vegetation increased by 14% across target area.",
        },
        runs_dir=runs_dir,
    )

    # 2. Write event history to events.jsonl
    events_file = ws / "events.jsonl"
    events = [
        {"id": 1, "task_id": task_id, "type": "start", "question": "Show vegetation changes"},
        {"id": 2, "task_id": task_id, "type": "thinking", "delta": "Analyzing spectral bands..."},
        {"id": 3, "task_id": task_id, "type": "finish", "status": "done", "ok": True},
    ]
    with open(events_file, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")

    # 3. Simulate server startup: new TaskManager instance
    tm = TaskManager(auto_approve=False, runs_dir=runs_dir)
    ts = tm.get_task(task_id)

    assert ts is not None
    assert ts.status == "done"
    assert ts.question == "Show vegetation changes"
    assert ts.step == "Completed"
    assert ts.result is not None
    assert ts.result["answer"] == "Vegetation increased by 14% across target area."
    assert len(ts.event_log) == 3
    assert ts.next_event_id == 4


def test_completed_partial_task_not_resumed_on_startup(tmp_path: Path):
    """Verify tasks that finished with 'partial' status or existing finish events do not auto-resume."""
    runs_dir = tmp_path / "runs"
    task_id = "task_2"
    ws = init_workspace_layout(task_id, runs_dir)

    # Deliverables present
    out_dir = ws / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "ndvi_map.png").write_bytes(b"\x89PNG\r\n\x1a\nfakeimage")

    # Checkpoint saved with partial status
    save_checkpoint(
        task_id=task_id,
        stage="task_completed",
        data={
            "question": "Calculate NDVI",
            "status": "partial",
            "step": "Completed",
            "answer": "NDVI computed successfully.",
        },
        runs_dir=runs_dir,
    )

    events_file = ws / "events.jsonl"
    with open(events_file, "w", encoding="utf-8") as f:
        f.write(json.dumps({"id": 1, "task_id": task_id, "type": "finish", "status": "partial", "ok": True}) + "\n")

    # Start TaskManager
    tm = TaskManager(auto_approve=False, runs_dir=runs_dir)
    ts = tm.get_task(task_id)

    assert ts is not None
    assert ts.status == "partial"
    assert ts.step == "Completed"
    assert tm.active_count() == 0  # Crucial: NOT resumed or running!


def test_ttl_cleanup(tmp_path: Path):
    """Verify background TTL cleanup expires inactive workspaces while preserving outputs."""
    runs_dir = tmp_path / "runs"
    task_id = "task_1"
    ws = init_workspace_layout(task_id, runs_dir)

    # Create old checkpoint (simulating 30 hours ago)
    old_time = time.time() - (30 * 3600)
    save_checkpoint(
        task_id=task_id,
        stage="task_completed",
        data={"status": "done", "step": "Completed"},
        runs_dir=runs_dir,
    )
    # Manually backdate the checkpoint timestamp
    cp_file = ws / "checkpoint.json"
    cp_data = json.loads(cp_file.read_text(encoding="utf-8"))
    cp_data["updated_at"] = old_time
    cp_file.write_text(json.dumps(cp_data), encoding="utf-8")

    # Add dummy scratch file
    dummy_scratch = ws / "scratch" / "heavy_temp.raw"
    dummy_scratch.write_bytes(b"TEMP_BYTES" * 100)

    # Run TTL cleanup with 24 hour threshold
    cleaned = cleanup_expired_workspaces(runs_dir=runs_dir, ttl_hours=24.0)
    assert cleaned == 1
    assert dummy_scratch.exists() is False


def test_code_executed_checkpoint_resumption(tmp_path: Path):
    """Verify that when a task has executed code and produced deliverables on disk,
    server restart restores the task as Completed with deliverables pre-populated,
    without auto-resuming or re-executing background validation."""
    runs_dir = tmp_path / "runs"
    task_id = "task_1"
    ws = init_workspace_layout(task_id, runs_dir)

    # 1. Simulate output deliverables already produced on disk
    outputs_dir = ws / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    map_png = outputs_dir / "water_change_map.png"
    map_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 200)

    # 2. Simulate checkpoint saved at 'code_executed'
    save_checkpoint(
        task_id=task_id,
        stage="code_executed",
        data={
            "question": "Assess water changes across Aral Sea",
            "status": "running",
            "step": "Code executed successfully — deliverables produced",
            "plan_approved": True,
            "verified_outputs": ["water_change_map.png"],
        },
        runs_dir=runs_dir,
    )

    # 3. Restore via TaskManager
    tm = TaskManager(auto_approve=False, runs_dir=runs_dir)
    ts = tm.get_task(task_id)

    assert ts is not None
    assert ts.status == "done"
    assert ts.step == "Completed"
    assert len(ts.artifacts) == 1
    assert ts.artifacts[0]["name"] == "water_change_map.png"
    assert tm.active_count() == 0  # Completed task must NOT be auto-resumed or re-run


def test_approved_plan_without_deliverables_resumes(tmp_path: Path):
    """Verify that when a plan was approved but execution was interrupted before producing
    any deliverables, server restart auto-resumes execution."""
    runs_dir = tmp_path / "runs"
    task_id = "task_1"
    ws = init_workspace_layout(task_id, runs_dir)
    (ws / "plan_approved.flag").touch()

    save_checkpoint(
        task_id=task_id,
        stage="plan_approved",
        data={
            "question": "Calculate indices",
            "status": "running",
            "step": "Plan approved — resuming container execution...",
            "plan_approved": True,
        },
        runs_dir=runs_dir,
    )

    tm = TaskManager(auto_approve=False, runs_dir=runs_dir)
    ts = tm.get_task(task_id)

    assert ts is not None
    assert ts.status == "running"
    assert "resuming execution" in ts.step.lower()
    assert tm.active_count() == 1


def test_stac_approved_checkpoint_resumption(tmp_path: Path):
    """Verify that when a task was interrupted midway during STAC downloads,
    server restart restores status as running directly resuming downloads without re-prompting preview."""
    runs_dir = tmp_path / "runs"
    task_id = "task_1"
    ws = init_workspace_layout(task_id, runs_dir)

    # 1. Simulate user approved STAC preview before interrupt
    stac_data = {
        "bbox": [34.2, 31.2, 34.5, 31.5],
        "scenes": [
            {"id": "S2_2020", "collection": "sentinel-2-l2a", "assets": ["B04", "B08"]},
        ],
    }
    (ws / "stac_approved.flag").touch()
    (ws / "stac_approved.json").write_text(json.dumps(stac_data), encoding="utf-8")

    save_checkpoint(
        task_id=task_id,
        stage="stac_approved",
        data={
            "question": "Assess land changes",
            "status": "running",
            "step": "Staging approved STAC scenes at native resolution...",
            "stac_data": stac_data,
        },
        runs_dir=runs_dir,
    )

    # 2. TaskManager restores from disk
    tm = TaskManager(auto_approve=False, runs_dir=runs_dir)
    ts = tm.get_task(task_id)

    assert ts is not None
    assert ts.status == "running"
    assert "satellite image downloads" in ts.step.lower()
    assert ts.stac_preview is None

    # 3. Verify clean_workspace removes stac_approved flags
    clean_workspace(task_id, runs_dir=runs_dir)
    assert not (ws / "stac_approved.flag").exists()
    assert not (ws / "stac_approved.json").exists()


def test_stac_partial_download_does_not_falsely_complete(tmp_path: Path):
    """Verify that when STAC downloading is interrupted with only partial bands downloaded,
    the orchestrator does NOT prematurely treat the partial files as complete inputs."""
    runs_dir = tmp_path / "runs"
    task_id = "task_2"
    ws = init_workspace_layout(task_id, runs_dir)

    # 1. Simulate partial download: only 1 band out of 4 was downloaded
    staged_dir = ws / "staged_inputs"
    staged_dir.mkdir(parents=True, exist_ok=True)
    partial_file = staged_dir / "sentinel-2-l2a_2020-05-30_B02.tif"
    partial_file.write_bytes(b"\x00" * 2000)

    stac_data = {
        "bbox": [34.3, 31.35, 34.55, 31.6],
        "scenes": [
            {
                "collection": "sentinel-2-l2a",
                "datetime": "2020-05-30T00:00:00Z",
                "assets": ["B02", "B03", "B04", "B08"],
            }
        ],
    }
    (ws / "stac_approved.flag").touch()
    (ws / "stac_approved.json").write_text(json.dumps(stac_data), encoding="utf-8")

    save_checkpoint(
        task_id=task_id,
        stage="stac_approved",
        data={
            "question": "Track farmland changes in Gaza",
            "status": "running",
            "step": "Staging approved STAC scenes at native resolution...",
            "stac_data": stac_data,
        },
        runs_dir=runs_dir,
    )

    # 2. TaskManager restores from disk
    tm = TaskManager(auto_approve=False, runs_dir=runs_dir)
    ts = tm.get_task(task_id)

    assert ts is not None
    assert ts.status == "running"
    # ts.files must NOT be locked to just the 1 partial file!
    assert len(ts.files) == 0
    assert "satellite image downloads" in ts.step.lower()




