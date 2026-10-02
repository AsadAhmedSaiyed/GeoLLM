"""The LLM's plan: parsed, then checked against the dataset facts by plain code."""
import json
import re

PLAN_KEYS = ("meaning", "measures", "required_roles", "needs_two_dates", "preprocessing", "assumptions", "outputs")
ROLES = ("blue", "green", "red", "nir", "swir1", "swir2")


def parse_reply(text):
    """Returns (plan_dict or None, python_code or None)."""
    plan = None
    m = re.search(r"```json\s*\n(.*?)```", text, re.S)
    if m:
        try:
            plan = json.loads(m.group(1))
        except json.JSONDecodeError:
            plan = None
    c = re.search(r"```python\s*\n(.*?)```", text, re.S)
    if c:
        return plan, c.group(1).strip()
    for block in re.findall(r"```\s*\n(.*?)```", text, re.S):
        if not block.lstrip().startswith("{"):
            return plan, block.strip()
    return plan, None


def check_plan(plan, facts, overrides=None):
    """Returns [(kind, message)], kind in refuse | clarify | fix."""
    if not isinstance(plan, dict):
        return [("fix", "Start your reply with a ```json plan block (keys: " + ", ".join(PLAN_KEYS) + "), then a ```python block.")]
    issues = []
    missing = [k for k in PLAN_KEYS if k not in plan]
    if missing:
        issues.append(("fix", f"The plan is missing keys: {missing}"))
    overrides = overrides or {}
    rasters = {n: f for n, f in facts["files"].items() if f.get("kind") == "raster"}

    for role in plan.get("required_roles") or []:
        if role not in ROLES:
            issues.append(("fix", f"Unknown band role '{role}'. Use only {ROLES}."))
            continue
        if role in overrides:
            continue
        for name, f in rasters.items():
            entry = f["band_roles"]["roles"][role]
            labels = [b.get("label") or "(unlabelled)" for b in f["bands"]]
            if entry["status"] == "missing":
                issues.append(("refuse", f"'{name}' has no '{role}' band (its band labels: {labels}), "
                                         f"which this analysis needs. Provide data with a '{role}' band, "
                                         f"or if the bands are unlabelled, tell me which band number is '{role}'."))
            elif entry["status"] == "ambiguous":
                issues.append(("clarify", f"'{name}' has several possible '{role}' bands {entry['bands']}. Which one should I use?"))

    if plan.get("needs_two_dates"):
        if len(rasters) < 2:
            issues.append(("refuse", "This needs two images of the same area from different dates; only one raster was provided."))
        else:
            dates = [d for d in facts["alignment"]["dates"].values() if d]
            if len(dates) == len(rasters) and len(set(dates)) == 1:
                issues.append(("refuse", "The images have the same acquisition date, so there is no change over time to measure."))

    align = facts["alignment"]
    if len(rasters) >= 2 and align["aligned"] is False:
        steps = " ".join(str(p).lower() for p in plan.get("preprocessing") or [])
        if not any(w in steps for w in ("align", "reproject", "resample", "warp")):
            issues.append(("fix", "The rasters are not on the same grid (" + "; ".join(align["differences"])
                           + "). Add an alignment step to 'preprocessing' (geollm_lib.align.align_to)."))
    return issues