"""Multi-task orchestrator: runs up to 3 concurrent Pi sub-agent jobs."""
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from harness.pi_harness import solve


MAX_TASKS = 3
TASK_IDS = [f"task_{i+1}" for i in range(MAX_TASKS)]


@dataclass
class TaskState:
    """Mutable state for one task slot."""
    task_id: str
    status: str = "idle"          # idle | running | pending_approval | done | partial | failed
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
    plan: Optional[str] = None            # Phase 3: holds draft plan markdown
    approval_event: threading.Event = field(default_factory=threading.Event)
    revision_feedback: Optional[str] = None
    auto_approve: bool = False
    run_id: int = 0
    pi_rpc: Optional[object] = field(default=None, repr=False)
    _thread: Optional[threading.Thread] = field(default=None, repr=False)
    _flushed_events: int = field(default=0, repr=False)


def find_artifacts(run_dir) -> list:
    """Find deliverables from the final succeeded attempt only. No duplicates."""
    artifacts = []
    if not run_dir:
        return artifacts
    rd = Path(run_dir)
    if not rd.exists():
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
    if status_data:
        if status_data.get("ok"):
            final_attempt = status_data.get("attempt")
        else:
            # If no attempt succeeded, return an empty list and do not show files from failed attempts
            return []

    # If last_status wasn't there or didn't specify attempt, find highest attempt_XX with outputs
    if final_attempt is None:
        attempts = sorted(rd.glob("attempt_*"), reverse=True)
        for ad in attempts:
            out_dir = ad / "outputs"
            if out_dir.exists() and any(out_dir.iterdir()):
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

    valid_exts = {".png", ".tif", ".tiff", ".geojson", ".csv", ".json", ".gif"}
    excluded_names = {"feedback", "events", "stderr", "stdout", "code.py", "script.py", "last_status", "plan.json", ".flag"}

    candidate_paths = []
    if status_data and status_data.get("ok") and status_data.get("artifacts"):
        for a in status_data["artifacts"]:
            ap = Path(a)
            if ap.exists() and ap.is_file() and ap.parent.resolve() == outputs_dir.resolve():
                candidate_paths.append(ap)

    if not candidate_paths:
        candidate_paths = [p for p in outputs_dir.iterdir() if p.is_file()]

    seen_names = set()
    for p in candidate_paths:
        ext = p.suffix.lower()
        if ext not in valid_exts:
            continue
        if any(x in p.name.lower() for x in excluded_names):
            continue
        if p.name in seen_names:
            continue
        seen_names.add(p.name)

        try:
            rel = p.relative_to(Path.cwd()).as_posix()
        except ValueError:
            parts = p.parts
            idx = parts.index("runs") if "runs" in parts else 0
            rel = "/".join(parts[idx:])

        artifacts.append({
            "name": p.name,
            "url": f"/{rel}",
            "type": "image" if ext == ".png" else "raster" if ext in (".tif", ".tiff") else "file",
            "ext": ext,
            "attempt": final_attempt,
        })

    return artifacts


class TaskManager:
    """Manages up to MAX_TASKS concurrent geospatial analysis jobs."""

    def __init__(self, on_finish: Optional[Callable] = None, auto_approve: bool = False):
        self._lock = threading.Lock()
        self.on_finish = on_finish
        self.auto_approve = auto_approve
        self.tasks: dict[str, TaskState] = {
            tid: TaskState(task_id=tid) for tid in TASK_IDS
        }

    # ---- public API ----

    def submit_task(self, question: str, files: list, **kw) -> Optional[str]:
        """Find a free slot, start the job. Returns task_id or None if all busy."""
        with self._lock:
            for tid in TASK_IDS:
                ts = self.tasks[tid]
                if ts.status in ("idle", "done", "partial", "failed"):
                    ts.run_id += 1
                    current_run_id = ts.run_id
                    ts.status = "running"
                    ts.step = "starting"
                    ts.result = None
                    ts.error = None
                    ts.started = time.time()
                    ts.ended = None
                    ts.events = []
                    ts.event_log = []
                    ts.next_event_id = 1
                    ts._flushed_events = 0
                    ts.state = {}
                    ts.question = question
                    ts.files = list(files)
                    ts.plan = None
                    ts.auto_approve = self.auto_approve
                    ts.approval_event = threading.Event()
                    ts.revision_feedback = None
                    ts.pi_rpc = None
                    t = threading.Thread(
                        target=self._work, args=(tid, question, files, kw, current_run_id), daemon=True
                    )
                    ts._thread = t
                    t.start()
                    return tid
        return None


    def get_task(self, task_id: str) -> Optional[TaskState]:
        return self.tasks.get(task_id)

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for ts in self.tasks.values() if ts.status == "running")

    def cancel_task(self, task_id: str) -> bool:
        ts = self.tasks.get(task_id)
        if not ts or ts.status not in ("running", "pending_approval"):
            return False

        with self._lock:
            ts.error = "Cancelled by user"
            ts.status = "failed"
            ts.ended = time.time()
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
            for c in client.containers.list(filters={"name": f"geollm_{task_id}_"}):
                c.kill()
        except Exception:
            pass

        self._on_step(task_id, {"type": "finish", "task_id": task_id, "status": "failed", "error": "Cancelled by user"}, ts.run_id)

        if self.on_finish:
            self.on_finish(task_id)

        return True


    def cancel_all(self):
        for tid in TASK_IDS:
            self.cancel_task(tid)

    def approve_task(self, task_id: str) -> bool:
        """Phase 3: approve a pending plan."""
        ts = self.tasks.get(task_id)
        if not ts or ts.status != "pending_approval":
            return False
        with self._lock:
            ts.revision_feedback = None
            ts.approval_event.set()
        return True

    def revise_task(self, task_id: str, feedback: str) -> bool:
        """Phase 3: send revision feedback on a plan."""
        ts = self.tasks.get(task_id)
        if not ts or ts.status != "pending_approval":
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
            elif t == "turn":
                step_str = f"Turn {ev_data.get('turn', '')}".strip()
            elif t == "artifacts":
                step_str = f"Generated {len(ev_data.get('artifacts', []))} artifacts"
            elif t == "finish":
                step_str = f"Finished ({ev_data.get('status')})"
            else:
                step_str = str(ev_data.get("step") or ev_data.get("text") or t or "")

            if step_str:
                ts.step = step_str
                ts.events.append(f"[{time.strftime('%H:%M:%S')}] {step_str}")

            # Flush events to runs/<run>/events.jsonl
            rd = ts.state.get("run_dir")
            if rd:
                try:
                    events_file = Path(rd) / "events.jsonl"
                    flushed = getattr(ts, "_flushed_events", 0)
                    to_flush = ts.event_log[flushed:]
                    if to_flush:
                        with open(events_file, "a", encoding="utf-8") as f:
                            for item in to_flush:
                                f.write(json.dumps(item) + "\n")
                        ts._flushed_events = len(ts.event_log)
                except Exception:
                    pass

        if ev_data.get("type") not in ("text", "thinking"):
            print(f"\n[GeoLLM:{task_id}] {ts.step}", flush=True)

    def _work(self, task_id: str, question: str, files: list, kw: dict, run_id: int):
        ts = self.tasks[task_id]
        self._on_step(task_id, {"type": "start", "task_id": task_id, "question": question}, run_id)
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

            # Emit deliverables and finish
            rd = ts.state.get("run_dir") or (r.get("run_dir") if isinstance(r, dict) else None)
            arts = find_artifacts(rd) if rd else []
            if arts:
                self._on_step(task_id, {"type": "artifacts", "task_id": task_id, "artifacts": arts}, run_id)
            self._on_step(task_id, {"type": "finish", "task_id": task_id, "status": ts.status, "error": ts.error}, run_id)

        except Exception as e:
            with self._lock:
                if ts.run_id != run_id or ts.error == "Cancelled by user":
                    return
                ts.error = str(e)
                ts.status = "failed"
            self._on_step(task_id, {"type": "finish", "task_id": task_id, "status": "failed", "error": ts.error}, run_id)

        finally:
            ts.ended = time.time()
            with self._lock:
                rd = ts.state.get("run_dir")
                if rd:
                    try:
                        events_file = Path(rd) / "events.jsonl"
                        flushed = getattr(ts, "_flushed_events", 0)
                        to_flush = ts.event_log[flushed:]
                        if to_flush:
                            with open(events_file, "a", encoding="utf-8") as f:
                                for item in to_flush:
                                    f.write(json.dumps(item) + "\n")
                            ts._flushed_events = len(ts.event_log)
                    except Exception:
                        pass
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

        container_num = {"task_1": 1, "task_2": 2, "task_3": 3}.get(task_id, "?")

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
        for tid in TASK_IDS:
            ts = self.tasks[tid]
            if ts.status == "idle":
                container_num = {"task_1": 1, "task_2": 2, "task_3": 3}.get(tid, "?")
                sections.append(f"--- Container #{container_num} ({tid}) ---\nSTATUS: idle (no job assigned)")
            else:
                sections.append(self.task_snapshot(tid))
        return "\n\n".join(sections)

