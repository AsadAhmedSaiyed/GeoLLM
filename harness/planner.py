"""Question + dataset facts -> validated task graph (a plan)."""
import copy
import json

from . import api_doc, llm, plan as plan_mod, prompts


def compact_facts(facts):
    """Smaller copy of the dataset facts for prompts (role summary instead of the full role table)."""
    f = copy.deepcopy(facts)
    for info in f["files"].values():
        if info.get("kind") == "raster":
            roles = info["band_roles"]["roles"]
            info["band_roles"] = {"sensor": info["band_roles"]["sensor"],
                                  "found": {r: v["bands"][0] for r, v in roles.items() if v["status"] == "found"},
                                  "ambiguous": {r: v["bands"] for r, v in roles.items() if v["status"] == "ambiguous"},
                                  "missing": [r for r, v in roles.items() if v["status"] == "missing"]}
            info.pop("tags", None) if len(json.dumps(info.get("tags", {}))) > 600 else None
    return f


def make_plan(question, facts, overrides=None, max_tries=3):
    """Returns {"status": ok|refused|clarify|failed, "plan", "message", "attempts"}."""
    user = (f"Dataset facts:\n{json.dumps(compact_facts(facts), separators=(',', ':'))}\n\n"
            f"Helper modules (optional building blocks):\n{api_doc.module_overview()}\n\nUser question: {question}"
            + (f"\n(The user stated these band numbers: {overrides})" if overrides else ""))
    messages = [{"role": "system", "content": prompts.PLANNER + prompts.KNOWLEDGE}, {"role": "user", "content": user}]
    last = ""
    for n in range(1, max_tries + 1):
        reply = llm.chat(messages, show=False)
        plan = plan_mod.parse_json(reply)
        issues = plan_mod.check_plan(plan, facts, overrides)
        refuse = [m for k, m in issues if k == "refuse"]
        clarify = [m for k, m in issues if k == "clarify"]
        fix = [m for k, m in issues if k == "fix"]
        if refuse:
            return {"status": "refused", "plan": plan, "message": "Cannot answer this with the given data. " + " ".join(refuse), "attempts": n}
        if clarify:
            return {"status": "clarify", "plan": plan, "message": " ".join(clarify), "attempts": n}
        if not fix:
            return {"status": "ok", "plan": plan, "message": "", "attempts": n}
        last = "; ".join(fix)
        messages += [{"role": "assistant", "content": reply},
                     {"role": "user", "content": "Plan problems:\n- " + "\n- ".join(fix) + "\nReturn the corrected ```json plan."}]
    return {"status": "failed", "plan": None, "message": f"Could not produce a valid plan: {last}", "attempts": max_tries}