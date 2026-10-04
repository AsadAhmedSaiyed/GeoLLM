"""Orchestrator: inspect -> plan -> task graph -> (generate, validate, run, check, patch) per task -> final checks -> explanation."""
import json
import os
import shutil
import time
from pathlib import Path

from . import (api_doc, artifacts as art, debugger, executor, final_check, graph as G, llm, numerical_check,
               patcher, plan as plan_mod, planner, prompts, result_check, validator, visual_check)
from .state import RunState

INSPECT_CODE = '''
import os
from geollm_lib.indices import describe_indices
from geollm_lib.metadata import inspect_dataset
from geollm_lib.result import save_result
names = sorted(os.listdir("/workspace/input"))
facts = inspect_dataset(["/workspace/input/" + n for n in names])
facts["available_indices"] = describe_indices()
save_result(facts)
'''


def _log(entry):
    Path("runs").mkdir(exist_ok=True)
    with open("runs/log.jsonl", "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def _classify(res):
    if res["timed_out"]:
        return "timeout"
    if res["oom"]:
        return "out_of_memory"
    if res["oversize"]:
        return "output_too_large"
    if res["exit_code"] != 0:
        lines = res["stderr"].strip().splitlines()
        return "runtime_error:" + (lines[-1].split(":")[0] if lines else "unknown")
    return None


def _apply_overrides(facts, overrides):
    for f in facts["files"].values():
        if f.get("kind") == "raster":
            for role, n in overrides.items():
                f["band_roles"]["roles"][role] = {"status": "found", "bands": [n], "source": "user"}


def _generate_code(state, task):
    deps = {}
    for d in task.dependencies:
        dt = state.graph.tasks[d]
        deps[d] = {"name": dt.name, "files": [{"file": a["name"], "type": a["type"], **a["meta"]} for a in dt.artifacts],
                   "result": json.dumps(dt.result, default=str)[:2000]}
    spec = {"id": task.id, "name": task.name, "description": task.description, "inputs": task.inputs,
            "expected_outputs": task.expected_outputs, "parameters": task.parameters, "constraints": task.constraints,
            "must_report": task.must_report, "is_final_task": task.id == state.graph.final_task}
    user = (f"TASK:\n{json.dumps(spec, indent=1)}\n\nPLAN CONTEXT:\nmeaning: {state.plan.get('meaning')}\n"
            f"assumptions: {state.plan.get('assumptions')}\nrequirements: {state.plan.get('requirements')}\n\n"
            f"DEPENDENCY OUTPUTS (read at /workspace/prior/<task_id>/<file>):\n{json.dumps(deps, default=str)}\n\n"
            f"DATASET FACTS:\n{json.dumps(planner.compact_facts(state.facts), separators=(',', ':'))}\n\n"
            f"HELPER API (generated from the real code):\n{api_doc.docs_for(task.modules)}")
    reply = llm.chat([{"role": "system", "content": prompts.CODER}, {"role": "user", "content": user}], show=False)
    return llm.extract_code(reply) or ""


def execute_task(state, task, files, memory, max_attempts, start_code="", seed=""):
    """Run one task with generate / validate / execute / check / patch. Returns {status, message, warnings}."""
    tdir = state.task_dir(task.id)
    prior = {d: str(state.task_dir(d) / "outputs") for d in task.dependencies}
    env = {"GEOLLM_BANDS": json.dumps(state.overrides)} if state.overrides else None
    final = task.id == state.graph.final_task
    timeout = int(os.environ.get("GEOLLM_TASK_TIMEOUT", "300"))
    task.status = G.RUNNING
    code, feedback, band_errors, last_msg = start_code, seed, 0, ""

    for attempt in range(1, max_attempts + 1):
        task.attempt = attempt
        state.attempts_total += 1
        adir = tdir / f"attempt_{attempt}"
        if not code:
            print(f"  [{task.id}] attempt {attempt}/{max_attempts}: writing code...", flush=True)
            code = _generate_code(state, task)
        elif feedback:
            print(f"  [{task.id}] attempt {attempt}/{max_attempts}: patching...", flush=True)
            new, mode, info = patcher.patch(code, feedback)
            task.patches.append({"attempt": attempt, "mode": mode, **info})
            if new is None:
                state.failures.append("patch_failed")
                last_msg = "could not produce a patch"
                continue
            code = new
        task.code = code

        failure, res, warns = None, None, []
        if not code:
            failure = ("no_code", "The reply contained no ```python block.")
        else:
            problems = validator.validate(code)
            if problems:
                failure = ("validation", "\n".join(problems))
            else:
                print(f"  [{task.id}] running in a fresh container...", flush=True)
                res = executor.run_code(code, files, adir, timeout=timeout, memory=memory, env=env, prior=prior)
                ftype = _classify(res)
                _log({"run_id": state.run_id, "task": task.id, "attempt": attempt, "failure_type": ftype,
                      "startup_s": res["startup_s"], "duration_s": res["duration_s"]})
                if ftype:
                    if "BandError" in res["stderr"]:
                        band_errors += 1
                        if band_errors >= 2:
                            last = (res["stderr"].strip().splitlines() or [""])[-1]
                            task.status = G.FAILED
                            return {"status": "refused", "message": "A required band is missing or ambiguous in this data. " + last}
                    failure = ("runtime", ftype + "\n" + res["stderr"][-800:])
                elif res["result"] is None:
                    failure = ("no_result", "The script ran but wrote no result.json.")
                else:
                    result = res["result"]
                    if isinstance(result, dict) and "error" in result:
                        task.status, task.result = G.FAILED, result
                        return {"status": "refused", "message": "Cannot complete this request: " + str(result["error"])}
                    if isinstance(result, dict) and "clarify" in result:
                        task.status = G.FAILED
                        return {"status": "clarify", "message": str(result["clarify"])}
                    errs, warns = result_check.check_result(result, res["output_dir"], res["artifacts"], state.facts,
                                                            final=final, expected_outputs=task.expected_outputs)
                    issues = numerical_check.check_outputs(res["output_dir"], res["artifacts"], result, state.facts)
                    errs += [i["message"] for i in issues if i["severity"] == "error"]
                    warns += [i["message"] for i in issues if i["severity"] == "warning"]
                    cons = plan_mod.check_consistency(task, code, result)
                    if errs:
                        failure = ("numerical", "\n".join(errs))
                    elif cons:
                        failure = ("consistency", "\n".join(cons))
                    else:
                        pngs = [a for a in res["artifacts"] if a.lower().endswith(".png")]
                        verdicts = visual_check.check_images(task, res["output_dir"], pngs, adir / "feedback") if pngs else []
                        bad = [f"{v['file']}: {'; '.join(map(str, v['issues']))} -> {v['recommended_action']}"
                               for v in verdicts if v["status"] == "needs_revision"]
                        task.validation = {"warnings": warns, "visual": verdicts}
                        if bad and attempt < max_attempts:
                            failure = ("visual", "\n".join(bad))
                        elif bad:
                            warns.append("Visual check flagged: " + " | ".join(bad))

        if failure is None:
            shutil.rmtree(tdir / "outputs", ignore_errors=True)
            shutil.copytree(adir / "outputs", tdir / "outputs")
            (tdir / "code.py").write_text(code)
            task.artifacts = [a.to_dict() for a in art.collect(tdir / "outputs", task.id)]
            task.result, task.status = res["result"], G.SUCCESS
            task.validation = {**task.validation, "warnings": warns}
            (tdir / "validation.json").write_text(json.dumps(task.validation, indent=2, default=str))
            print(f"  [{task.id}] OK", flush=True)
            return {"status": "success", "message": "", "warnings": warns}

        kind, msg = failure
        last_msg = f"{kind}: {msg[:300]}"
        state.failures.append(kind)
        task.feedback.append({"attempt": attempt, "kind": kind, "message": msg})
        print(f"  [{task.id}] FAILED ({kind}): {msg[:200]}", flush=True)
        feedback = debugger.build_feedback(task, code, kind, msg, stderr=res["stderr"] if res else "")
        (tdir / "feedback.json").write_text(json.dumps(task.feedback, indent=2, default=str))

    task.status, task.error = G.FAILED, last_msg
    return {"status": "failed", "message": last_msg}


def solve(question, files, overrides=None, max_turns=None, explain=True, memory="3g"):
    """Answer a question about the given files. Returns a dict (status ok|partial|refused|clarify|failed)."""
    overrides = overrides or {}
    max_attempts = max_turns or int(os.environ.get("MAX_TASK_ATTEMPTS", "3"))
    state = RunState(question, files, overrides)

    def out(status, answer, result=None, artifacts=None, warnings=None):
        state.status = status
        state.final = {"status": status, "answer": answer, "result": result}
        state.save()
        secs = round(time.time() - state.started, 1)
        _log({"run_id": state.run_id, "final": status, "attempts": state.attempts_total, "seconds": secs,
              "provider": llm.PROVIDER, "model": llm.MODEL, "failures": state.failures})
        return {"status": status, "answer": answer, "turns": state.attempts_total,
                "tasks": {k: t.status for k, t in state.graph.tasks.items()} if state.graph else {},
                "result": result, "artifacts": artifacts or [], "warnings": warnings or [], "run_dir": str(state.run_dir),
                "failures": state.failures, "seconds": secs}

    print("[1] Inspecting the files in a container...", flush=True)
    insp = executor.run_code(INSPECT_CODE, files, state.run_dir / "inspect", memory=memory)
    if insp["exit_code"] != 0 or not insp["result"]:
        state.failures.append("inspect_failed")
        return out("failed", "Could not inspect the input files:\n" + insp["stderr"][-800:])
    state.facts = insp["result"]
    errs = {n: f["error"] for n, f in state.facts["files"].items() if "error" in f}
    if errs and len(errs) == len(state.facts["files"]):
        return out("refused", "None of the files could be read: " + json.dumps(errs))
    _apply_overrides(state.facts, overrides)
    state.decide(f"dataset: {[(n, f.get('modality', f.get('kind'))) for n, f in state.facts['files'].items()]}")

    print("[2] Planning the task graph...", flush=True)
    p = planner.make_plan(question, state.facts, overrides)
    state.plan = p["plan"]
    if p["status"] != "ok":
        state.failures.append("plan_" + p["status"])
        return out(p["status"], p["message"])
    plan = state.plan
    state.graph = G.TaskGraph.from_plan(plan)
    (state.run_dir / "plan.json").write_text(json.dumps(plan, indent=2))
    state.decide(f"plan: {plan.get('meaning')} | tasks: {state.graph.order()} | assumptions: {plan.get('assumptions')}")
    state.save()

    needed = state.graph.needed()
    print(f"[3] Executing {len(needed)} task(s)...", flush=True)
    for tid in state.graph.order():
        if tid not in needed:
            continue
        task = state.graph.tasks[tid]
        if not state.graph.deps_ok(task):
            task.status = G.BLOCKED
            continue
        print(f" Task {tid}: {task.name}", flush=True)
        r = execute_task(state, task, files, memory, max_attempts)
        state.warnings += r.get("warnings", [])
        state.save()
        if r["status"] in ("refused", "clarify"):
            return out(r["status"], r["message"])
        if r["status"] == "failed":
            for t in state.graph.tasks.values():
                if t.status == G.PENDING and t.id in needed and not state.graph.deps_ok(t):
                    t.status = G.BLOCKED
            report = {k: {"status": t.status, "attempts": t.attempt, "error": t.error} for k, t in state.graph.tasks.items()}
            (state.run_dir / "failure_report.json").write_text(json.dumps(report, indent=2))
            return out("failed", f"Task '{tid}' failed after {max_attempts} attempts: {r['message']}\nSee {state.run_dir}/failure_report.json")

    ft = state.graph.tasks[state.graph.final_task]
    names = [a["name"] for a in ft.artifacts]

    print("[4] Final validation...", flush=True)
    unmet, unchecked = final_check.check_requirements(plan, ft.result, names)
    if explain:
        unmet += final_check.judge(question, ft.result, unchecked)
    if unmet:
        state.failures.append("requirements_unmet")
        seed = debugger.build_feedback(ft, ft.code, "requirements", "Not satisfied: " + "; ".join(unmet))
        r = execute_task(state, ft, files, memory, 2, start_code=ft.code, seed=seed)
        if r["status"] == "success":
            names = [a["name"] for a in ft.artifacts]
            unmet, _ = final_check.check_requirements(plan, ft.result, names)
        if unmet:
            state.warnings.append("Requirements not fully met: " + "; ".join(unmet))

    result = ft.result
    all_files = [f"tasks/{t.id}/outputs/{a['rel']}" for t in state.graph.tasks.values() if t.status == G.SUCCESS and t.id in needed
                 for a in t.artifacts]
    fdir = state.run_dir / "final"
    fdir.mkdir(exist_ok=True)
    if (state.task_dir(ft.id) / "outputs").exists():
        shutil.copytree(state.task_dir(ft.id) / "outputs", fdir / "outputs", dirs_exist_ok=True)

    brief = {n: {"date": f.get("date"), "extent_km2": f.get("extent_km2")} for n, f in state.facts["files"].items() if f.get("kind") == "raster"}
    support = {t.id: t.result for t in state.graph.tasks.values() if t.id in needed and t.id != ft.id and t.result}
    if explain:
        print("[5] Writing the plain-language answer...", flush=True)
        payload = {"question": question, "assumptions": plan.get("assumptions"), "result": result, "supporting_results": support,
                   "warnings": state.warnings, "files": names, "datasets": brief}
        msgs = [{"role": "system", "content": prompts.EXPLAIN}, {"role": "user", "content": json.dumps(payload, default=str)[:14000]}]
        answer = llm.chat(msgs, show=False)
        allowed = [result, support, brief, plan.get("assumptions")]
        bad = final_check.ground_numbers(answer, allowed)
        if bad:
            answer = llm.chat(msgs + [{"role": "assistant", "content": answer},
                                      {"role": "user", "content": f"These numbers are not in the data: {bad}. Rewrite using only numbers from the JSON."}], show=False)
            if final_check.ground_numbers(answer, allowed):
                state.warnings.append("Explanation could not be verified against the data; showing a deterministic summary.")
                answer = final_check.template_answer(result, state.warnings, names)
    else:
        answer = json.dumps(result, indent=2, default=str)
    (fdir / "answer.md").write_text(answer)
    (fdir / "report.json").write_text(json.dumps({"query": question, "tasks": {k: t.status for k, t in state.graph.tasks.items()},
                                                  "warnings": state.warnings, "result": result}, indent=2, default=str))
    return out("partial" if unmet else "ok", answer, result, all_files, state.warnings)