"""Persistent run state. runs/<run_id>/state.json is the single source of truth (not the chat history)."""
import json
import time
from pathlib import Path


class RunState:
    def __init__(self, query, files, overrides=None):
        self.run_id = time.strftime("%Y%m%d_%H%M%S")
        self.run_dir = Path("runs") / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.query, self.files, self.overrides = query, [str(f) for f in files], overrides or {}
        self.status = "running"
        self.facts, self.plan, self.graph = None, None, None
        self.decisions, self.failures, self.warnings = [], [], []
        self.attempts_total = 0
        self.final = None
        self.started = time.time()

    def task_dir(self, task_id):
        d = self.run_dir / "tasks" / task_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def decide(self, text):
        self.decisions.append({"t": round(time.time() - self.started, 1), "decision": text})

    def save(self):
        data = {"run_id": self.run_id, "query": self.query, "files": self.files, "status": self.status,
                "overrides": self.overrides, "facts": self.facts, "plan": self.plan,
                "graph": self.graph.to_dict() if self.graph else None, "decisions": self.decisions,
                "failures": self.failures, "warnings": self.warnings, "attempts_total": self.attempts_total,
                "final": self.final, "seconds": round(time.time() - self.started, 1)}
        (self.run_dir / "state.json").write_text(json.dumps(data, indent=2, default=str))