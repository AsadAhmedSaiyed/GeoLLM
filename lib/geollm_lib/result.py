import json
import os
from pathlib import Path


def _default(o):
    if hasattr(o, "tolist"):
        return o.tolist()
    return str(o)


def save_result(data: dict):
    out = Path(os.environ.get("GEOLLM_OUTPUT_DIR", "/workspace/output"))
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps(data, indent=2, default=_default))