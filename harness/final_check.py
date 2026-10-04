"""Final validation: were the requirements met, and does the explanation use only real numbers?"""
import json
import re

from . import llm, plan as plan_mod, prompts

_NUM = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")


def check_requirements(plan, result, artifact_names):
    """Returns (unmet, unchecked): unmet failed a deterministic check, unchecked have no machine-checkable rule."""
    unmet, unchecked = [], []
    for r in plan_mod.normalize_requirements(plan.get("requirements")):
        c = r["check"] if isinstance(r["check"], dict) else None
        if c and "result_key" in c:
            if not plan_mod.has_key(result, c["result_key"]):
                unmet.append(f"{r['text']} (result has no '{c['result_key']}')")
        elif c and "artifact" in c:
            if not any(n.lower().endswith(str(c["artifact"]).lower()) for n in artifact_names):
                unmet.append(f"{r['text']} (no '{c['artifact']}' file was produced)")
        else:
            unchecked.append(r["text"])
    return unmet, unchecked


def judge(question, result, unchecked):
    """LLM judgement for requirements without a machine check. Returns a list of unmet requirement texts."""
    if not unchecked:
        return []
    try:
        reply = llm.chat([{"role": "system", "content": prompts.JUDGE},
                          {"role": "user", "content": json.dumps({"question": question, "result": result, "requirements": unchecked})[:12000]}],
                         show=False)
        v = plan_mod.parse_json(reply) or {}
        return [str(x) for x in v.get("unmet", [])]
    except Exception:
        return []


def _leaves(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _leaves(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _leaves(v)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        yield float(obj)


def ground_numbers(answer, allowed_objs):
    """Numbers in `answer` that do not appear (up to rounding) in the allowed structures."""
    allowed = [v for o in allowed_objs for v in _leaves(o)]
    bad = []
    for m in _NUM.findall(answer):
        try:
            a = float(m.replace(",", ""))
        except ValueError:
            continue
        if (a == int(a) and 1900 <= a <= 2100) or (a == int(a) and abs(a) <= 10):
            continue
        if not any(abs(a - v) <= 1e-6 or any(abs(round(v, d) - a) < 1e-9 for d in range(0, 5)) for v in allowed):
            bad.append(m)
    return bad


def template_answer(result, warnings, files):
    """Deterministic fallback explanation built only from the result."""
    lines = [str(result.get("summary", "Analysis finished."))]
    if result.get("assumptions"):
        lines.append("Assumptions: " + "; ".join(map(str, result["assumptions"])))
    if result.get("thresholds"):
        lines.append("Cutoffs used: " + json.dumps(result["thresholds"]))
    if warnings:
        lines.append("Warnings: " + "; ".join(warnings))
    lines.append("Files: " + ", ".join(files))
    return "\n".join(lines)