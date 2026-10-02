import json
import time
from pathlib import Path

from . import executor, llm, plan as plan_mod, prompts, result_check, validator

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
        f.write(json.dumps(entry) + "\n")


def _classify(res):
    if res["timed_out"]:
        return "timeout"
    if res["oom"]:
        return "out_of_memory"
    if res["exit_code"] != 0:
        lines = res["stderr"].strip().splitlines()
        return "runtime_error:" + (lines[-1].split(":")[0] if lines else "unknown")
    return None


def _apply_overrides(facts, overrides):
    """Roles the user stated explicitly count as found."""
    for f in facts["files"].values():
        if f.get("kind") == "raster":
            for role, n in overrides.items():
                f["band_roles"]["roles"][role] = {"status": "found", "bands": [n], "source": "user"}


def solve(question, files, overrides=None, max_turns=6, explain=True, memory="3g"):
    overrides = overrides or {}
    run_id = time.strftime("%Y%m%d_%H%M%S")
    base = Path("runs") / run_id
    t0, failures = time.time(), []

    def out(status, answer, turns=0, result=None, artifacts=None, run_dir=""):
        _log({"run_id": run_id, "final": status, "turns": turns, "seconds": round(time.time() - t0, 1),
              "provider": llm.PROVIDER, "model": llm.MODEL, "failures": failures})
        return {"status": status, "answer": answer, "turns": turns, "result": result,
                "artifacts": artifacts or [], "run_dir": run_dir, "failures": failures,
                "seconds": round(time.time() - t0, 1)}

    print("[1] Inspecting the files in a container...", flush=True)
    insp = executor.run_code(INSPECT_CODE, files, base / "inspect", memory=memory)
    if insp["exit_code"] != 0 or not insp["result"]:
        failures.append("inspect_failed")
        return out("failed", "Could not inspect the input files:\n" + insp["stderr"][-800:])
    facts = insp["result"]
    errs = {n: f["error"] for n, f in facts["files"].items() if "error" in f}
    if errs and len(errs) == len(facts["files"]):
        return out("refused", "None of the files could be read: " + json.dumps(errs))
    _apply_overrides(facts, overrides)

    messages = [
        {"role": "system", "content": prompts.SYSTEM},
        {"role": "user", "content": f"Dataset facts:\n{json.dumps(facts, indent=1)}\n\nUser question: {question}"
                                    + (f"\n(The user stated these band numbers: {overrides})" if overrides else "")},
    ]
    env = {"GEOLLM_BANDS": json.dumps(overrides)} if overrides else None
    plan, plan_ok, band_errors, last_feedback = None, False, 0, ""
    final, warnings = None, []

    for turn in range(1, max_turns + 1):
        print(f"\n[2] Turn {turn}/{max_turns}: the model is reasoning...", flush=True)
        reply = llm.chat(messages)
        messages.append({"role": "assistant", "content": reply})
        p, code = plan_mod.parse_reply(reply)
        feedback = None

        if not plan_ok:
            issues = plan_mod.check_plan(p, facts, overrides)
            refuse = [m for k, m in issues if k == "refuse"]
            clarify = [m for k, m in issues if k == "clarify"]
            fix = [m for k, m in issues if k == "fix"]
            if refuse:
                failures.append("refused_by_plan_check")
                return out("refused", "Cannot answer this with the given data. " + " ".join(refuse), turn)
            if clarify:
                return out("clarify", " ".join(clarify), turn)
            if fix:
                failures.append("bad_plan")
                feedback = "Plan problems:\n- " + "\n- ".join(fix)
            else:
                plan, plan_ok = p, True
                base.mkdir(parents=True, exist_ok=True)
                (base / "plan.json").write_text(json.dumps(plan, indent=2))

        if feedback is None:
            if code is None:
                failures.append("no_code")
                feedback = "No ```python block found. Reply with one."
            else:
                problems = validator.validate(code)
                if problems:
                    failures.append("validation")
                    feedback = "Code policy violations:\n- " + "\n- ".join(problems) + "\nRewrite the script without them."

        if feedback is None:
            print("[3] Running in a fresh Docker container...", flush=True)
            res = executor.run_code(code, files, base / f"turn_{turn}", memory=memory, env=env)
            print(f"    exit {res['exit_code']}, {res['duration_s']}s, files: {res['artifacts']}", flush=True)
            ftype = _classify(res)
            _log({"run_id": run_id, "turn": turn, "failure_type": ftype, "startup_s": res["startup_s"],
                  "duration_s": res["duration_s"]})
            if ftype:
                failures.append(ftype)
                err = res["stderr"][-1500:]
                if "BandError" in res["stderr"]:
                    band_errors += 1
                    if band_errors >= 2:
                        last = (res["stderr"].strip().splitlines() or [""])[-1]
                        return out("refused", "A required band is missing or ambiguous in this data. " + last, turn)
                    feedback = ("BandError: this is a DATA LIMITATION, not a bug. Do NOT substitute another band. "
                                "If the data cannot support the question, call save_result({'error': ...}).\n" + err)
                else:
                    feedback = f"The script failed ({ftype}).\nstderr:\n{err}"
            elif res["result"] is None:
                feedback = ("The script ran but wrote no result.json, so it was treated as a PROBE. Output:\n"
                            + res["stdout"][-3000:] + "\nNow write the FINAL script (it must call save_result), or another probe.")
            else:
                result = res["result"]
                if isinstance(result, dict) and "error" in result:
                    return out("refused", "Cannot complete this request: " + str(result["error"]), turn, result, res["run_dir"])
                if isinstance(result, dict) and "clarify" in result:
                    return out("clarify", str(result["clarify"]), turn, result, res["run_dir"])
                errors, warnings = result_check.check_result(result, res["run_dir"], res["artifacts"], facts)
                if errors:
                    failures.append("invalid_result")
                    feedback = "Result validation failed:\n- " + "\n- ".join(errors) + "\nFix the script and write a valid final result."
                else:
                    final = res
                    break

        last_feedback = feedback
        messages.append({"role": "user", "content": feedback})
        print(f"    -> sent back to the model: {feedback[:300]}", flush=True)

    if final is None:
        return out("failed", f"No valid final result after {max_turns} turns. Last problem: {last_feedback[:500]}", max_turns)

    result = final["result"]
    if explain:
        print("\n[4] Writing the plain-language answer...", flush=True)
        brief = {n: {"date": f.get("date"), "extent_km2": f.get("extent_km2")}
                 for n, f in facts["files"].items() if f.get("kind") == "raster"}
        payload = {"question": question, "plan_assumptions": (plan or {}).get("assumptions"),
                   "result": result, "warnings": warnings, "files": final["artifacts"], "datasets": brief}
        answer = llm.chat([{"role": "system", "content": prompts.EXPLAIN},
                           {"role": "user", "content": json.dumps(payload)[:12000]}], show=False)
    else:
        answer = json.dumps(result, indent=2)
    return out("ok", answer, turn, result, final["artifacts"], final["run_dir"])