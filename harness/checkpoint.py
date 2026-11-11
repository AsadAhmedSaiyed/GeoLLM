"""Atomic step-level checkpointing for GeoLLM tasks."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional


SCHEMA_VERSION = 1

VALID_STAGES = (
    "task_created",
    "stac_search_completed",
    "stac_approved",
    "stac_staged",
    "plan_generated",
    "plan_approved",
    "code_generated",
    "code_executed",
    "vision_validation_started",
    "vision_validation_completed",
    "task_completed",
    "interrupted",
    "failed",
)


def get_checkpoint_path(task_id: str, runs_dir: Optional[Path] = None) -> Path:
    base = runs_dir if runs_dir is not None else Path("runs")
    return base / task_id / "checkpoint.json"


def save_checkpoint(
    task_id: str,
    stage: str,
    data: Optional[Dict[str, Any]] = None,
    runs_dir: Optional[Path] = None,
) -> Path:
    """Atomically write a checkpoint to disk using temporary file replacement."""
    target_path = get_checkpoint_path(task_id, runs_dir)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target_path.parent / "checkpoint.tmp"

    existing = load_checkpoint(task_id, runs_dir) or {}
    stages = existing.get("stages", {})

    now = time.time()
    stages[stage] = {
        "timestamp": now,
        "completed": True,
        "detail": data or {},
    }

    # When saving failure or interruption, preserve the highest stage reached so we can resume!
    effective_stage = stage
    if stage in ("failed", "interrupted"):
        prev_stage = existing.get("current_stage")
        if prev_stage and prev_stage not in ("task_created", "failed", "interrupted"):
            effective_stage = prev_stage

    checkpoint_doc = {
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id,
        "current_stage": effective_stage,
        "updated_at": now,
        "created_at": existing.get("created_at", now),
        "question": (data.get("question") if data and "question" in data else existing.get("question", "")),
        "bbox": (data.get("bbox") if data and "bbox" in data else existing.get("bbox")),
        "files": (data.get("files") if data and "files" in data else existing.get("files", [])),
        "plan": (data.get("plan") if data and "plan" in data else existing.get("plan")),
        "plan_approved": (data.get("plan_approved") if data and "plan_approved" in data else existing.get("plan_approved", False)),
        "staged_inputs": (data.get("staged_inputs") if data and "staged_inputs" in data else existing.get("staged_inputs", [])),
        "attempt": (data.get("attempt") if data and "attempt" in data else existing.get("attempt", 0)),
        "stages": stages,
        "status": (data.get("status") if data and "status" in data else existing.get("status", "running")),
        "current_step": (data.get("step") if data and "step" in data else existing.get("current_step", "")),
        "error": (data.get("error") if data and "error" in data else existing.get("error")),
        "verified_outputs": (data.get("verified_outputs") if data and "verified_outputs" in data else existing.get("verified_outputs", [])),
        "answer": (data.get("answer") if data and "answer" in data else existing.get("answer")),
    }

    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(checkpoint_doc, f, indent=2, default=str)
        f.flush()
        try:
            os.fsync(f.fileno())
        except Exception:
            pass

    # Atomic replace guarantees zero corrupted files on crash
    os.replace(temp_path, target_path)
    return target_path


def load_checkpoint(task_id: str, runs_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Load and parse the checkpoint file for task_id, or None if not found or corrupted."""
    target_path = get_checkpoint_path(task_id, runs_dir)
    if not target_path.is_file():
        return None
    try:
        raw = target_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("task_id") == task_id:
            return data
    except Exception:
        pass
    return None


def verify_checkpoint_files(checkpoint: Dict[str, Any]) -> bool:
    """Verify that staged inputs referenced in checkpoint actually exist on disk."""
    staged = checkpoint.get("staged_inputs") or []
    for f in staged:
        p = Path(f)
        if not p.is_file() or p.stat().st_size == 0:
            return False
    return True


def delete_checkpoint(task_id: str, runs_dir: Optional[Path] = None) -> bool:
    target_path = get_checkpoint_path(task_id, runs_dir)
    try:
        if target_path.exists():
            target_path.unlink()
        temp_path = target_path.parent / "checkpoint.tmp"
        if temp_path.exists():
            temp_path.unlink()
        return True
    except Exception:
        return False

