"""Multi-task orchestrator: runs dynamic concurrent Pi sub-agent jobs with resource-aware queueing."""
import json
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from harness.executor import release_container
from harness.pi_harness import solve
from harness.resource_sizer import estimate_job_resources, get_host_budget_gb
from harness.workspace import (
    MAX_TASKS,
    TASK_IDS,
    get_workspace_dir,
    init_workspace_layout,
    clean_workspace,
    promote_outputs,
)
from harness.checkpoint import (
    save_checkpoint,
    load_checkpoint,
    delete_checkpoint,
)

MAX_DYNAMIC_TASKS = 12


def _container_num(task_id: str) -> str:
    m = re.match(r"^task_(\d+)$", str(task_id or ""))
    return m.group(1) if m else "?"


@dataclass
class TaskState:
    """Mutable state for one task slot."""
    task_id: str
    status: str = "idle"          # idle | queued | running | pending_approval | done | partial | failed
    step: str = ""
    result: Optional[dict] = None
    error: Optional[str] = None
    started: Optional[float] = None
    ended: Optional[float] = None
    events: list = field(default_factory=list)
    event_log: list = field(default_factory=list)
    next_event_id: int = 1
    state: dict = field(default_factory=dict)
    question: str = ""
    files: list = field(default_factory=list)
    artifacts: list = field(default_factory=list)
    plan: Optional[str] = None            # Phase 3: holds draft plan markdown
    stac_preview: Optional[dict] = None   # Phase 0: holds STAC preview card data
    approval_event: threading.Event = field(default_factory=threading.Event)
    revision_feedback: Optional[str] = None
    auto_approve: bool = False
    allocated_ram_gb: float = 0.0
    resource_tier: str = ""
    run_id: int = 0
    pi_rpc: Optional[object] = field(default=None, repr=False)
    _thread: Optional[threading.Thread] = field(default=None, repr=False)
    _flushed_events: int = field(default=0, repr=False)


def find_artifacts(run_dir) -> list:
    """Find deliverables from canonical outputs or the final succeeded attempt. No duplicates."""
    artifacts = []
    if not run_dir:
        return artifacts
    rd = Path(run_dir)
    if not rd.exists():
        return artifacts

    valid_exts = {".png", ".tif", ".tiff", ".geojson", ".gpkg", ".csv", ".json", ".gif", ".svg", ".html", ".htm"}
    excluded_names = {"feedback", "events", "stderr", "stdout", "code.py", "script.py", "last_status", "plan.json", "vision_revision.json", ".flag", "checkpoint.json", "task.lock"}

    # Auto-promote any live scratch outputs so deliverables are immediately visible as they are generated
    scratch_outputs = rd / "scratch" / "outputs"
    if scratch_outputs.is_dir() and any(p.is_file() for p in scratch_outputs.iterdir()):
        try:
            promote_outputs(rd.name, scratch_outputs, rd.parent)
        except Exception:
            pass

    # 1. Canonical outputs directory in runs/task_X/outputs
    canonical_outputs = rd / "outputs"
    if canonical_outputs.is_dir() and any(p.is_file() for p in canonical_outputs.iterdir()):
        for p in sorted(canonical_outputs.iterdir()):
            if p.is_file() and p.suffix.lower() in valid_exts and not any(x in p.name.lower() for x in excluded_names):
                try:
                    rel = p.relative_to(Path.cwd()).as_posix()
                except ValueError:
                    parts = p.parts
                    idx = parts.index("runs") if "runs" in parts else 0
                    rel = "/".join(parts[idx:])
                url_with_ts = f"/{rel}"
                try:
                    url_with_ts = f"/{rel}?v={int(p.stat().st_mtime_ns)}"
                except Exception:
                    pass
                artifacts.append({
                    "name": p.name,
                    "url": url_with_ts,
                    "type": "image" if p.suffix.lower() in (".png", ".svg") else "raster" if p.suffix.lower() in (".tif", ".tiff") else "file",
                    "ext": p.suffix.lower(),
                    "attempt": 1,
                    "vision_flagged": False,
                })
        if artifacts:
            return artifacts

    final_attempt = None
    sf = rd / "last_status.json"
    status_data = None
    if sf.exists():
        try:
            status_data = json.loads(sf.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Check if last_status records the final attempt / success
    if status_data and status_data.get("ok"):
        final_attempt = status_data.get("attempt")

    # If last_status wasn't there, didn't specify attempt, or latest attempt failed,
    # find highest attempt_XX with outputs so generated deliverables are always visible
    if final_attempt is None:
        attempts = sorted(rd.glob("attempt_*"), reverse=True)
        for ad in attempts:
            out_dir = ad / "outputs"
            if out_dir.exists() and any(p.is_file() for p in out_dir.iterdir()):
                try:
                    num = int(ad.name.split("_")[-1])
                    final_attempt = num
                    break
                except ValueError:
                    pass

    if final_attempt is None:
        return []

    attempt_str = f"attempt_{int(final_attempt):02d}"
    attempt_dir = rd / attempt_str
    outputs_dir = attempt_dir / "outputs"
    if not outputs_dir.exists():
        return []

    valid_exts = {".png", ".tif", ".tiff", ".geojson", ".csv", ".json", ".gif", ".svg"}
    excluded_names = {"feedback", "events", "stderr", "stdout", "code.py", "script.py", "last_status", "plan.json", "vision_revision.json", ".flag"}

    bad_files = set()
    bad_attempt = None
    unfixed_bad = False
    rev_file = rd / "vision_revision.json"
    if rev_file.exists():
        try:
            rev_data = json.loads(rev_file.read_text(encoding="utf-8"))
            bad_files = {Path(f).name for f in rev_data.get("bad_files", [])}
            bad_attempt = rev_data.get("attempt")
            unfixed_bad = bool(rev_data.get("unfixed", False))
        except Exception:
            pass

    candidate_entries = []  # list of (Path, attempt_num)
    if status_data and status_data.get("ok") and status_data.get("artifacts"):
        for a in status_data["artifacts"]:
            ap = Path(a)
            if ap.exists() and ap.is_file() and ap.parent.resolve() == outputs_dir.resolve():
                candidate_entries.append((ap, int(final_attempt)))

    if not candidate_entries:
        for p in sorted(outputs_dir.iterdir()):
            if p.is_file():
                candidate_entries.append((p, int(final_attempt)))

    # Also retain valid outputs from earlier attempts if the latest attempt only re-generated a subset
    for prev_num in range(int(final_attempt) - 1, 0, -1):
        prev_out = rd / f"attempt_{prev_num:02d}" / "outputs"
        if prev_out.is_dir():
            for p in sorted(prev_out.iterdir()):
                if p.is_file():
                    candidate_entries.append((p, prev_num))

    seen_names = set()
    for p, att_num in candidate_entries:
        ext = p.suffix.lower()
        if ext not in valid_exts:
            continue
        if any(x in p.name.lower() for x in excluded_names):
            continue
        if p.name in seen_names:
            continue
        if p.name in bad_files and not unfixed_bad and (bad_attempt is None or att_num <= int(bad_attempt)):
            continue
        is_flagged = bool(p.name in bad_files and unfixed_bad)
        seen_names.add(p.name)

        try:
            rel = p.relative_to(Path.cwd()).as_posix()
        except ValueError:
            parts = p.parts
            idx = parts.index("runs") if "runs" in parts else 0
            rel = "/".join(parts[idx:])

        # Append file mtime cache-buster so browser never serves stale attempt's GIF or image
        url_with_ts = f"/{rel}"
        try:
            url_with_ts = f"/{rel}?v={int(p.stat().st_mtime_ns)}"
        except Exception:
            pass

        artifacts.append({
            "name": p.name,
            "url": url_with_ts,
            "type": "image" if ext in (".png", ".svg") else "raster" if ext in (".tif", ".tiff") else "file",
            "ext": ext,
            "attempt": att_num,
            "vision_flagged": is_flagged,
        })

    return artifacts


class TaskManager:
    """Manages dynamic concurrent geospatial analysis jobs with resource-aware queueing."""

    def __init__(self, on_finish: Optional[Callable] = None, auto_approve: bool = False, runs_dir: Optional[Path] = None):
        self._lock = threading.Lock()
        self.on_finish = on_finish
        self.auto_approve = auto_approve
        self.runs_dir = runs_dir if runs_dir is not None else Path("runs")
        self._pending_queue: list[tuple[str, str, list, dict, int, float, str]] = []
        # Discover existing task_* directories on disk first so deleted workspaces stay deleted across restarts.
        discovered = []
        if self.runs_dir.is_dir():
            for d in sorted(self.runs_dir.iterdir()):
                if d.is_dir() and re.match(r"^task_(\d+)$", d.name):
                    discovered.append(d.name)
        if discovered:
            initial_ids = sorted(set(["task_1", *discovered]), key=lambda t: int(_container_num(t)) if _container_num(t).isdigit() else 999)
        else:
            initial_ids = list(TASK_IDS)
        self.tasks: dict[str, TaskState] = {
            tid: TaskState(task_id=tid) for tid in initial_ids
        }
        self._restore_from_disk()

    def _restore_from_disk(self):
        """Restore task states and event logs from disk on server startup, and auto-resume incomplete tasks."""
        tasks_to_resume = []
        with self._lock:
            for tid in list(self.tasks.keys()):
                ts = self.tasks[tid]
                ws_dir = get_workspace_dir(tid, self.runs_dir)
                ts.state["run_dir"] = str(ws_dir)

                # 1. Load historical events from events.jsonl FIRST so event_log is available
                events_file = ws_dir / "events.jsonl"
                if events_file.is_file():
                    try:
                        seq_id = 1
                        with open(events_file, "r", encoding="utf-8") as f:
                            for line in f:
                                line = line.strip()
                                if line:
                                    try:
                                        ev = json.loads(line)
                                        raw_id = ev.get("id")
                                        if isinstance(raw_id, int):
                                            seq_id = max(seq_id, raw_id + 1)
                                        else:
                                            try:
                                                ev["id"] = int(raw_id)
                                                seq_id = max(seq_id, ev["id"] + 1)
                                            except (ValueError, TypeError):
                                                ev["id"] = seq_id
                                                seq_id += 1
                                        ts.event_log.append(ev)
                                    except Exception:
                                        pass
                        ts.next_event_id = seq_id
                        ts._flushed_events = len(ts.event_log)
                    except Exception:
                        pass

                # Inspect event log for finish and start events
                last_finish = next(
                    (ev for ev in reversed(ts.event_log) if ev.get("type") == "finish"),
                    None,
                )
                start_ev = next(
                    (ev for ev in ts.event_log if ev.get("type") == "start" and ev.get("question")),
                    None,
                )

                # Inspect disk artifacts
                arts = find_artifacts(ws_dir)

                # Inspect last_status.json
                status_file = ws_dir / "last_status.json"
                last_status_ok = False
                if status_file.is_file():
                    try:
                        sdata = json.loads(status_file.read_text(encoding="utf-8"))
                        last_status_ok = bool(sdata.get("ok"))
                    except Exception:
                        pass

                # Load checkpoint if present
                cp = load_checkpoint(tid, self.runs_dir)
                current_stage = cp.get("current_stage") if cp else None
                status = cp.get("status", "idle") if cp else "idle"
                question = (cp.get("question") if cp else "") or (start_ev.get("question") if start_ev else "")

                # Check if failed or cancelled
                is_cancelled = (ws_dir / "cancelled.flag").exists()
                is_failed = is_cancelled or status == "failed" or current_stage == "failed" or (
                    last_finish is not None and (last_finish.get("status") == "failed" or last_finish.get("ok") is False)
                )

                # Check if ALREADY complete
                has_finish_success = last_finish is not None and (
                    last_finish.get("status") in ("done", "partial") or last_finish.get("ok") is True
                )
                is_already_complete = not is_failed and (
                    current_stage in ("task_completed", "vision_validation_completed")
                    or status in ("done", "partial")
                    or has_finish_success
                    or (bool(arts) and (last_status_ok or current_stage in ("code_executed", "vision_validation_started")))
                )

                if is_failed:
                    ts.status = "failed"
                    ts.question = question
                    ts.step = "Cancelled by user" if is_cancelled else ((cp.get("step") if cp else None) or (last_finish.get("error") if last_finish else "Failed"))
                    ts.error = "Cancelled by user" if is_cancelled else ((cp.get("error") if cp else None) or "Task failed")
                    if arts:
                        ts.artifacts = arts
                    if cp:
                        ts.plan = cp.get("plan")
                        ts.files = cp.get("files", [])
                        ts.started = cp.get("created_at")
                        ts.ended = cp.get("updated_at")

                elif is_already_complete:
                    effective_status = status if status in ("done", "partial") else (
                        last_finish.get("status") if last_finish and last_finish.get("status") in ("done", "partial") else "done"
                    )
                    ts.status = effective_status
                    ts.question = question
                    ts.step = "Completed"
                    if arts:
                        ts.artifacts = arts
                    if cp:
                        ts.plan = cp.get("plan")
                        ts.files = cp.get("files", [])
                        ts.started = cp.get("created_at")
                        ts.ended = cp.get("updated_at")
                        ans = cp.get("answer")
                        if ans:
                            ts.result = {"answer": ans, "run_dir": str(ws_dir), "status": ts.status}
                    # Update checkpoint on disk if it was still at an intermediate stage
                    if current_stage != "task_completed":
                        try:
                            save_checkpoint(tid, "task_completed", {
                                "status": ts.status,
                                "step": "Completed",
                                "question": ts.question,
                                "answer": ts.result.get("answer") if isinstance(ts.result, dict) else None,
                                "plan": ts.plan,
                                "verified_outputs": [a["name"] for a in arts],
                            }, self.runs_dir)
                        except Exception:
                            pass

                elif question:
                    # Interrupted or crashed midway before completion — auto-resume!
                    ts.question = question
                    ts.plan = cp.get("plan") if cp else None
                    ts.files = list(cp.get("files", [])) if cp else []
                    ts.started = (cp.get("created_at") if cp else None) or time.time()
                    ts.run_id += 1
                    current_run_id = ts.run_id
                    ts.approval_event = threading.Event()
                    if arts:
                        ts.artifacts = arts

                    # Re-scan staged inputs on disk only if staging was already completed
                    # (do NOT populate incomplete partial files if interrupted during STAC downloading)
                    staged_dir = ws_dir / "staged_inputs"
                    is_stac_resuming = (ws_dir / "stac_approved.flag").exists() or current_stage == "stac_approved"
                    if staged_dir.is_dir() and not is_stac_resuming:
                        staged_files = [str(p) for p in sorted(staged_dir.glob("*.tif")) if p.stat().st_size > 1000]
                        if staged_files and not ts.files:
                            ts.files = staged_files

                    was_approved = (cp.get("plan_approved", False) if cp else False) or (ws_dir / "plan_approved.flag").exists()
                    if current_stage in ("stac_preview_ready", "stac_search_completed"):
                        ts.status = "pending_stac_approval"
                        ts.step = "STAC satellite preview ready — review required"
                        if cp and cp.get("preview"):
                            ts.stac_preview = cp.get("preview")
                    elif current_stage in ("plan_generated", "plan_ready") and ts.plan:
                        ts.status = "pending_approval"
                        ts.step = "Plan review required"
                    elif current_stage == "stac_approved" or (ws_dir / "stac_approved.flag").exists():
                        ts.status = "running"
                        ts.step = "Resuming satellite image downloads..."
                        tasks_to_resume.append((tid, ts.question, ts.files, current_run_id))
                    elif was_approved:
                        (ws_dir / "plan_approved.flag").touch()
                        ts.status = "running"
                        ts.step = f"Resuming execution from checkpoint ({current_stage or 'plan_approved'})..."
                        tasks_to_resume.append((tid, ts.question, ts.files, current_run_id))
                    else:
                        ts.status = "running"
                        ts.step = f"Resuming task {tid} from checkpoint..."
                        tasks_to_resume.append((tid, ts.question, ts.files, current_run_id))

                # If this task is resuming, mark any trailing finish events in memory as superseded
                # so connected SSE streams do not prematurely terminate historical replay
                if tid in [t[0] for t in tasks_to_resume]:
                    for ev in reversed(ts.event_log):
                        if ev.get("type") == "finish":
                            ev["type"] = "superseded_finish"
                            break

        # OUTSIDE LOCK: Launch auto-resumed background worker threads
        for tid, q, files, run_id in tasks_to_resume:
            print(f"[TaskManager] Auto-resuming task {tid} from disk checkpoint...", flush=True)
            ts = self.tasks[tid]
            t = threading.Thread(
                target=self._work, args=(tid, q, files, {}, run_id), daemon=True
            )
            ts._thread = t
            t.start()

    # ---- public API ----

    def create_task(self) -> Optional[TaskState]:
        """Allocate a new dynamic workspace slot (task_4, task_5, ...) up to MAX_DYNAMIC_TASKS."""
        with self._lock:
            if len(self.tasks) >= MAX_DYNAMIC_TASKS:
                return None
            used_nums = {int(_container_num(tid)) for tid in self.tasks if _container_num(tid).isdigit()}
            n = 1
            while n in used_nums:
                n += 1
            tid = f"task_{n}"
            ts = TaskState(task_id=tid)
            ws_dir = get_workspace_dir(tid, self.runs_dir)
            ts.state["run_dir"] = str(ws_dir)
            init_workspace_layout(tid, self.runs_dir)
            self.tasks[tid] = ts
            return ts

    def delete_task(self, task_id: str) -> bool:
        """Stop any running job/warm container for `task_id` and remove its dynamic slot + folder."""
        if task_id == "task_1":
            return False
        self.cancel_task(task_id)
        release_container(task_id)
        with self._lock:
            if task_id not in self.tasks:
                return False
            self._pending_queue = [item for item in self._pending_queue if item[0] != task_id]
            self.tasks.pop(task_id, None)
        ws_dir = get_workspace_dir(task_id, self.runs_dir)
        if ws_dir.exists():
            lock_file = ws_dir / "task.lock"
            for attempt in range(4):
                try:
                    if lock_file.exists():
                        lock_file.unlink(missing_ok=True)
                    shutil.rmtree(ws_dir)
                    break
                except OSError:
                    if attempt < 3:
                        time.sleep(0.1)
                    else:
                        shutil.rmtree(ws_dir, ignore_errors=True)
        return True

    def capacity(self) -> dict:
        """Return live host RAM budget, allocated RAM, active and queued container counts."""
        budget_gb = get_host_budget_gb()
        with self._lock:
            active_statuses = ("running", "pending_approval", "pending_stac_approval")
            active = sum(1 for ts in self.tasks.values() if ts.status in active_statuses)
            queued = sum(1 for ts in self.tasks.values() if ts.status == "queued")
            allocated = round(
                sum(ts.allocated_ram_gb for ts in self.tasks.values() if ts.status in active_statuses),
                1,
            )
            return {
                "active_containers": active,
                "total_containers": len(self.tasks),
                "max_containers": MAX_DYNAMIC_TASKS,
                "allocated_ram_gb": allocated,
                "budget_ram_gb": budget_gb,
                "queued_count": queued,
            }

    def _drain_queue(self) -> None:
        """Start queued tasks whenever host RAM budget has room."""
        to_launch = []
        budget_gb = get_host_budget_gb()
        with self._lock:
            active_statuses = ("running", "pending_approval", "pending_stac_approval")
            used_gb = sum(ts.allocated_ram_gb for ts in self.tasks.values() if ts.status in active_statuses)
            active_n = sum(1 for ts in self.tasks.values() if ts.status in active_statuses)
            remaining = []
            for item in self._pending_queue:
                tid, question, files, kw, run_id, needed_gb, tier = item
                ts = self.tasks.get(tid)
                if not ts or ts.status != "queued" or ts.run_id != run_id:
                    continue
                if active_n == 0 or (used_gb + needed_gb <= budget_gb):
                    used_gb += needed_gb
                    active_n += 1
                    ts.status = "running"
                    ts.step = f"starting ({tier} · {int(round(needed_gb))}g)"
                    ts.started = time.time()
                    ts.allocated_ram_gb = needed_gb
                    ts.resource_tier = tier
                    to_launch.append((tid, question, files, kw, run_id))
                else:
                    remaining.append(item)
            self._pending_queue = remaining

        for tid, question, files, kw, run_id in to_launch:
            self._on_step(tid, {"type": "status", "status": "running", "step": "Allocated container resources — starting..."}, run_id)
            t = threading.Thread(target=self._work, args=(tid, question, files, kw, run_id), daemon=True)
            self.tasks[tid]._thread = t
            t.start()

    def submit_task(self, question: str, files: list, task_id: Optional[str] = None, **kw) -> Optional[str]:
        """Find a free slot (or use specific task_id), start or queue the job based on host RAM budget."""
        profile = estimate_job_resources(question, files)
        budget_gb = get_host_budget_gb()

        with self._lock:
            if task_id and task_id not in self.tasks and len(self.tasks) < MAX_DYNAMIC_TASKS:
                self.tasks[task_id] = TaskState(task_id=task_id)
            target_ids = [task_id] if task_id and task_id in self.tasks else list(self.tasks.keys())
            for tid in target_ids:
                ts = self.tasks[tid]
                if ts.status in ("idle", "done", "partial", "failed"):
                    ts.run_id += 1
                    current_run_id = ts.run_id
                    ts.result = None
                    ts.error = None
                    ts.started = time.time()
                    ts.ended = None
                    ts.events = []
                    ts.event_log = []
                    ts.next_event_id = 1
                    ts._flushed_events = 0

                    ws_dir = get_workspace_dir(tid, self.runs_dir)
                    ts.state = {"run_dir": str(ws_dir)}
                    init_workspace_layout(tid, self.runs_dir)
                    clean_workspace(tid, self.runs_dir, preserve_outputs=False)

                    # Truncate / recreate events.jsonl for new task
                    events_file = ws_dir / "events.jsonl"
                    try:
                        events_file.write_text("", encoding="utf-8")
                    except Exception:
                        pass

                    ts.question = question
                    ts.files = list(files)
                    ts.plan = None
                    ts.stac_preview = None
                    ts.auto_approve = self.auto_approve
                    ts.approval_event = threading.Event()
                    ts.revision_feedback = None
                    ts.pi_rpc = None

                    active_statuses = ("running", "pending_approval", "pending_stac_approval")
                    used_gb = sum(t_s.allocated_ram_gb for t_s in self.tasks.values() if t_s.status in active_statuses)
                    active_n = sum(1 for t_s in self.tasks.values() if t_s.status in active_statuses)

                    if active_n == 0 or (used_gb + profile.memory_gb <= budget_gb):
                        ts.status = "running"
                        ts.step = f"starting ({profile.tier} · {profile.memory})"
                        ts.allocated_ram_gb = profile.memory_gb
                        ts.resource_tier = profile.tier

                        save_checkpoint(tid, "task_created", {
                            "question": question,
                            "files": files,
                            "status": "running",
                            "step": ts.step,
                            "bbox": kw.get("bbox")
                        }, self.runs_dir)

                        t = threading.Thread(
                            target=self._work, args=(tid, question, files, kw, current_run_id), daemon=True
                        )
                        ts._thread = t
                        t.start()
                    else:
                        ts.status = "queued"
                        ts.step = f"Queued — waiting for free RAM ({profile.memory} needed; {used_gb:.0f}/{budget_gb:.0f} GB in use)"
                        ts.allocated_ram_gb = 0.0
                        ts.resource_tier = profile.tier
                        print(f"[GeoLLM:{tid}] {ts.step}", flush=True)
                        self._pending_queue.append((tid, question, files, kw, current_run_id, profile.memory_gb, profile.tier))
                        self._on_step(tid, {"type": "status", "status": "queued", "step": ts.step}, current_run_id)
                    return tid
        return None


    def get_task(self, task_id: str) -> Optional[TaskState]:
        return self.tasks.get(task_id)

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for ts in self.tasks.values() if ts.status == "running")

    def cancel_task(self, task_id: str) -> bool:
        ts = self.tasks.get(task_id)
        if not ts or ts.status not in ("queued", "running", "pending_approval", "pending_stac_approval"):
            return False

        with self._lock:
            ts.error = "Cancelled by user"
            ts.status = "failed"
            ts.ended = time.time()
            ts.allocated_ram_gb = 0.0
            self._pending_queue = [item for item in self._pending_queue if item[0] != task_id]
            ts.approval_event.set()  # unblock if waiting for approval
            pi = ts.pi_rpc
            rd = ts.state.get("run_dir")

        # OUTSIDE LOCK: Kill disk flag, Pi process, and Docker containers
        if rd:
            try:
                (Path(rd) / "cancelled.flag").touch()
            except Exception:
                pass

        if pi:
            try:
                pi.close()
            except Exception:
                pass

        try:
            import docker
            client = docker.from_env()
            for c in client.containers.list(all=True, filters={"name": f"geollm_{task_id}_"}):
                try:
                    c.kill()
                except Exception:
                    pass
                try:
                    c.remove(force=True)
                except Exception:
                    pass
        except Exception:
            pass

        release_container(task_id)
        self._on_step(task_id, {"type": "finish", "task_id": task_id, "status": "failed", "error": "Cancelled by user"}, ts.run_id)
        save_checkpoint(task_id, "failed", {"status": "failed", "error": "Cancelled by user", "step": "Aborted"}, self.runs_dir)
        self._drain_queue()

        if self.on_finish:
            self.on_finish(task_id)

        return True


    def cancel_all(self):
        for tid in list(self.tasks.keys()):
            self.cancel_task(tid)

    def approve_task(self, task_id: str) -> bool:
        """Approve a pending STAC preview or analysis plan."""
        ts = self.tasks.get(task_id)
        if not ts or ts.status not in ("pending_approval", "pending_stac_approval"):
            return False
        with self._lock:
            ts.revision_feedback = None
            ts.approval_event.set()
        return True

    def revise_task(self, task_id: str, feedback: str) -> bool:
        """Send revision feedback on a pending STAC preview or analysis plan."""
        ts = self.tasks.get(task_id)
        if not ts or ts.status not in ("pending_approval", "pending_stac_approval"):
            return False
        with self._lock:
            ts.revision_feedback = feedback
            ts.approval_event.set()
        return True

    # ---- internal ----

    def _on_step(self, task_id: str, ev, run_id: int):
        ts = self.tasks[task_id]
        with self._lock:
            if ts.run_id != run_id:
                return  # Discard step events from old/cancelled run

            if isinstance(ev, dict):
                ev_data = dict(ev)
            else:
                ev_data = {"type": "status", "status": ts.status, "text": str(ev)}

            ev_data["task_id"] = task_id
            ev_data["id"] = ts.next_event_id
            ts.next_event_id += 1

            ts.event_log.append(ev_data)

            # Update ts.step and ts.events from real event
            t = ev_data.get("type")
            if t == "tool_start":
                step_str = f"Running tool: {ev_data.get('toolName')}"
            elif t == "tool_end":
                step_str = f"Tool {ev_data.get('toolCallId')} finished (exit {ev_data.get('exit_code')})"
            elif t == "vision_check":
                step_str = f"Vision check: {ev_data.get('image')} ({ev_data.get('state')})"
            elif t == "text":
                d = ev_data.get("delta", "")
                step_str = d.strip()[:100] if d.strip() else ts.step
            elif t == "thinking":
                step_str = "Thinking..."
            elif t == "status":
                step_str = ev_data.get("step") or ev_data.get("status") or ts.status
            elif t == "plan_ready":
                step_str = "Plan proposed"
            elif t == "stac_preview_ready":
                step_str = "STAC Satellite Preview Ready"
            elif t == "stac_download_progress":
                step_str = f"Downloading {ev_data.get('filename')} ({ev_data.get('band_index', '?')}/{ev_data.get('total_bands', '?')} · {ev_data.get('band_pct', 0)}%)"
            elif t == "stac_staged":
                step_str = f"Staged {len(ev_data.get('files', []))} native-resolution STAC files"
            elif t == "turn":
                step_str = f"Turn {ev_data.get('turn', '')}".strip()
            elif t == "artifacts":
                step_str = f"Generated {len(ev_data.get('artifacts', []))} artifacts"
            elif t == "start":
                step_str = ev_data.get("step") or ts.step or "Starting analysis"
            elif t == "finish":
                step_str = f"Finished ({ev_data.get('status')})"
            else:
                step_str = str(ev_data.get("step") or ev_data.get("text") or t or "")

            if step_str:
                ts.step = step_str
                if t != "stac_download_progress":
                    ts.events.append(f"[{time.strftime('%H:%M:%S')}] {step_str}")

            # Immediately flush event to events.jsonl (skip transient download progress ticks)
            rd = ts.state.get("run_dir")
            if rd and t != "stac_download_progress":
                try:
                    events_file = Path(rd) / "events.jsonl"
                    with open(events_file, "a", encoding="utf-8") as f:
                        f.write(json.dumps(ev_data) + "\n")
                        f.flush()
                    ts._flushed_events = len(ts.event_log)
                except Exception:
                    pass

        if ev_data.get("type") not in ("text", "thinking", "stac_download_progress"):
            print(f"\n[GeoLLM:{task_id}] {ts.step}", flush=True)

    def _work(self, task_id: str, question: str, files: list, kw: dict, run_id: int):
        ts = self.tasks[task_id]
        with self._lock:
            ts.status = "running"
            ts.error = None
            ts.result = {}
        self._on_step(task_id, {"type": "start", "task_id": task_id, "question": question, "step": ts.step}, run_id)
        # Emit existing deliverables immediately on resume so UI displays them
        rd = ts.state.get("run_dir") or str(self.runs_dir / task_id)
        existing_arts = find_artifacts(rd)
        if existing_arts:
            self._on_step(task_id, {"type": "artifacts", "task_id": task_id, "artifacts": existing_arts}, run_id)
        try:
            r = solve(
                question, files,
                on_step=lambda ev: self._on_step(task_id, ev, run_id),
                state=ts.state,
                task_id=task_id,
                task_state=ts,
                **kw,
            )
            with self._lock:
                if ts.run_id != run_id or ts.error == "Cancelled by user":
                    return
                ts.result = r
                ts.status = {"ok": "done", "partial": "partial"}.get(r["status"], "failed")
                if ts.status != "done":
                    ts.error = "; ".join(r["warnings"]) or "run failed"

            # Promote scratch deliverables to canonical outputs/
            rd = ts.state.get("run_dir") or (r.get("run_dir") if isinstance(r, dict) else None)
            if rd:
                scratch_out = Path(rd) / "scratch" / "outputs"
                if scratch_out.is_dir():
                    promote_outputs(task_id, scratch_out, self.runs_dir)

            # Emit deliverables and finish
            arts = find_artifacts(rd) if rd else []
            if arts:
                self._on_step(task_id, {"type": "artifacts", "task_id": task_id, "artifacts": arts}, run_id)
            self._on_step(task_id, {"type": "finish", "task_id": task_id, "status": ts.status, "ok": ts.status in ("done", "partial"), "error": ts.error}, run_id)

        except Exception as e:
            with self._lock:
                if ts.run_id != run_id or ts.error == "Cancelled by user":
                    return
                ts.error = str(e)
                ts.status = "failed"
            rd = ts.state.get("run_dir")
            if rd:
                scratch_out = Path(rd) / "scratch" / "outputs"
                if scratch_out.is_dir():
                    promote_outputs(task_id, scratch_out, self.runs_dir)
                arts = find_artifacts(rd)
                if arts:
                    self._on_step(task_id, {"type": "artifacts", "task_id": task_id, "artifacts": arts}, run_id)
            self._on_step(task_id, {"type": "finish", "task_id": task_id, "status": "failed", "ok": False, "error": ts.error}, run_id)

        finally:
            with self._lock:
                ts.ended = time.time()
                ts.allocated_ram_gb = 0.0
            rd = ts.state.get("run_dir")
            if rd:
                # Also promote if any outputs exist in scratch
                scratch_out = Path(rd) / "scratch" / "outputs"
                if scratch_out.is_dir():
                    promote_outputs(task_id, scratch_out, self.runs_dir)
                ans = ts.result.get("answer") if isinstance(ts.result, dict) else None
                arts = find_artifacts(rd)
                is_completed = ts.status in ("done", "partial")
                stage_name = "task_completed" if is_completed else "interrupted"
                save_checkpoint(task_id, stage_name, {
                    "status": ts.status,
                    "step": "Completed" if is_completed else ts.step,
                    "answer": ans,
                    "error": ts.error,
                    "plan": ts.plan,
                    "plan_approved": (Path(rd) / "plan_approved.flag").exists(),
                    "verified_outputs": [a["name"] for a in arts]
                }, self.runs_dir)

            self._drain_queue()
            if self.on_finish:
                self.on_finish(task_id)


    # ---- reporting ----

    def outcome_line(self, task_id: str) -> str:
        ts = self.tasks.get(task_id)
        if not ts:
            return f"[GeoLLM] Unknown task: {task_id}"
        r = ts.result or {}
        if ts.status == "done":
            head = (f"[GeoLLM:{task_id}] RUN SUCCESS | {r.get('attempts')} tool calls, "
                    f"{r.get('seconds')}s")
        elif ts.status == "partial":
            head = f"[GeoLLM:{task_id}] RUN PARTIAL"
        else:
            head = f"[GeoLLM:{task_id}] RUN FAILED"
        reasons = r.get("warnings") or ([ts.error] if ts.error else [])
        lines = [head, f"  run folder: {r.get('run_dir', '')}"]
        lines += [f"  - {w}" for w in reasons]
        return "\n".join(lines)

    def task_snapshot(self, task_id: str) -> str:
        ts = self.tasks.get(task_id)
        if not ts:
            return f"[{task_id}] UNKNOWN"

        container_num = _container_num(task_id)

        with self._lock:
            s = dict(ts.state)
            elapsed = round((ts.ended or time.time()) - ts.started, 1) if ts.started else 0
            elapsed_str = f"{int(elapsed//60)}m {int(elapsed%60)}s" if elapsed >= 60 else f"{int(elapsed)}s"
            tool_calls = s.get('tool_calls', 0)

            # Build human-readable recent activity from raw events
            recent_events = [e for e in ts.events[-8:] if e]
            clean_events = []
            for ev in recent_events:
                import re
                clean = re.sub(r'\[\d{1,2}:\d{2}:\d{2}\]\s*', '', ev).strip()
                if clean:
                    clean_events.append(clean)
            activity_trail = " → ".join(clean_events) if clean_events else ts.step

            # Set current_action from latest real event and STATUS only from ts.status
            current_action = ts.step or "idle"

            lines = [
                f"--- Container #{container_num} ({task_id}) ---",
                f"TASK: {ts.question}",
                f"STATUS: {ts.status}",
                f"WHAT IT'S DOING NOW: {current_action}",
                f"CODE EXECUTIONS COMPLETED: {tool_calls}",
                f"ELAPSED TIME: {elapsed_str}" + (" (finished)" if ts.ended else " (still working)"),
                f"ACTIVITY TRAIL: {activity_trail}",
            ]
            if ts.plan:
                lines.append(f"PROPOSED_PLAN: {ts.plan[:400]}")
            if ts.error:
                lines.append(f"ERROR: {ts.error}")
            result = ts.result

        rd = s.get("run_dir")
        if rd:
            try:
                live = json.loads((Path(rd) / "last_status.json").read_text(encoding="utf-8"))
                artifacts_list = live.get('artifacts', [])
                if artifacts_list:
                    artifact_names = [Path(a).name if isinstance(a, str) else str(a) for a in artifacts_list]
                    lines.append(f"OUTPUT FILES PRODUCED: {', '.join(artifact_names)}")
                sandbox_msg = str(live.get('message', ''))[:400]
                if sandbox_msg:
                    lines.append(f"SANDBOX RESULT: {'Success' if live.get('ok') else 'Failed'} — {sandbox_msg}")
            except Exception:
                pass

        if result:
            lines += [
                f"FINAL STATUS: {result['status']}",
                f"AGENT'S SUMMARY: {result['answer'][:1500]}",
            ]
            if result.get('warnings'):
                lines.append(f"WARNINGS: {'; '.join(str(w) for w in result['warnings'][:3])}")
            if result.get('artifacts'):
                file_names = [Path(a).name if isinstance(a, str) else str(a) for a in result['artifacts']]
                lines.append(f"DELIVERABLES: {', '.join(file_names)}")

        return "\n".join(lines)

    def multi_snapshot(self) -> str:
        sections = []
        with self._lock:
            tids = list(self.tasks.keys())
        for tid in tids:
            ts = self.tasks.get(tid)
            if not ts:
                continue
            if ts.status == "idle":
                container_num = _container_num(tid)
                sections.append(f"--- Container #{container_num} ({tid}) ---\nSTATUS: idle (no job assigned)")
            else:
                sections.append(self.task_snapshot(tid))
        return "\n\n".join(sections)

