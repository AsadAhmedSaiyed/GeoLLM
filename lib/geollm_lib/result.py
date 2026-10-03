import json
import os
from pathlib import Path

OUT = Path(os.environ.get("GEOLLM_OUTPUT_DIR", "/workspace/output"))
PRIOR = Path(os.environ.get("GEOLLM_PRIOR_DIR", "/workspace/prior"))
INPUT = Path(os.environ.get("GEOLLM_INPUT_DIR", "/workspace/input"))


def _default(o):
    return o.tolist() if hasattr(o, "tolist") else str(o)


def save_result(data: dict):
    """Write result.json (required once per task)."""
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "result.json").write_text(json.dumps(data, indent=2, default=_default))


def output_path(name):
    """Path for a file this task writes."""
    OUT.mkdir(parents=True, exist_ok=True)
    return str(OUT / name)


def input_path(name):
    """Path of an input file by name."""
    return str(INPUT / name)


def prior_path(task_id, name):
    """Path of a file produced by an earlier task this task depends on."""
    p = PRIOR / task_id / name
    if not p.exists():
        have = sorted(x.name for x in (PRIOR / task_id).glob("*")) if (PRIOR / task_id).exists() else []
        raise FileNotFoundError(f"{task_id}/{name} not found. Declared dependency outputs: {have}")
    return str(p)


def prior_result(task_id):
    """result.json (dict) of an earlier task."""
    return json.loads(Path(prior_path(task_id, "result.json")).read_text())