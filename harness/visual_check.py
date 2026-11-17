"""Visual validation of generated PNG maps by a vision model. Secondary to the numerical checks; never fatal."""
import json
import os
import re
from pathlib import Path

import numpy as np
from matplotlib import image as mpimg

from . import llm, prompts
from .validation.config import get_mode, get_validation_config


def _image_stats(path):
    """Size and how much of the image is one single colour."""
    a = mpimg.imread(str(path))
    h, w = a.shape[:2]
    s = max(1, max(h, w) // 800)
    a = a[::s, ::s]
    rgb = (a[..., :3] if a.ndim == 3 else np.stack([a] * 3, -1))
    q = (np.clip(rgb, 0, 1) * 255).astype(int) // 8
    codes = (q[..., 0] << 10) + (q[..., 1] << 5) + q[..., 2]
    return {
        "width": int(w),
        "height": int(h),
        "dominant_color_fraction": round(float(np.bincount(codes.ravel()).max() / codes.size), 4),
    }


def _parse_json(text):
    """Extract a JSON object from an LLM reply. Returns a dict, or None if none can be parsed."""
    if not text:
        return None
    m = re.search(r"```json\s*\n(.*?)```", text, re.S)
    candidates = [m.group(1)] if m else []
    candidates += re.findall(r"```\s*\n(.*?)```", text, re.S)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for block in candidates:
        try:
            value = json.loads(block.strip())
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(value, dict):
            return value
    return None


def check_images(task, output_dir, pngs, feedback_dir, on_step=None, input_files=None):
    """Returns a list of {file, status: ok|needs_revision|skipped, issues, recommended_action}.

    When ``GEOLLM_VALIDATION_MODE=agentic`` the call is delegated to the
    multi-turn agentic loop in ``harness.validation.agent``.  The legacy
    single-pass path remains the default and is untouched.
    """
    # ---- Phase 3 agentic gate (feature flag) --------------------------------
    # Single source of truth: validation.config.get_mode().  An invalid env
    # value falls back to "legacy" with a warning rather than activating the
    # agentic loop.
    real_inputs = input_files or getattr(task, "input_files", None)
    if get_mode() == "agentic":
        from harness.validation.agent import validate_artifacts
        return validate_artifacts(task, output_dir, pngs, feedback_dir, on_step, input_files=real_inputs)
    # -------------------------------------------------------------------------

    verdicts = []
    Path(feedback_dir).mkdir(parents=True, exist_ok=True)
    step = on_step or (lambda ev: None)
    target_pngs = pngs[:get_validation_config().max_images_per_run]
    total = len(target_pngs)
    mode = get_mode()
    run_root = Path(feedback_dir).parent if feedback_dir else Path(output_dir)
    for i, rel in enumerate(target_pngs):
        if (run_root / "cancelled.flag").exists():
            break
        p = Path(output_dir) / rel
        step({
            "type": "vision_check",
            "image": rel,
            "index": i + 1,
            "total": total,
            "state": "started",
            "mode": mode
        })
        if not llm.vision_available():
            verdicts.append({"file": rel, "status": "skipped", "issues": [], "recommended_action": "no vision model configured"})
            step({
                "type": "vision_check",
                "image": rel,
                "index": i + 1,
                "total": total,
                "state": "done",
                "verdict": "skipped",
                "text": "no vision model configured",
                "mode": mode
            })
            continue
        try:
            stats = _image_stats(p)
            prompt = prompts.VISION + "\n\nTASK: " + task.name + " - " + task.description \
                + "\nEXPECTED OUTPUTS: " + ", ".join(task.expected_outputs) + "\nIMAGE STATS: " + json.dumps(stats)
            raw_reply = llm.chat_vision(prompt, [str(p)])
            v = _parse_json(raw_reply) or {}
            status = v.get("status") if v.get("status") in ("ok", "needs_revision") else "skipped"
            issues = v.get("issues", [])
            recommended = v.get("recommended_action", "")
            verdicts.append({"file": rel, "status": status, "issues": issues,
                             "recommended_action": recommended})
            summary_text = "; ".join(map(str, issues)) if issues else (recommended or status)
            step({
                "type": "vision_check",
                "image": rel,
                "index": i + 1,
                "total": total,
                "state": "done",
                "verdict": status,
                "text": summary_text,
                "mode": mode
            })
        except Exception as e:
            verdicts.append({"file": rel, "status": "skipped", "issues": [], "recommended_action": f"vision call failed: {e}"})
            step({
                "type": "vision_check",
                "image": rel,
                "index": i + 1,
                "total": total,
                "state": "done",
                "verdict": "skipped",
                "text": f"vision call failed: {e}",
                "mode": mode
            })
    feedback_path = Path(feedback_dir) / "visual.json"
    try:
        feedback_path.parent.mkdir(parents=True, exist_ok=True)
        feedback_path.write_text(json.dumps(verdicts, indent=2), encoding="utf-8")
    except Exception as exc:
        import sys
        print(f"[visual_check] WARNING: could not write {feedback_path}: {exc}", file=sys.stderr)
    return verdicts
