"""Orchestrator: inspect -> plan -> task graph -> (generate, validate, run, check, patch)
per task -> final checks -> explanation.
"""

import json
import os
import shutil
import time
from pathlib import Path

from . import (
    api_doc,
    artifacts as art,
    debugger,
    executor,
    final_check,
    graph as G,
    llm,
    numerical_check,
    patcher,
    plan as plan_mod,
    planner,
    prompts,
    result_check,
    validator,
    visual_check,
)
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


def _progress(message):
    """Print live GeoLLM progress to the terminal."""
    print(f"[GeoLLM] {message}", flush=True)


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
                f["band_roles"]["roles"][role] = {
                    "status": "found",
                    "bands": [n],
                    "source": "user",
                }


def _previous_attempts(task):
    """Compact history of earlier failures and repairs for the repair model."""
    history = []

    for fb in task.feedback:
        history.append(
            {
                "attempt": fb.get("attempt"),
                "failure_kind": fb.get("kind"),
                "failure_message": str(fb.get("message", ""))[:1500],
            }
        )

    for p in task.patches:
        history.append(
            {
                "attempt": p.get("attempt"),
                "repair_mode": p.get("mode"),
                "changed_lines": p.get("changed_lines"),
                "repair_error": p.get("reason"),
            }
        )

    return history


def _build_patch_context(state, task, code, feedback):
    """Structured context handed to patcher.patch()."""
    return {
        "task": task,
        "current_code": code,
        "failure": feedback,
        "dataset_facts": planner.compact_facts(state.facts),
        "capabilities": api_doc.docs_for(task.modules),
        "previous_attempts": _previous_attempts(task),
        "attempt_number": task.attempt,
        "repeated_failure": (
            len(task.feedback) >= 2
            and task.feedback[-1]["message"] == task.feedback[-2]["message"]
        ),
    }


def _generate_code(state, task):
    """Ask the coder LLM to generate code for one task."""

    deps = {}

    for d in task.dependencies:
        dt = state.graph.tasks[d]

        deps[d] = {
            "name": dt.name,
            "files": [
                {
                    "file": a["name"],
                    "type": a["type"],
                    **a["meta"],
                }
                for a in dt.artifacts
            ],
            "result": json.dumps(dt.result, default=str)[:2000],
        }

    spec = {
        "id": task.id,
        "name": task.name,
        "description": task.description,
        "inputs": task.inputs,
        "expected_outputs": task.expected_outputs,
        "parameters": task.parameters,
        "constraints": task.constraints,
        "must_report": task.must_report,
        "is_final_task": task.id == state.graph.final_task,
    }

    user = (
        f"TASK:\n{json.dumps(spec, indent=1)}\n\n"
        f"PLAN CONTEXT:\n"
        f"meaning: {state.plan.get('meaning')}\n"
        f"assumptions: {state.plan.get('assumptions')}\n"
        f"requirements: {state.plan.get('requirements')}\n\n"
        f"DEPENDENCY OUTPUTS "
        f"(read at /workspace/prior/<task_id>/<file>):\n"
        f"{json.dumps(deps, default=str)}\n\n"
        f"DATASET FACTS:\n"
        f"{json.dumps(planner.compact_facts(state.facts), separators=(',', ':'))}\n\n"
        f"AVAILABLE CAPABILITIES\n\n"
        f"The following API documentation is generated automatically from the "
        f"actual geollm_lib source code.\n\n"
        f"Treat signatures and documentation as authoritative.\n\n"
        f"Do not guess function signatures or argument types.\n\n"
        f"Helpers are optional:\n"
        f"- use a helper when useful\n"
        f"- combine helpers with standard Python/geospatial libraries\n"
        f"- implement the operation directly with allowed libraries "
        f"when appropriate\n\n"
        f"Do not assume that a file path is equivalent to an opened dataset "
        f"object. Follow the documented argument requirements.\n"
        f"Do not invent geollm_lib APIs.\n\n"
        f"{api_doc.docs_for(task.modules)}\n"
    )

    _progress(f"TASK {task.id} → sending task to coder LLM...")

    reply = llm.chat(
        [
            {"role": "system", "content": prompts.CODER},
            {"role": "user", "content": user},
        ],
        show=False,
    )

    code = llm.extract_code(reply) or ""

    if code:
        _progress(
            f"TASK {task.id} → code generated "
            f"({len(code.splitlines())} lines)"
        )
    else:
        _progress(f"TASK {task.id} → coder returned no Python code")

    return code


def execute_task(
    state,
    task,
    files,
    memory,
    max_attempts,
    start_code="",
    seed="",
):
    """
    Run one task with:

    generate -> validate -> execute -> result checks ->
    numerical checks -> visual checks ->
    debugger feedback -> patch_context -> patcher.patch() ->
    (focused patch | complete rewrite) -> validate -> execute again.
    """

    tdir = state.task_dir(task.id)

    prior = {
        d: str(state.task_dir(d) / "outputs")
        for d in task.dependencies
    }

    env = (
        {"GEOLLM_BANDS": json.dumps(state.overrides)}
        if state.overrides
        else None
    )

    final = task.id == state.graph.final_task
    timeout = int(os.environ.get("GEOLLM_TASK_TIMEOUT", "300"))

    task.status = G.RUNNING

    code = start_code
    feedback = seed
    last_msg = ""

    for attempt in range(1, max_attempts + 1):
        task.attempt = attempt
        state.attempts_total += 1

        adir = tdir / f"attempt_{attempt}"

        _progress(
            f"TASK {task.id} [{task.name}] "
            f"→ attempt {attempt}/{max_attempts}"
        )

        # ------------------------------------------------------------
        # CODE GENERATION / PATCHING
        # ------------------------------------------------------------

        if not code:
            _progress(f"TASK {task.id} → generating code...")
            code = _generate_code(state, task)

        elif feedback:
            _progress(
                f"TASK {task.id} → repairing code "
                f"using previous failure feedback..."
            )

            patch_context = _build_patch_context(
                state,
                task,
                code,
                feedback,
            )

            patched_code, patch_mode, patch_info = patcher.patch(
                patch_context
            )

            task.patches.append(
                {
                    "attempt": attempt,
                    "mode": patch_mode,
                    **patch_info,
                }
            )

            if patched_code is None:
                _progress(
                    f"TASK {task.id} → repair generation FAILED"
                )

                state.failures.append("patch_failed")
                last_msg = (
                    "could not produce a patch or rewrite: "
                    + str(patch_info.get("reason", "unknown"))
                )
                continue

            code = patched_code

            _progress(
                f"TASK {task.id} → repair generated "
                f"(mode={patch_mode})"
            )

        task.code = code

        # ------------------------------------------------------------
        # CODE VALIDATION
        # ------------------------------------------------------------

        failure = None
        res = None
        warns = []

        if not code:
            _progress(
                f"TASK {task.id} → FAILED: no code returned"
            )

            failure = (
                "no_code",
                "The reply contained no ```python block.",
            )

        else:
            _progress(
                f"TASK {task.id} → validating generated code..."
            )

            problems = validator.validate(code)

            if problems:
                _progress(
                    f"TASK {task.id} → code validation FAILED "
                    f"({len(problems)} problem(s))"
                )

                failure = (
                    "validation",
                    "\n".join(problems),
                )

            else:
                _progress(
                    f"TASK {task.id} → code validation OK"
                )

                # ----------------------------------------------------
                # DOCKER EXECUTION
                # ----------------------------------------------------

                _progress(
                    f"TASK {task.id} → running in fresh Docker container..."
                )

                res = executor.run_code(
                    code,
                    files,
                    adir,
                    timeout=timeout,
                    memory=memory,
                    env=env,
                    prior=prior,
                )

                _progress(
                    f"TASK {task.id} → Docker finished "
                    f"(exit={res['exit_code']}, "
                    f"time={res['duration_s']}s)"
                )

                ftype = _classify(res)

                _log(
                    {
                        "run_id": state.run_id,
                        "task": task.id,
                        "attempt": attempt,
                        "failure_type": ftype,
                        "startup_s": res["startup_s"],
                        "duration_s": res["duration_s"],
                    }
                )

                # ----------------------------------------------------
                # RUNTIME FAILURE
                # (no hardcoded BandError handling: every runtime error,
                #  including band problems, goes through the debugger and
                #  the repair model, which may report the limitation via
                #  the result protocol if the data cannot support the task)
                # ----------------------------------------------------

                if ftype:
                    _progress(
                        f"TASK {task.id} → execution FAILED: {ftype}"
                    )
                    failure = (
                        "runtime",
                        ftype + "\n" + res["stderr"][-800:],
                    )

                # ----------------------------------------------------
                # NO RESULT
                # ----------------------------------------------------

                elif res["result"] is None:
                    _progress(
                        f"TASK {task.id} → execution succeeded "
                        f"but no result.json was produced"
                    )

                    failure = (
                        "no_result",
                        "The script ran but wrote no result.json.",
                    )

                else:
                    result = res["result"]

                    # ------------------------------------------------
                    # AGENT-REPORTED ERROR
                    # ------------------------------------------------

                    if isinstance(result, dict) and "error" in result:
                        _progress(
                            f"TASK {task.id} → task reported an error"
                        )

                        task.status = G.FAILED
                        task.result = result

                        return {
                            "status": "refused",
                            "message": (
                                "Cannot complete this request: "
                                + str(result["error"])
                            ),
                        }

                    # ------------------------------------------------
                    # AGENT-REPORTED CLARIFICATION
                    # ------------------------------------------------

                    if isinstance(result, dict) and "clarify" in result:
                        _progress(
                            f"TASK {task.id} → clarification required"
                        )

                        task.status = G.FAILED

                        return {
                            "status": "clarify",
                            "message": str(result["clarify"]),
                        }

                    # ------------------------------------------------
                    # RESULT STRUCTURE CHECK
                    # ------------------------------------------------

                    _progress(
                        f"TASK {task.id} → checking result structure..."
                    )

                    errs, warns = result_check.check_result(
                        result,
                        res["output_dir"],
                        res["artifacts"],
                        state.facts,
                        final=final,
                        expected_outputs=task.expected_outputs,
                    )

                    _progress(
                        f"TASK {task.id} → result check complete "
                        f"({len(errs)} error(s), "
                        f"{len(warns)} warning(s))"
                    )

                    # ------------------------------------------------
                    # NUMERICAL CHECK
                    # ------------------------------------------------

                    _progress(
                        f"TASK {task.id} → running numerical validation..."
                    )

                    issues = numerical_check.check_outputs(
                        res["output_dir"],
                        res["artifacts"],
                        result,
                        state.facts,
                    )

                    numerical_errors = [
                        i["message"]
                        for i in issues
                        if i["severity"] == "error"
                    ]

                    numerical_warnings = [
                        i["message"]
                        for i in issues
                        if i["severity"] == "warning"
                    ]

                    errs += numerical_errors
                    warns += numerical_warnings

                    _progress(
                        f"TASK {task.id} → numerical validation complete "
                        f"({len(numerical_errors)} error(s), "
                        f"{len(numerical_warnings)} warning(s))"
                    )

                    # ------------------------------------------------
                    # VALIDATION DECISION
                    # ------------------------------------------------

                    if errs:
                        failure = (
                            "numerical",
                            "\n".join(errs),
                        )

                    else:
                        # --------------------------------------------
                        # VISUAL VALIDATION
                        # --------------------------------------------

                        pngs = [
                            a
                            for a in res["artifacts"]
                            if a.lower().endswith(".png")
                        ]

                        if pngs:
                            _progress(
                                f"TASK {task.id} → visual validation "
                                f"({len(pngs)} image(s))..."
                            )

                            verdicts = visual_check.check_images(
                                task,
                                res["output_dir"],
                                pngs,
                                adir / "feedback",
                            )

                            for verdict in verdicts:
                                _progress(
                                    f"TASK {task.id} → visual check "
                                    f"{verdict['file']}: "
                                    f"{verdict['status']}"
                                )

                        else:
                            _progress(
                                f"TASK {task.id} → no PNG output; "
                                f"visual validation skipped"
                            )

                            verdicts = []

                        bad = [
                            (
                                f"{v['file']}: "
                                f"{'; '.join(map(str, v['issues']))} "
                                f"-> {v['recommended_action']}"
                            )
                            for v in verdicts
                            if v["status"] == "needs_revision"
                        ]

                        task.validation = {
                            "warnings": warns,
                            "visual": verdicts,
                        }

                        if bad and attempt < max_attempts:
                            _progress(
                                f"TASK {task.id} → visual validation "
                                f"requires revision"
                            )

                            failure = (
                                "visual",
                                "\n".join(bad),
                            )

                        elif bad:
                            warns.append(
                                "Visual check flagged: "
                                + " | ".join(bad)
                            )

        # ------------------------------------------------------------
        # SUCCESS
        # ------------------------------------------------------------

        if failure is None:
            shutil.rmtree(
                tdir / "outputs",
                ignore_errors=True,
            )

            shutil.copytree(
                adir / "outputs",
                tdir / "outputs",
            )

            (tdir / "code.py").write_text(code)

            task.artifacts = [
                a.to_dict()
                for a in art.collect(
                    tdir / "outputs",
                    task.id,
                )
            ]

            task.result = res["result"]
            task.status = G.SUCCESS

            task.validation = {
                **task.validation,
                "warnings": warns,
            }

            (tdir / "validation.json").write_text(
                json.dumps(
                    task.validation,
                    indent=2,
                    default=str,
                )
            )

            _progress(
                f"TASK {task.id} → SUCCESS"
            )

            if task.artifacts:
                _progress(
                    f"TASK {task.id} → artifacts: "
                    + ", ".join(
                        a["name"]
                        for a in task.artifacts
                    )
                )

            return {
                "status": "success",
                "message": "",
                "warnings": warns,
            }

        # ------------------------------------------------------------
        # FAILURE + DEBUG FEEDBACK
        # (next loop iteration builds patch_context from this feedback
        #  and calls patcher.patch(patch_context))
        # ------------------------------------------------------------

        kind, msg = failure

        last_msg = f"{kind}: {msg[:300]}"

        state.failures.append(kind)

        task.feedback.append(
            {
                "attempt": attempt,
                "kind": kind,
                "message": msg,
            }
        )

        _progress(
            f"TASK {task.id} → FAILED [{kind}]"
        )

        _progress(
            f"TASK {task.id} → preparing debugger feedback..."
        )

        feedback = debugger.build_feedback(
            task,
            code,
            kind,
            msg,
            stderr=res["stderr"] if res else "",
        )

        (tdir / "feedback.json").write_text(
            json.dumps(
                task.feedback,
                indent=2,
                default=str,
            )
        )

        _progress(
            f"TASK {task.id} → failure recorded; "
            f"will retry if attempts remain"
        )

    # ------------------------------------------------------------
    # TASK FAILED COMPLETELY
    # ------------------------------------------------------------

    task.status = G.FAILED
    task.error = last_msg

    _progress(
        f"TASK {task.id} → FAILED permanently "
        f"after {max_attempts} attempts"
    )

    return {
        "status": "failed",
        "message": last_msg,
    }


def solve(
    question,
    files,
    overrides=None,
    max_turns=None,
    explain=True,
    memory="3g",
):
    """
    Answer a question about the given files.

    Returns:
        status: ok | partial | refused | clarify | failed
    """

    overrides = overrides or {}

    max_attempts = (
        max_turns
        or int(
            os.environ.get(
                "MAX_TASK_ATTEMPTS",
                "3",
            )
        )
    )

    state = RunState(
        question,
        files,
        overrides,
    )

    def out(
        status,
        answer,
        result=None,
        artifacts=None,
        warnings=None,
    ):
        state.status = status

        state.final = {
            "status": status,
            "answer": answer,
            "result": result,
        }

        state.save()

        secs = round(
            time.time() - state.started,
            1,
        )

        _log(
            {
                "run_id": state.run_id,
                "final": status,
                "attempts": state.attempts_total,
                "seconds": secs,
                "provider": llm.PROVIDER,
                "model": llm.MODEL,
                "failures": state.failures,
            }
        )

        return {
            "status": status,
            "answer": answer,
            "turns": state.attempts_total,
            "tasks": (
                {
                    k: t.status
                    for k, t in state.graph.tasks.items()
                }
                if state.graph
                else {}
            ),
            "result": result,
            "artifacts": artifacts or [],
            "warnings": warnings or [],
            "run_dir": str(state.run_dir),
            "failures": state.failures,
            "seconds": secs,
        }

    # ================================================================
    # STEP 1: DATASET INSPECTION
    # ================================================================

    _progress("1/5 Inspecting input datasets...")

    insp = executor.run_code(
        INSPECT_CODE,
        files,
        state.run_dir / "inspect",
        memory=memory,
    )

    if insp["exit_code"] != 0 or not insp["result"]:
        state.failures.append("inspect_failed")

        _progress("1.1 Dataset inspection FAILED")

        return out(
            "failed",
            "Could not inspect the input files:\n"
            + insp["stderr"][-800:],
        )

    state.facts = insp["result"]

    _progress(
        f"1.1 Dataset inspection complete: "
        f"{len(state.facts['files'])} file(s)"
    )

    for name, fact in state.facts["files"].items():
        _progress(
            f"    {name}: "
            f"{fact.get('modality', fact.get('kind'))}"
        )

    errs = {
        n: f["error"]
        for n, f in state.facts["files"].items()
        if "error" in f
    }

    if errs and len(errs) == len(state.facts["files"]):
        return out(
            "refused",
            "None of the files could be read: "
            + json.dumps(errs),
        )

    _apply_overrides(
        state.facts,
        overrides,
    )

    state.decide(
        f"dataset: "
        f"{[(n, f.get('modality', f.get('kind'))) for n, f in state.facts['files'].items()]}"
    )

    state.save()

    # ================================================================
    # STEP 2: PLANNING
    # ================================================================

    _progress("2/5 Planning the task graph...")
    _progress(
        "2.1 Sending query + dataset facts to planner..."
    )

    p = planner.make_plan(
        question,
        state.facts,
        overrides,
    )

    _progress(
        f"2.2 Planner returned: {p['status']}"
    )

    state.plan = p["plan"]

    if p["status"] == "ok":
        _progress(
            f"2.3 Plan meaning: "
            f"{state.plan.get('meaning')}"
        )

        _progress(
            f"2.4 Measures: "
            f"{state.plan.get('measures')}"
        )

        _progress(
            f"2.5 Required data: "
            f"{state.plan.get('required_roles')}"
        )

        _progress(
            f"2.6 Preprocessing: "
            f"{state.plan.get('preprocessing')}"
        )

    if p["status"] != "ok":
        state.failures.append(
            "plan_" + p["status"]
        )

        return out(
            p["status"],
            p["message"],
        )

    plan = state.plan

    # ================================================================
    # STEP 2.7: BUILD TASK GRAPH
    # ================================================================

    _progress(
        "2.7 Building task graph..."
    )

    state.graph = G.TaskGraph.from_plan(plan)

    _progress(
        f"2.8 Task graph created: "
        f"{len(state.graph.tasks)} task(s)"
    )

    for tid in state.graph.order():
        task = state.graph.tasks[tid]

        deps = (
            ", ".join(task.dependencies)
            if task.dependencies
            else "none"
        )

        _progress(
            f"    {tid}: {task.name} "
            f"| dependencies: {deps}"
        )

    _progress(
        f"2.9 Final task: "
        f"{state.graph.final_task}"
    )

    (state.run_dir / "plan.json").write_text(
        json.dumps(
            plan,
            indent=2,
        )
    )

    state.decide(
        f"plan: {plan.get('meaning')} | "
        f"tasks: {state.graph.order()} | "
        f"assumptions: {plan.get('assumptions')}"
    )

    state.save()

    # ================================================================
    # STEP 3: EXECUTE TASK GRAPH
    # ================================================================

    needed = state.graph.needed()

    _progress(
        f"3/5 Executing {len(needed)} required task(s)..."
    )

    for tid in state.graph.order():

        if tid not in needed:
            continue

        task = state.graph.tasks[tid]

        if not state.graph.deps_ok(task):
            task.status = G.BLOCKED

            _progress(
                f"TASK {tid} → BLOCKED "
                f"(dependency failed)"
            )

            continue

        _progress(
            f"Starting TASK {tid}: {task.name}"
        )

        r = execute_task(
            state,
            task,
            files,
            memory,
            max_attempts,
        )

        state.warnings += r.get(
            "warnings",
            [],
        )

        state.save()

        if r["status"] in (
            "refused",
            "clarify",
        ):
            return out(
                r["status"],
                r["message"],
            )

        if r["status"] == "failed":

            for t in state.graph.tasks.values():
                if (
                    t.status == G.PENDING
                    and t.id in needed
                    and not state.graph.deps_ok(t)
                ):
                    t.status = G.BLOCKED

            report = {
                k: {
                    "status": t.status,
                    "attempts": t.attempt,
                    "error": t.error,
                }
                for k, t in state.graph.tasks.items()
            }

            (
                state.run_dir / "failure_report.json"
            ).write_text(
                json.dumps(
                    report,
                    indent=2,
                )
            )

            return out(
                "failed",
                f"Task '{tid}' failed after "
                f"{max_attempts} attempts: "
                f"{r['message']}\n"
                f"See {state.run_dir}/failure_report.json",
            )

    # ================================================================
    # STEP 4: FINAL VALIDATION
    # ================================================================

    ft = state.graph.tasks[
        state.graph.final_task
    ]

    names = [
        a["name"]
        for a in ft.artifacts
    ]

    _progress("4/5 Final validation...")

    _progress(
        "4.1 Checking required outputs..."
    )

    unmet, unchecked = (
        final_check.check_requirements(
            plan,
            ft.result,
            names,
        )
    )

    _progress(
        f"4.2 Requirement check: "
        f"{len(unmet)} unmet, "
        f"{len(unchecked)} unchecked"
    )

    if explain:
        _progress(
            "4.3 Asking LLM to judge final requirements..."
        )

        unmet += final_check.judge(
            question,
            ft.result,
            unchecked,
        )

        _progress(
            f"4.4 Final judge result: "
            f"{len(unmet)} unmet requirement(s)"
        )

    if unmet:
        _progress(
            "4.5 Final result needs revision; "
            "patching final task..."
        )

        state.failures.append(
            "requirements_unmet"
        )

        seed = debugger.build_feedback(
            ft,
            ft.code,
            "requirements",
            "Not satisfied: "
            + "; ".join(unmet),
        )

        r = execute_task(
            state,
            ft,
            files,
            memory,
            2,
            start_code=ft.code,
            seed=seed,
        )

        if r["status"] == "success":
            names = [
                a["name"]
                for a in ft.artifacts
            ]

            unmet, _ = (
                final_check.check_requirements(
                    plan,
                    ft.result,
                    names,
                )
            )

        if unmet:
            state.warnings.append(
                "Requirements not fully met: "
                + "; ".join(unmet)
            )

    else:
        _progress(
            "4.5 Final requirements satisfied"
        )

    # ================================================================
    # FINAL ARTIFACTS
    # ================================================================

    result = ft.result

    all_files = [
        f"tasks/{t.id}/outputs/{a['rel']}"
        for t in state.graph.tasks.values()
        if (
            t.status == G.SUCCESS
            and t.id in needed
        )
        for a in t.artifacts
    ]

    fdir = state.run_dir / "final"
    fdir.mkdir(
        exist_ok=True
    )

    if (
        state.task_dir(ft.id) / "outputs"
    ).exists():
        shutil.copytree(
            state.task_dir(ft.id) / "outputs",
            fdir / "outputs",
            dirs_exist_ok=True,
        )

    # ================================================================
    # STEP 5: FINAL EXPLANATION
    # ================================================================

    brief = {
        n: {
            "date": f.get("date"),
            "extent_km2": f.get("extent_km2"),
        }
        for n, f in state.facts["files"].items()
        if f.get("kind") == "raster"
    }

    support = {
        t.id: t.result
        for t in state.graph.tasks.values()
        if (
            t.id in needed
            and t.id != ft.id
            and t.result
        )
    }

    if explain:

        _progress(
            "5/5 Writing the plain-language answer..."
        )

        payload = {
            "question": question,
            "assumptions": plan.get(
                "assumptions"
            ),
            "result": result,
            "supporting_results": support,
            "warnings": state.warnings,
            "files": names,
            "datasets": brief,
        }

        msgs = [
            {
                "role": "system",
                "content": prompts.EXPLAIN,
            },
            {
                "role": "user",
                "content": json.dumps(
                    payload,
                    default=str,
                )[:14000],
            },
        ]

        _progress(
            "5.1 Sending validated results to explanation LLM..."
        )

        answer = llm.chat(
            msgs,
            show=False,
        )

        _progress(
            "5.2 Explanation generated; "
            "checking numeric claims..."
        )

        allowed = [
            result,
            support,
            brief,
            plan.get("assumptions"),
        ]

        bad = final_check.ground_numbers(
            answer,
            allowed,
        )

        if bad:
            _progress(
                "5.3 Explanation contains "
                "unverified numbers; asking LLM to rewrite..."
            )

            answer = llm.chat(
                msgs
                + [
                    {
                        "role": "assistant",
                        "content": answer,
                    },
                    {
                        "role": "user",
                        "content": (
                            "These numbers are not in the data: "
                            f"{bad}. Rewrite using only numbers "
                            "from the JSON."
                        ),
                    },
                ],
                show=False,
            )

            if final_check.ground_numbers(
                answer,
                allowed,
            ):
                state.warnings.append(
                    "Explanation could not be verified "
                    "against the data; showing a "
                    "deterministic summary."
                )

                answer = final_check.template_answer(
                    result,
                    state.warnings,
                    names,
                )

        _progress(
            "5.4 Final explanation ready"
        )

    else:
        answer = json.dumps(
            result,
            indent=2,
            default=str,
        )

        _progress(
            "5.4 Raw result selected "
            "(explanation disabled)"
        )

    # ================================================================
    # SAVE FINAL REPORT
    # ================================================================

    (fdir / "answer.md").write_text(
        answer
    )

    (fdir / "report.json").write_text(
        json.dumps(
            {
                "query": question,
                "tasks": {
                    k: t.status
                    for k, t in state.graph.tasks.items()
                },
                "warnings": state.warnings,
                "result": result,
            },
            indent=2,
            default=str,
        )
    )

    _progress(
        f"RUN COMPLETE → "
        f"{'PARTIAL' if unmet else 'SUCCESS'}"
    )

    return out(
        "partial" if unmet else "ok",
        answer,
        result,
        all_files,
        state.warnings,
    )