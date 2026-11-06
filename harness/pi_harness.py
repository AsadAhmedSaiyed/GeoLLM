"""Replaces harness/agent.py: drives the Pi agent (RPC mode) with one sandbox tool,
then runs a vision check -> fix -> re-check loop on the PNG outputs."""
import base64
import json
import os
import shutil
import sys
import time
import uuid
from dataclasses import replace
from pathlib import Path
from string import Template
from types import SimpleNamespace

from geollm_lib.metadata import inspect_dataset
from harness import api_doc, prompts, llm, visual_check
from harness.pi_config import load_config
from harness.pi_rpc import PiRPC, PiRPCError

HARNESS_DIR = Path(__file__).resolve().parent
EXTENSION = HARNESS_DIR / "pi_extension" / "geollm.ts"
PROMPT_FILE = HARNESS_DIR / "pi_prompt.md"
RUNNER = HARNESS_DIR / "docker_runner.py"


def _result(status, answer, run_dir="", **kw):
    base = {
        "status": status,
        "answer": answer,
        "turns": 0,
        "attempts": 0,
        "seconds": 0.0,
        "tasks": {"pi_agent": status},
        "warnings": [],
        "artifacts": [],
        "run_dir": str(run_dir),
        "vision": [],
    }
    base.update(kw)
    return base


def _build_prompt(cfg, question, files, facts, overrides, explain):
    return Template(PROMPT_FILE.read_text(encoding="utf-8")).substitute(
        max_calls=cfg.max_tool_calls,
        result_contract=cfg.result_contract,
        api_overview=api_doc.module_overview(),
        knowledge=prompts.KNOWLEDGE,
        facts=json.dumps(facts, indent=2, default=str),
        question=question,
        files=json.dumps([str(f) for f in files]),
        overrides=(f"User overrides (authoritative): {json.dumps(overrides, default=str)}" if overrides else ""),
        explain_line=("" if explain else "Keep the final answer to a few sentences."),
    )


def _read_status(run_dir):
    sf = Path(run_dir) / "last_status.json"
    try:
        return json.loads(sf.read_text(encoding="utf-8")) if sf.exists() else {}
    except Exception:
        return {}


def _png_rels(run_dir):
    """PNG/GIF artifact names as recorded by the runner (with fallback across succeeded attempts)."""
    rels = []
    seen_names = set()
    rd = Path(run_dir).resolve()
    status_data = _read_status(run_dir)
    for a in status_data.get("artifacts", []):
        p = Path(a)
        if not p.is_absolute():
            p = (rd / p).resolve()
        if p.suffix.lower() in (".png", ".gif") and p.is_file() and p.name not in seen_names:
            seen_names.add(p.name)
            try:
                rel = str(p.relative_to(rd))
            except ValueError:
                rel = str(p)
            rels.append(rel)

    # If a revision attempt updated only a subset of files without re-declaring artifacts,
    # merge PNG/GIF files from the latest attempt outputs and earlier completed attempts.
    if status_data.get("ok"):
        for ad in sorted(rd.glob("attempt_*"), reverse=True):
            out_dir = ad / "outputs"
            if not out_dir.is_dir():
                continue
            # Include latest attempt or earlier completed attempts (those with result.json)
            att_num = int(ad.name.split("_")[-1]) if ad.name.split("_")[-1].isdigit() else 0
            if att_num != status_data.get("attempt") and not (out_dir / "result.json").is_file():
                continue
            for p in sorted(out_dir.iterdir()):
                if p.is_file() and p.suffix.lower() in (".png", ".gif") and p.name not in seen_names:
                    seen_names.add(p.name)
                    try:
                        rel = str(p.relative_to(rd))
                    except ValueError:
                        rel = str(p)
                    rels.append(rel)
    return rels


def _b64_images(paths, limit=2):
    return [{"type": "image",
             "data": base64.b64encode(Path(p).read_bytes()).decode(),
             "mimeType": "image/png"} for p in paths[:limit]]


def _stderr_tail(run_dir, n=400):
    try:
        text = (Path(run_dir) / "pi_stderr.log").read_text(encoding="utf-8", errors="replace").strip()
        return text[-n:] if text else ""
    except Exception:
        return ""


def solve(question, files, overrides=None, max_turns=None, explain=True, on_step=None, state=None, task_id="task_1", task_state=None) -> dict:

    step = on_step or (lambda s: None)
    state = state if state is not None else {}
    t0 = time.time()
    cfg = load_config()
    if max_turns:
        cfg = replace(cfg, max_tool_calls=int(max_turns))

    pi_exe = shutil.which(cfg.pi_command)          # resolves pi.cmd on Windows
    if not pi_exe:
        return _result("failed", f"Pi CLI '{cfg.pi_command}' not found. Install: "
                       "npm install -g @earendil-works/pi-coding-agent (or set PI_COMMAND).")
    missing = [str(f) for f in files if not Path(f).exists()]
    if missing:
        return _result("failed", f"Input file(s) not found: {missing}")
    if not EXTENSION.exists():
        return _result("failed", f"Missing Pi extension: {EXTENSION}")

    facts = inspect_dataset(files)
    run_dir = cfg.runs_dir / (time.strftime("%Y%m%d_%H%M%S") + "_" + task_id)

    run_dir.mkdir(parents=True, exist_ok=True)
    if not task_state or getattr(task_state, "auto_approve", False):
        (run_dir / "plan_approved.flag").touch()
    state.update(run_dir=str(run_dir), facts=json.dumps(facts, default=str)[:3000],
                 tool_calls=0, pi_text="", last_tool="")


    env = {**os.environ,
           "GEOLLM_PYTHON": sys.executable,
           "GEOLLM_RUNNER": str(RUNNER),
           "GEOLLM_RUN_DIR": str(run_dir),
           "GEOLLM_ALLOWED_FILES": json.dumps([str(f) for f in files]),
           "GEOLLM_TOOL_TIMEOUT_S": str(cfg.tool_timeout_s),
           "GEOLLM_MAX_TOOL_CALLS": str(cfg.max_tool_calls),
           "GEOLLM_QUESTION": question,
           "GEOLLM_TASK_ID": task_id}

    args = [pi_exe, "--mode", "rpc", "--no-session", "--no-builtin-tools",
            "--no-context-files", "--no-extensions", "-e", str(EXTENSION)]
    if cfg.provider:
        args += ["--provider", cfg.provider]
    if cfg.model:
        args += ["--model", cfg.model]

    def on_event(ev):
        t = ev.get("type")
        if t == "message_update":
            d = ev.get("assistantMessageEvent") or {}
            dt = d.get("type")
            if dt == "text_delta":
                piece = d.get("delta", "")
                if piece:
                    step({"type": "text", "delta": piece})
                    state["pi_text"] = (state.get("pi_text", "") + piece)[-800:]
                if cfg.verbose:
                    print(piece, end="", flush=True)
            elif dt in ("thinking_delta", "thought_delta", "reasoning_delta"):
                piece = d.get("delta") or d.get("text") or ""
                if piece:
                    step({"type": "thinking", "delta": piece})
        elif t == "turn_start":
            state["turns"] = state.get("turns", 0) + 1
            step({"type": "turn", "state": "start", "turn": state["turns"]})
        elif t in ("turn_end", "agent_end"):
            step({"type": "turn", "state": "end"})
        elif t == "tool_execution_start":
            state["tool_calls"] = state.get("tool_calls", 0) + 1
            tool_name = ev.get("toolName") or ev.get("name") or "tool"
            args_payload = ev.get("args") or ev.get("input") or {}
            tool_id = ev.get("toolCallId") or f"call_{state['tool_calls']}"
            state[f"t_start_{tool_id}"] = time.time()
            if tool_name == "run_geospatial_code":
                state["code_attempts"] = state.get("code_attempts", 0) + 1
                if task_state and args_payload.get("code"):
                    task_state.last_code = args_payload.get("code")
            code_attempt = state.get("code_attempts", state["tool_calls"])
            max_code_attempts = getattr(cfg, "max_tool_calls", 4)
            step({
                "type": "tool_start",
                "toolCallId": tool_id,
                "toolName": tool_name,
                "args": args_payload,
                "attempt": state["tool_calls"],
                "code_attempt": code_attempt,
                "max_attempts": max_code_attempts,
            })
            if cfg.verbose:
                print(f"\n[pi] running tool: {tool_name}", flush=True)
        elif t == "tool_execution_end":
            tool_id = ev.get("toolCallId") or f"call_{state.get('tool_calls', 1)}"
            t_start = state.pop(f"t_start_{tool_id}", None)
            wall_s = round(time.time() - t_start, 2) if t_start else 0.0
            is_err = ev.get("isError", False)
            res = ev.get("result") or {}
            details = res.get("details") or {} if isinstance(res, dict) else {}
            ok = details.get("ok", not is_err)
            exit_code = details.get("exit_code", -1 if is_err else 0)
            # SyntaxError: do not count as a code attempt
            if details.get("syntax_error"):
                state["code_attempts"] = max(0, state.get("code_attempts", 1) - 1)
            code_attempt = state.get("code_attempts", state.get("tool_calls", 1))
            attempt = details.get("attempt", code_attempt)
            dur_val = details.get("duration_s")
            if dur_val is None or dur_val == 0.0:
                dur_val = details.get("duration", wall_s)
            duration_s = dur_val if (dur_val is not None and dur_val > 0) else wall_s

            raw_err = details.get("error") or ""
            if not raw_err and details.get("message"):
                msg = str(details["message"])
                if "SANDBOX PATH CONTRACT:" in msg:
                    raw_err = msg.split("SANDBOX PATH CONTRACT:")[0].strip()
                else:
                    raw_err = msg
            err_tail = (raw_err or "")[:1200]

            stdout_tail = ""
            if isinstance(res, dict) and res.get("content"):
                for item in res["content"]:
                    if isinstance(item, dict) and item.get("text"):
                        stdout_tail = item["text"][:600]
                        break
            step({
                "type": "tool_end",
                "toolCallId": tool_id,
                "ok": ok,
                "exit_code": exit_code,
                "duration_s": duration_s,
                "error": err_tail,
                "stdout": stdout_tail,
                "attempt": attempt,
                "code_attempt": code_attempt,
                "max_attempts": getattr(cfg, "max_tool_calls", 4),
            })
            if cfg.verbose:
                print(f"[pi] tool finished (isError={is_err})", flush=True)

    print("[GeoLLM] Starting Pi RPC...", flush=True)
    print(f"[GeoLLM] Run directory: {run_dir}", flush=True)
    pi = PiRPC(args, cwd=Path.cwd(), env=env, stderr_path=run_dir / "pi_stderr.log")
    if task_state:
        task_state.pi_rpc = pi
    state["pi_live"] = pi.snapshot          # lets the status chat read real Pi state


    warnings, answer = [], ""
    stats = {"tool_calls": 0, "turns": 0, "aborted": False}
    vision_log = []
    session_problem = False
    try:
        prompt = _build_prompt(cfg, question, files, facts, overrides, explain)
        step({"type": "status", "status": "running"})

        # ---- Preflight input quality gate (Phase 1e) ---------------------------
        # Runs on the real uploaded paths before ANY model call.  If the
        # inputs are unusable (nodata / cloud / multi-date intersection below
        # thresholds) the gate emits vision_input_gate + vision_insufficient_data
        # and stops here — the Pi agent is never invoked.
        try:
            from harness.validation.input_gate import run_input_gate
            gate = run_input_gate(files, on_step=step)
            if gate is None:
                warnings.append(
                    "Input quality gate blocked execution: insufficient data in "
                    "the uploaded rasters. No model call was made."
                )
                return _result(
                    "failed",
                    "Input quality gate blocked execution: insufficient data in the "
                    "uploaded rasters.",
                    run_dir,
                    warnings=warnings,
                )
        except Exception as exc:
            warnings.append(f"Input quality gate error: {exc}")
        # ------------------------------------------------------------------------

        stats = pi.run_prompt(prompt, cfg.idle_timeout_s, cfg.total_timeout_s,
                              cfg.max_tool_calls, on_event)
        answer = pi.last_assistant_text()

        # ---- Plan Approval Gate ----
        plan_file = run_dir / "plan.json"
        plan_approved = not task_state or getattr(task_state, "auto_approve", False)
        revisions = 0

        # Case 1: CLI Auto-Approve (executes immediately without blocking)
        if task_state and getattr(task_state, "auto_approve", False):
            if plan_file.exists():
                plan_file.unlink()
                step({"type": "status", "status": "running"})
                pi.drain()
                stats = pi.run_prompt(
                    "Plan approved! Proceed to implement and run the analysis with `run_geospatial_code`. "
                    "Write all requested GeoTIFF/PNG files and verify deliverables.",
                    cfg.idle_timeout_s, cfg.total_timeout_s, cfg.max_tool_calls, on_event
                )
                answer = pi.last_assistant_text()

        # Case 2: Web UI Human-in-the-Loop Review
        elif task_state:
            while revisions <= 3:
                if not plan_file.exists():
                    break

                try:
                    pdata = json.loads(plan_file.read_text(encoding="utf-8"))
                    plan_file.unlink()
                except Exception:
                    break

                task_state.approval_event.clear()
                task_state.plan = pdata.get("plan", "")
                task_state.status = "pending_approval"
                step({"type": "plan_ready", "plan": task_state.plan})
                step({"type": "status", "status": "pending_approval"})

                approved = task_state.approval_event.wait(timeout=1800)
                if not approved or task_state.error == "Cancelled by user":
                    if not approved:
                        task_state.error = "Approval timed out after 30 minutes"
                    task_state.status = "failed"
                    return _result("failed", task_state.error, run_dir)

                if task_state.revision_feedback:
                    revisions += 1
                    step({"type": "status", "status": "running"})
                    task_state.status = "running"
                    fb = task_state.revision_feedback
                    task_state.revision_feedback = None
                    pi.drain()
                    stats = pi.run_prompt(
                        f"The user reviewed your plan and requested changes:\n{fb}\n\n"
                        "Revise your approach and call `propose_plan` again.",
                        cfg.idle_timeout_s, cfg.total_timeout_s,
                        cfg.max_tool_calls, on_event
                    )
                    answer = pi.last_assistant_text()
                    continue

                plan_approved = True
                (run_dir / "plan_approved.flag").touch()
                step({"type": "status", "status": "running"})
                task_state.status = "running"
                pi.drain()
                stats = pi.run_prompt(
                    "Plan approved! Proceed to implement and run the analysis with `run_geospatial_code`. "
                    "Write all requested GeoTIFF/PNG files and verify deliverables.",
                    cfg.idle_timeout_s, cfg.total_timeout_s,
                    cfg.max_tool_calls, on_event
                )
                answer = pi.last_assistant_text()
                break

            if not plan_approved:
                msg = ("Too many plan revisions" if revisions > 3 else "Agent did not propose a plan")
                return _result("failed", msg, run_dir, warnings=[msg])

        # ---- vision loop: check -> Pi fixes -> check again ----
        if llm.vision_available():
            max_r = cfg.vision_max_retries
            feedback_memory: list = []
            cached_passed: Dict[str, Dict[str, Any]] = {}
            seen_rel_names: set = set()
            needs_recheck_names: set = set()

            for attempt in range(max_r + 1):          # +1 = final re-check after the last fix
                all_rels = _png_rels(run_dir)
                if not all_rels:
                    break

                if attempt == 0:
                    rels = all_rels
                else:
                    # Incremental check: only re-evaluate files that needed revision
                    # (or brand-new files generated in the fix attempt), skipping
                    # files that already passed or were unflagged in earlier rounds.
                    rels = [
                        r for r in all_rels
                        if Path(r).name not in cached_passed
                        and (not needs_recheck_names or Path(r).name in needs_recheck_names or Path(r).name not in seen_rel_names)
                    ]
                    if not rels:
                        # Everything has passed!
                        break

                seen_rel_names.update(Path(r).name for r in all_rels)

                input_geotiffs = [
                    Path(f) for f in files
                    if str(f).lower().endswith((".tif", ".tiff")) and Path(f).is_file()
                ]
                task_stub = SimpleNamespace(
                    name="geospatial analysis",
                    description=question,
                    input_files=input_geotiffs,
                    expected_outputs=[str(a) for a in _read_status(run_dir).get("artifacts", [])]
                                     or ["the outputs the question asks for"],
                )
                try:
                    verdicts = visual_check.check_images(
                        task_stub, run_dir, rels, run_dir / "feedback", on_step=step, input_files=input_geotiffs
                    )
                except Exception as e:
                    warnings.append(f"Vision check failed: {e}")
                    break

                # Cache newly passed verdicts (including parent GIFs when all sampled frames pass)
                source_groups: Dict[str, list] = {}
                for v in verdicts:
                    src_name = Path(v.get("source_artifact") or v["file"]).name
                    source_groups.setdefault(src_name, []).append(v)
                    if v.get("status") == "ok":
                        cached_passed[Path(v["file"]).name] = v
                for src_name, g_vs in source_groups.items():
                    if g_vs and all(gv.get("status") == "ok" for gv in g_vs):
                        cached_passed[src_name] = g_vs[0]
                        needs_recheck_names.discard(src_name)

                # Merge current verdicts with cached passed verdicts for full inventory
                all_verdicts_dict = dict(cached_passed)
                for v in verdicts:
                    all_verdicts_dict[Path(v["file"]).name] = v
                all_verdicts = list(all_verdicts_dict.values())

                bad = [v for v in all_verdicts if v.get("status") == "needs_revision"]
                skipped = [v for v in all_verdicts if v.get("status") == "skipped"]
                passed = [v for v in all_verdicts if v.get("status") == "ok"]
                # not_verified / insufficient_data are NOT "ok" — they mean the
                # model could not confirm the output, or the input was unusable.
                failed = [v for v in all_verdicts
                          if v.get("status") in ("not_verified", "insufficient_data")]

                vision_log.append({
                    "round": attempt + 1,
                    "checked": len(verdicts),
                    "bad": [{"file": v["file"], "issues": v.get("issues", [])} for v in bad],
                    "failed": [{"file": v["file"], "status": v.get("status"),
                                "issues": v.get("issues", [])} for v in failed],
                    "skipped": [{"file": v["file"], "reason": v.get("recommended_action", "")} for v in skipped]
                })

                # Accumulate feedback memory across rounds
                for v in bad:
                    tile_ids = [t.get("tile_id") for t in feedback_memory]
                    if v.get("tile_id") not in tile_ids:
                        feedback_memory.append({
                            "tile_id": v.get("tile_id"),
                            "file": v["file"],
                            "severity": v.get("severity", "medium"),
                            "category": v.get("category", "output"),
                            "suggested_fix": v.get("recommended_action", ""),
                            "status": "open",
                        })
                # Mark previously-seen issues as fixed if no longer in bad
                bad_tile_ids = {v.get("tile_id") for v in bad}
                for mem in feedback_memory:
                    if mem["tile_id"] not in bad_tile_ids:
                        mem["status"] = "fixed"

                # Emit vision_feedback SSE events (output/code issues only, not input)
                for v in bad:
                    if v.get("category") != "input":
                        step({
                            "type": "vision_feedback",
                            "file": v["file"],
                            "tile_id": v.get("tile_id"),
                            "bbox_norm": v.get("bbox_norm"),
                            "bbox_geo": v.get("bbox_geo"),
                            "severity": v.get("severity", "medium"),
                            "category": v.get("category", "output"),
                            "suggested_fix": v.get("recommended_action", ""),
                        })
                # Input problems -> user warnings only (not sub-agent critique)
                for v in bad:
                    if v.get("category") == "input":
                        warnings.append(
                            f"Input data problem for {v['file']}: {v.get('recommended_action', '')}"
                        )

                if skipped:
                    reason = skipped[0].get("recommended_action", "unknown vision error")
                    warnings.append(f"Vision check warning: {reason}")

                if failed:
                    for v in failed:
                        v_name = Path(v["file"]).name
                        warnings.append(
                            f"Vision check note for {v_name}: "
                            f"{v.get('status')} — {'; '.join(map(str, v.get('issues', [])))}"
                        )

                if not bad:
                    rev_file = run_dir / "vision_revision.json"
                    if rev_file.exists():
                        try:
                            rev_file.unlink()
                        except Exception:
                            pass
                    break
                if attempt == max_r:
                    unfixed_names = sorted({
                        Path(v.get("source_artifact") or v["file"]).name for v in bad
                    })
                    warnings.append("Vision issues remain after max retries: "
                                    + "; ".join(unfixed_names))
                    try:
                        cur_att = _read_status(run_dir).get("attempt")
                        (run_dir / "vision_revision.json").write_text(
                            json.dumps({"bad_files": unfixed_names, "attempt": cur_att, "unfixed": True}, indent=2),
                            encoding="utf-8",
                        )
                    except Exception:
                        pass
                    break

                step({"type": "status", "status": "running"})
                # Only send output/code issues to sub-agent; input problems go to user only
                agent_bad = [v for v in bad if v.get("category") != "input"]
                if not agent_bad:
                    # All issues are input-data problems; nothing for the sub-agent to fix
                    break

                bad_artifact_names = sorted({
                    Path(v.get("source_artifact") or v["file"]).name for v in agent_bad
                })
                needs_recheck_names = set(bad_artifact_names)
                try:
                    cur_att = _read_status(run_dir).get("attempt")
                    (run_dir / "vision_revision.json").write_text(
                        json.dumps({"bad_files": bad_artifact_names, "attempt": cur_att, "unfixed": False}, indent=2),
                        encoding="utf-8",
                    )
                    from harness.orchestrator import find_artifacts
                    step({"type": "artifacts", "artifacts": find_artifacts(run_dir)})
                except Exception:
                    pass

                critique_lines = []
                for v in agent_bad:
                    v_name = Path(v.get("source_artifact") or v["file"]).name
                    raw_issues = v.get("issues", [])
                    seen_issues = set()
                    unique_issues = []
                    for iss in raw_issues:
                        s_iss = str(iss).strip()
                        if s_iss and s_iss not in seen_issues:
                            seen_issues.add(s_iss)
                            unique_issues.append(s_iss)
                    issues_str = "; ".join(unique_issues) if unique_issues else "Visual inspection identified defects"
                    fix_action = v.get("recommended_action", "").strip()
                    critique_lines.append(f"- {v_name}: {issues_str} | fix: {fix_action}")
                critique = "\n".join(critique_lines)
                pi.drain()
                # Build patch-first prompt using patcher SEARCH/REPLACE format
                last_code = getattr(task_state, "last_code", None) if task_state else None
                if last_code:
                    patch_hint = (
                        "\n\nPrefer to fix using SEARCH/REPLACE patches in this format:\n"
                        "<<<<<<< SEARCH\n<exact lines to replace>\n=======\n<replacement lines>\n>>>>>>> REPLACE\n"
                        "If patching is not possible, re-run the full corrected script."
                    )
                else:
                    patch_hint = " Re-run the full corrected script."
                stats = pi.run_prompt(
                    "A visual review of your output maps found problems with specific files:\n"
                    f"{critique}\n"
                    "Fix ONLY these affected files and save their corrected versions. "
                    "Files not listed above already passed validation and are already preserved in /workspace/output. "
                    "You have a fresh tool-call budget for this fix."
                    + patch_hint,
                    cfg.idle_timeout_s, cfg.total_timeout_s, cfg.max_tool_calls,
                    on_event, images=_b64_images([Path(run_dir) / v["file"] for v in agent_bad if (Path(run_dir) / v["file"]).is_file()]))
                answer = pi.last_assistant_text()
                try:
                    from harness.orchestrator import find_artifacts
                    step({"type": "artifacts", "artifacts": find_artifacts(run_dir)})
                except Exception:
                    pass
        else:
            warnings.append("Visual validation not performed (no GEOLLM_VISION_MODEL set).")
    except (PiRPCError, TimeoutError) as e:
        session_problem = True
        stats = pi.last_stats
        warnings.append(f"Pi session problem: {e}")
        step({"type": "status", "status": "failed", "error": str(e)})
    finally:
        pi.close()

    # Model/provider errors seen in Pi's event stream (skip ones already reported).
    for err in stats.get("errors", []):
        if not any(err in w for w in warnings):
            warnings.append(f"Model/provider error: {err}")

    # Ground truth for status = the sandbox runner's own record, not the model's words.
    status, artifacts = "failed", []
    sf = run_dir / "last_status.json"
    if sf.exists():
        last = json.loads(sf.read_text(encoding="utf-8"))
        artifacts = last.get("artifacts", [])
        warnings += last.get("warnings", [])
        if last.get("ok"):
            status = "partial" if session_problem else "ok"
            if session_problem:
                warnings.append("Sandbox succeeded, but the Pi session ended with a problem "
                                "afterwards; the written summary may be missing or incomplete.")
        else:
            warnings.append(f"Last execution did not succeed: {last.get('message', '')[:300]}")
    else:
        warnings.append("The model never executed any code.")
        # Fallback: if last_status is not ok, check if any earlier attempt produced valid outputs
    if status != "ok":
        for attempt_dir in sorted(run_dir.glob("attempt_*"), reverse=True):
            outputs_dir = attempt_dir / "outputs"
            if outputs_dir.exists():
                valid_files = [str(f) for f in outputs_dir.iterdir() if f.is_file()]
                if valid_files:
                    artifacts = valid_files
                    status = "partial" if session_problem else "ok"
                    warnings = [w for w in warnings if "Last execution did not succeed" not in w]
                    break
    
    if stats.get("aborted"):
        warnings.append(f"Stopped after exceeding {cfg.max_tool_calls} tool calls.")
    if status != "ok":
        tail = _stderr_tail(run_dir)
        if tail:
            warnings.append(f"pi_stderr.log tail: {tail}")

    step({"type": "status", "status": status})
    return _result(
        status,
        answer or "No textual summary was returned.",
        run_dir,
        turns=stats.get("turns", 0),
        attempts=stats.get("tool_calls", 0),
        seconds=round(time.time() - t0, 2),
        warnings=warnings,
        artifacts=artifacts,
        vision=vision_log,
    )