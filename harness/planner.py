
"""Question + dataset facts -> validated task graph (a plan)."""

import copy
import json

from . import api_doc, llm, plan as plan_mod, prompts


def compact_facts(facts):
    """Smaller copy of dataset facts for prompts."""

    f = copy.deepcopy(facts)

    for info in f["files"].values():
        if info.get("kind") == "raster":
            roles = info["band_roles"]["roles"]

            info["band_roles"] = {
                "sensor": info["band_roles"]["sensor"],
                "found": {
                    r: v["bands"][0]
                    for r, v in roles.items()
                    if v["status"] == "found"
                },
                "ambiguous": {
                    r: v["bands"]
                    for r, v in roles.items()
                    if v["status"] == "ambiguous"
                },
                "missing": [
                    r
                    for r, v in roles.items()
                    if v["status"] == "missing"
                ],
            }

            if len(json.dumps(info.get("tags", {}))) > 600:
                info.pop("tags", None)

    return f


def make_plan(question, facts, overrides=None, max_tries=3):
    """
    Ask the LLM for a plan and validate it against the dataset facts.

    Returns:
        {
            "status": "ok" | "refused" | "clarify" | "failed",
            "plan": dict | None,
            "message": str,
            "attempts": int
        }
    """

    compact = compact_facts(facts)

    user = (
        f"Dataset facts:\n"
        f"{json.dumps(compact, separators=(',', ':'))}\n\n"
        f"Helper modules (optional building blocks):\n"
        f"{api_doc.module_overview()}\n\n"
        f"User question: {question}"
        + (
            f"\n(The user stated these band numbers: {overrides})"
            if overrides
            else ""
        )
    )

    messages = [
        {
            "role": "system",
            "content": prompts.PLANNER + prompts.KNOWLEDGE,
        },
        {
            "role": "user",
            "content": user,
        },
    ]

    last = ""

    print(
        f"[GeoLLM] Planner prompt prepared "
        f"({len(user)} characters)",
        flush=True,
    )

    for n in range(1, max_tries + 1):

        print(
            f"[GeoLLM] Planner attempt {n}/{max_tries} → calling LLM...",
            flush=True,
        )

        reply = llm.chat(messages, show=False)

        print(
            f"[GeoLLM] Planner attempt {n} ← "
            f"LLM returned ({len(reply)} characters)",
            flush=True,
        )

        # plan.py exposes parse_reply(), not parse_json().
        # parse_reply() returns (plan_dict, python_code).
        plan, _ = plan_mod.parse_reply(reply)

        print(
            f"[GeoLLM] Planner attempt {n} → "
            f"plan parsed: {'yes' if plan is not None else 'no'}",
            flush=True,
        )

        issues = plan_mod.check_plan(
            plan,
            facts,
            overrides,
        )

        refuse = [
            message
            for kind, message in issues
            if kind == "refuse"
        ]

        clarify = [
            message
            for kind, message in issues
            if kind == "clarify"
        ]

        fix = [
            message
            for kind, message in issues
            if kind == "fix"
        ]

        if refuse:
            print(
                f"[GeoLLM] Planner → refusing request",
                flush=True,
            )

            return {
                "status": "refused",
                "plan": plan,
                "message": (
                    "Cannot answer this with the given data. "
                    + " ".join(refuse)
                ),
                "attempts": n,
            }

        if clarify:
            print(
                f"[GeoLLM] Planner → clarification required",
                flush=True,
            )

            return {
                "status": "clarify",
                "plan": plan,
                "message": " ".join(clarify),
                "attempts": n,
            }

        if not fix:
            print(
                f"[GeoLLM] Planner → valid plan received",
                flush=True,
            )

            return {
                "status": "ok",
                "plan": plan,
                "message": "",
                "attempts": n,
            }

        last = "; ".join(fix)

        print(
            f"[GeoLLM] Planner → plan needs correction:",
            flush=True,
        )

        for problem in fix:
            print(
                f"[GeoLLM]     - {problem}",
                flush=True,
            )

        messages += [
            {
                "role": "assistant",
                "content": reply,
            },
            {
                "role": "user",
                "content": (
                    "Plan problems:\n- "
                    + "\n- ".join(fix)
                    + "\nReturn the corrected ```json plan."
                ),
            },
        ]

    print(
        "[GeoLLM] Planner → failed to produce a valid plan",
        flush=True,
    )

    return {
        "status": "failed",
        "plan": None,
        "message": (
            f"Could not produce a valid plan: {last}"
        ),
        "attempts": max_tries,
    }
