import json
import threading
import time
from pathlib import Path

from harness.pi_harness import solve


class GeoLLMOrchestrator:
    """Runs the Pi + vision sub-agent in the background and exposes its full live state."""

    def __init__(self, on_finish=None):
        self._lock = threading.Lock()
        self.on_finish = on_finish
        self.status, self.step, self.result, self.error = "idle", "", None, None
        self.started = self.ended = None
        self.events, self.state, self.question = [], {}, ""

    def _on_step(self, text):
        with self._lock:
            self.step = text
            self.events.append(f"[{time.strftime('%H:%M:%S')}] {text}")
        print(f"\n[GeoLLM] {text}", flush=True)

    def run_async(self, question, files, **kw):
        with self._lock:
            if self.status == "running":
                return False
            self.status, self.step, self.result, self.error = "running", "starting", None, None
            self.started, self.ended = time.time(), None
            self.events, self.state, self.question = [], {}, question
        threading.Thread(target=self._work, args=(question, files, kw), daemon=True).start()
        return True

    def _work(self, question, files, kw):
        try:
            r = solve(question, files, on_step=self._on_step, state=self.state, **kw)
            with self._lock:
                self.result = r
                self.status = {"ok": "done", "partial": "partial"}.get(r["status"], "failed")
                if self.status != "done":
                    self.error = "; ".join(r["warnings"]) or "run failed"
        except Exception as e:
            with self._lock:
                self.error, self.status = str(e), "failed"
        self.ended = time.time()
        if self.on_finish:
            self.on_finish()

    def outcome_line(self):
        """Honest end-of-run message for the console."""
        r = self.result or {}
        if self.status == "done":
            head = (f"[GeoLLM] RUN SUCCESS | {r.get('attempts')} tool calls, "
                    f"{r.get('seconds')}s")
        elif self.status == "partial":
            head = "[GeoLLM] RUN PARTIAL (outputs exist, but the Pi session ended with a problem)"
        else:
            head = "[GeoLLM] RUN FAILED"
        reasons = r.get("warnings") or ([self.error] if self.error else [])
        lines = [head, f"  run folder: {r.get('run_dir', '')}"]
        lines += [f"  - {w}" for w in reasons]
        return "\n".join(lines)

    def snapshot(self):
        """Full job state as text, given to the main LLM on every message."""
        with self._lock:
            s = dict(self.state)
            elapsed = round((self.ended or time.time()) - self.started, 1) if self.started else 0
            lines = [f"JOB QUESTION: {self.question}",
                     f"JOB STATUS: {self.status}   (running | done | partial | failed)",
                     f"CURRENT STEP: {self.step}",
                     f"ELAPSED: {elapsed}s" + (" (job has ended; this time is final)" if self.ended else ""),
                     f"SANDBOX TOOL CALLS SO FAR: {s.get('tool_calls', 0)}",
                     f"LAST TOOL STATE: {s.get('last_tool', '')}",
                     f"PI LATEST OUTPUT: {s.get('pi_text', '')}",
                     f"INPUT FILE FACTS: {s.get('facts', '')}",
                     "RECENT EVENTS:\n" + "\n".join(self.events[-15:])]
            if self.error:
                lines.append(f"ERROR: {self.error}")
            result = self.result

        live_fn = s.get("pi_live")
        if live_fn:
            try:
                lines.append("PI LIVE: " + json.dumps(live_fn(), default=str))
            except Exception:
                pass

        rd = s.get("run_dir")
        if rd:   # latest record written by the Docker runner, live
            try:
                live = json.loads((Path(rd) / "last_status.json").read_text(encoding="utf-8"))
                lines.append(f"LATEST SANDBOX RESULT: ok={live.get('ok')} "
                             f"message={str(live.get('message', ''))[:400]} "
                             f"artifacts={live.get('artifacts')} warnings={live.get('warnings')}")
            except Exception:
                pass

        if result:
            lines += [f"FINAL STATUS: {result['status']}",
                      f"FINAL ANSWER: {result['answer'][:2500]}",
                      f"VISION CHECKS: {result.get('vision')}",
                      f"WARNINGS: {result['warnings']}",
                      f"FILES ({result['run_dir']}): {result['artifacts']}"]
        return "\n".join(lines)