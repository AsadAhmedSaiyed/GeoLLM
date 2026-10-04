"""Visual validation of generated PNG maps by a vision model. Secondary to the numerical checks; never fatal."""
import json
from pathlib import Path

from . import llm, numerical_check, plan as plan_mod, prompts


def check_images(task, output_dir, pngs, feedback_dir):
    """Returns a list of {file, status: ok|needs_revision|skipped, issues, recommended_action}."""
    verdicts = []
    Path(feedback_dir).mkdir(parents=True, exist_ok=True)
    for rel in pngs[:3]:
        p = Path(output_dir) / rel
        if not llm.vision_available():
            verdicts.append({"file": rel, "status": "skipped", "issues": [], "recommended_action": "no vision model configured"})
            continue
        try:
            stats = numerical_check.image_stats(p)
            prompt = prompts.VISION + "\n\nTASK: " + task.name + " - " + task.description \
                + "\nEXPECTED OUTPUTS: " + ", ".join(task.expected_outputs) + "\nIMAGE STATS: " + json.dumps(stats)
            v = plan_mod.parse_json(llm.chat_vision(prompt, [str(p)])) or {}
            status = v.get("status") if v.get("status") in ("ok", "needs_revision") else "skipped"
            verdicts.append({"file": rel, "status": status, "issues": v.get("issues", []),
                             "recommended_action": v.get("recommended_action", "")})
        except Exception as e:
            verdicts.append({"file": rel, "status": "skipped", "issues": [], "recommended_action": f"vision call failed: {e}"})
    (Path(feedback_dir) / "visual.json").write_text(json.dumps(verdicts, indent=2))
    return verdicts