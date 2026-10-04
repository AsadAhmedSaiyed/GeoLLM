"""Task graph: tasks with dependencies, validated by code."""
import re
from dataclasses import asdict, dataclass, field

PENDING, RUNNING, SUCCESS, FAILED, BLOCKED = "pending", "running", "success", "failed", "blocked"
ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,30}$")
FILE_RE = re.compile(r"^[\w.\-]+$")
MAX_TASKS = 25


@dataclass
class Task:
    id: str
    name: str
    description: str
    type: str = "compute"
    dependencies: list = field(default_factory=list)
    inputs: list = field(default_factory=list)
    expected_outputs: list = field(default_factory=list)
    modules: list = field(default_factory=list)
    parameters: dict = field(default_factory=dict)
    constraints: list = field(default_factory=list)
    must_report: list = field(default_factory=list)
    status: str = PENDING
    attempt: int = 0
    code: str = ""
    artifacts: list = field(default_factory=list)
    result: dict = None
    validation: dict = field(default_factory=dict)
    feedback: list = field(default_factory=list)
    patches: list = field(default_factory=list)
    error: str = None

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(d):
        keys = Task.__dataclass_fields__.keys()
        return Task(**{k: v for k, v in d.items() if k in keys})


def validate_tasks(raw, final_task):
    """Returns a list of problems with a raw task list (empty = valid)."""
    if not isinstance(raw, list) or not raw:
        return ["'tasks' must be a non-empty list"]
    if len(raw) > MAX_TASKS:
        return [f"Too many tasks ({len(raw)}); use at most {MAX_TASKS}."]
    probs, ids = [], []
    for t in raw:
        if not isinstance(t, dict):
            return ["each task must be an object"]
        tid = t.get("id")
        if not isinstance(tid, str) or not ID_RE.match(tid):
            probs.append(f"bad task id {tid!r} (lowercase letters, digits, underscore)")
            continue
        ids.append(tid)
        for k in ("name", "description"):
            if not isinstance(t.get(k), str) or not t[k].strip():
                probs.append(f"task {tid} needs a non-empty '{k}'")
        for o in t.get("expected_outputs") or []:
            if not isinstance(o, str) or not FILE_RE.match(o):
                probs.append(f"task {tid}: expected output {o!r} must be a plain file name (no folders)")
    if len(set(ids)) != len(ids):
        probs.append("task ids must be unique")
    if probs:
        return probs
    deps = {t["id"]: list(t.get("dependencies") or []) for t in raw}
    for tid, ds in deps.items():
        for d in ds:
            if d not in deps:
                probs.append(f"task {tid} depends on unknown task '{d}'")
            if d == tid:
                probs.append(f"task {tid} depends on itself")
    for t in raw:
        for i in t.get("inputs") or []:
            if isinstance(i, str) and ":" in i and i.split(":")[0] not in deps[t["id"]]:
                probs.append(f"task {t['id']}: input '{i}' comes from a task that is not in its dependencies")
    if final_task not in deps:
        probs.append(f"final_task '{final_task}' is not a task id")
    if probs:
        return probs
    indeg = {k: len(v) for k, v in deps.items()}
    queue, seen = [k for k, v in indeg.items() if v == 0], 0
    while queue:
        n = queue.pop()
        seen += 1
        for k, v in deps.items():
            if n in v:
                indeg[k] -= 1
                if indeg[k] == 0:
                    queue.append(k)
    if seen != len(deps):
        probs.append("the task dependencies contain a cycle")
    return probs


class TaskGraph:
    def __init__(self, tasks, final_task):
        self.tasks = {t.id: t for t in tasks}
        self.final_task = final_task

    @staticmethod
    def from_plan(plan):
        return TaskGraph([Task.from_dict(t) for t in plan["tasks"]], plan["final_task"])

    def order(self):
        indeg = {k: len(t.dependencies) for k, t in self.tasks.items()}
        out, ready = [], [k for k in self.tasks if indeg[k] == 0]
        while ready:
            n = ready.pop(0)
            out.append(n)
            for k, t in self.tasks.items():
                if n in t.dependencies:
                    indeg[k] -= 1
                    if indeg[k] == 0:
                        ready.append(k)
        return out

    def needed(self, tid=None):
        """The task and all its ancestors."""
        tid = tid or self.final_task
        out, stack = set(), [tid]
        while stack:
            n = stack.pop()
            if n not in out:
                out.add(n)
                stack.extend(self.tasks[n].dependencies)
        return out

    def deps_ok(self, task):
        return all(self.tasks[d].status == SUCCESS for d in task.dependencies)

    def to_dict(self):
        return {"final_task": self.final_task, "order": self.order(), "tasks": {k: t.to_dict() for k, t in self.tasks.items()}}