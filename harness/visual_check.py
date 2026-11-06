"""Visual validation of generated PNG maps by a vision model. Secondary to the numerical checks; never fatal."""
import json
import os
from pathlib import Path

from . import llm, numerical_check, plan as plan_mod, prompts
from .validation.config import get_mode, get_validation_config


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
    for i, rel in enumerate(target_pngs):
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
            stats = numerical_check.image_stats(p)
            prompt = prompts.VISION + "\n\nTASK: " + task.name + " - " + task.description \
                + "\nEXPECTED OUTPUTS: " + ", ".join(task.expected_outputs) + "\nIMAGE STATS: " + json.dumps(stats)
            raw_reply = llm.chat_vision(prompt, [str(p)])
            v = plan_mod.parse_json(raw_reply) or {}
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
