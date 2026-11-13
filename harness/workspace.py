"""Workspace lifecycle, folder structure, file locking, and disk cleanup."""
from __future__ import annotations

import contextlib
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Generator, List, Optional


DEFAULT_RUNS_DIR = Path("runs")
MAX_TASKS = 3
TASK_IDS = [f"task_{i+1}" for i in range(MAX_TASKS)]


def get_workspace_dir(task_id: str, runs_dir: Optional[Path] = None) -> Path:
    """Return the canonical fixed directory path for a task slot: runs/task_X."""
    base = runs_dir if runs_dir is not None else DEFAULT_RUNS_DIR
    return base / task_id


def init_workspace_layout(task_id: str, runs_dir: Optional[Path] = None) -> Path:
    """Ensure canonical subdirectories exist: staged_inputs/, scratch/, outputs/."""
    ws = get_workspace_dir(task_id, runs_dir)
    (ws / "staged_inputs").mkdir(parents=True, exist_ok=True)
    (ws / "scratch").mkdir(parents=True, exist_ok=True)
    (ws / "outputs").mkdir(parents=True, exist_ok=True)
    return ws


def clean_workspace(
    task_id: str,
    runs_dir: Optional[Path] = None,
    preserve_outputs: bool = False,
    preserve_staged: bool = False,
) -> bool:
    """Clean scratch, temporary logs, and optionally staged inputs and outputs."""
    ws = get_workspace_dir(task_id, runs_dir)
    if not ws.exists():
        return True

    scratch = ws / "scratch"
    if scratch.exists():
        try:
            shutil.rmtree(scratch)
            scratch.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    if not preserve_staged:
        staged = ws / "staged_inputs"
        if staged.exists():
            try:
                shutil.rmtree(staged)
                staged.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

    if not preserve_outputs:
        outputs = ws / "outputs"
        if outputs.exists():
            try:
                shutil.rmtree(outputs)
                outputs.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
        feedback = ws / "feedback"
        if feedback.exists():
            try:
                shutil.rmtree(feedback)
            except Exception:
                pass
        for ad in ws.glob("attempt_*"):
            try:
                shutil.rmtree(ad)
            except Exception:
                pass

    # Clear transient flags, internal RPC logs, and temporary attempt logs
    for fname in (
        "plan.json",
        "stac_preview.json",
        "stac_approved.flag",
        "stac_approved.json",
        "plan_approved.flag",
        "cancelled.flag",
        "pi_stderr.log",
        "pi_events.jsonl",
        "vision_revision.json",
        "allowed_files.json",
        "last_status.json",
        "terrain_3d.json",
        "lidar_3d.json",
        "orthophoto.png",
    ):
        f = ws / fname
        if f.exists():
            try:
                f.unlink()
            except Exception:
                pass

    if not preserve_outputs:
        for fname in ("terrain_3d.json", "lidar_3d.json", "orthophoto.png"):
            for f in ws.rglob(fname):
                if f.is_file():
                    try:
                        f.unlink()
                    except Exception:
                        pass

    # Clean any lingering temporary download files
    for tmp_file in ws.glob("**/*.tmp"):
        if tmp_file.is_file():
            try:
                tmp_file.unlink()
            except Exception:
                pass

    return True


def promote_outputs(task_id: str, source_dir: Path, runs_dir: Optional[Path] = None) -> List[Path]:
    """Promote verified deliverables from source_dir into the canonical runs/task_X/outputs/ folder."""
    ws = get_workspace_dir(task_id, runs_dir)
    dest_dir = ws / "outputs"
    dest_dir.mkdir(parents=True, exist_ok=True)

    promoted: List[Path] = []
    if not source_dir.exists():
        return promoted

    valid_exts = {".png", ".tif", ".tiff", ".geojson", ".gpkg", ".csv", ".json", ".gif", ".svg"}
    excluded_names = {"stderr.txt", "stdout.txt", "code.py", "script.py", "last_status.json", ".flag"}

    for item in sorted(source_dir.rglob("*")):
        if not item.is_file():
            continue
        if item.suffix.lower() not in valid_exts:
            continue
        if item.name in excluded_names:
            continue

        target = dest_dir / item.name
        try:
            shutil.copy2(item, target)
            promoted.append(target)
        except Exception:
            pass

    return promoted


@contextlib.contextmanager
def acquire_workspace_lock(task_id: str, runs_dir: Optional[Path] = None) -> Generator[bool, None, None]:
    """Acquire an atomic file lock on runs/task_X/task.lock."""
    ws = get_workspace_dir(task_id, runs_dir)
    ws.mkdir(parents=True, exist_ok=True)
    lock_file = ws / "task.lock"

    f = None
    try:
        f = open(lock_file, "a+", encoding="utf-8")
        if sys.platform == "win32":
            import msvcrt
            # Non-blocking lock on first byte
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield True
    except (OSError, IOError):
        yield False
    finally:
        if f is not None:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                f.close()
            except Exception:
                pass


def cleanup_expired_workspaces(runs_dir: Optional[Path] = None, ttl_hours: float = 24.0) -> int:
    """Expire inactive scratch data older than ttl_hours for completed/failed tasks."""
    base = runs_dir if runs_dir is not None else DEFAULT_RUNS_DIR
    cleaned_count = 0
    now = time.time()
    max_age_s = ttl_hours * 3600.0

    for tid in TASK_IDS:
        ws = base / tid
        if not ws.is_dir():
            continue

        # Never touch an actively locked workspace
        with acquire_workspace_lock(tid, base) as locked:
            if not locked:
                continue

            # Check checkpoint last update
            from harness.checkpoint import load_checkpoint
            cp = load_checkpoint(tid, base)
            if cp:
                status = cp.get("status")
                updated_at = cp.get("updated_at", 0)
                # Only clean if terminal state and older than TTL
                if status in ("done", "failed", "partial", "idle") and (now - updated_at) > max_age_s:
                    clean_workspace(tid, base, preserve_outputs=True, preserve_staged=False)
                    cleaned_count += 1
            else:
                # If no checkpoint exists, check directory modification time
                mtime = ws.stat().st_mtime
                if (now - mtime) > max_age_s:
                    clean_workspace(tid, base, preserve_outputs=True, preserve_staged=False)
                    cleaned_count += 1

    return cleaned_count


def append_conversation_turn(
    task_id: str,
    role: str,
    content: str,
    runs_dir: Optional[Path] = None,
    extra: Optional[dict] = None,
) -> None:
    """Appends a turn to runs/task_X/conversation.jsonl so chat history is durable."""
    ws = get_workspace_dir(task_id, runs_dir)
    ws.mkdir(parents=True, exist_ok=True)
    conv_file = ws / "conversation.jsonl"
    turn = {
        "role": role,
        "content": content,
        "timestamp": time.time(),
    }
    if extra:
        turn.update(extra)
    try:
        import json
        with open(conv_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(turn) + "\n")
    except Exception:
        pass


def load_conversation(task_id: str, runs_dir: Optional[Path] = None) -> List[dict]:
    """Loads durable conversation turns for a workspace."""
    ws = get_workspace_dir(task_id, runs_dir)
    conv_file = ws / "conversation.jsonl"
    turns = []
    if not conv_file.is_file():
        return turns
    try:
        import json
        with open(conv_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        turns.append(json.loads(line))
                    except Exception:
                        pass
    except Exception:
        pass
    return turns


