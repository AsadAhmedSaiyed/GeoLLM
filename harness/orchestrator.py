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

    def _on_step(self, task_id: str, text: str, run_id: int):
        ts = self.tasks[task_id]
        with self._lock:
            if ts.run_id != run_id:
                return  # Discard step events from old/cancelled run
            ts.step = text
            ts.events.append(f"[{time.strftime('%H:%M:%S')}] {text}")
        print(f"\n[GeoLLM:{task_id}] {text}", flush=True)

    def _work(self, task_id: str, question: str, files: list, kw: dict, run_id: int):
        ts = self.tasks[task_id]
        try:
            r = solve(
                question, files,
                on_step=lambda text: self._on_step(task_id, text, run_id),
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
        except Exception as e:
            with self._lock:
                if ts.run_id != run_id or ts.error == "Cancelled by user":
                    return
                ts.error = str(e)
                ts.status = "failed"
        ts.ended = time.time()
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
        with self._lock:
            s = dict(ts.state)
            elapsed = round((ts.ended or time.time()) - ts.started, 1) if ts.started else 0
            recent_events = [e for e in ts.events[-5:] if e]
            events_summary = " -> ".join(recent_events) if recent_events else ts.step
            lines = [
                f"[{task_id}] QUESTION: {ts.question}",
                f"[{task_id}] STATUS: {ts.status}",
                f"[{task_id}] CURRENT_STEP: {ts.step}",
                f"[{task_id}] RECENT_ACTIVITY: {events_summary}",
                f"[{task_id}] ELAPSED: {elapsed}s" + (" (finished)" if ts.ended else " (active)"),
                f"[{task_id}] TOOL_CALLS_COMPLETED: {s.get('tool_calls', 0)}",
            ]
            if ts.plan:
                lines.append(f"[{task_id}] PROPOSED_PLAN: {ts.plan[:400]}")
            if ts.error:
                lines.append(f"[{task_id}] ERROR_DETAILS: {ts.error}")
            result = ts.result


        rd = s.get("run_dir")
        if rd:
            try:
                live = json.loads((Path(rd) / "last_status.json").read_text(encoding="utf-8"))
                lines.append(f"[{task_id}] SANDBOX: ok={live.get('ok')} "
                             f"msg={str(live.get('message', ''))[:400]} "
                             f"artifacts={live.get('artifacts')}")
            except Exception:
                pass

        if result:
            lines += [
                f"[{task_id}] FINAL: {result['status']}",
                f"[{task_id}] ANSWER: {result['answer'][:1500]}",
                f"[{task_id}] WARNINGS: {result['warnings']}",
                f"[{task_id}] FILES: {result['artifacts']}",
            ]
        lines.append(f"[{task_id}] EVENTS: " + " | ".join(ts.events[-10:]))
        return "\n".join(lines)

    def multi_snapshot(self) -> str:
        sections = []
        for tid in TASK_IDS:
            ts = self.tasks[tid]
            if ts.status == "idle":
                sections.append(f"[{tid}] IDLE (no job)")
            else:
                sections.append(self.task_snapshot(tid))
        return "\n\n".join(sections)
