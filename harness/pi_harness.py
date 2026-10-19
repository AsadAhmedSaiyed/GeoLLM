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
    """PNG artifact names as recorded by the runner (check_images joins them to run_dir)."""
    rels = []
    for a in _read_status(run_dir).get("artifacts", []):
        if str(a).lower().endswith(".png") and (Path(run_dir) / a).exists():
            rels.append(str(a))
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
            step({
                "type": "tool_start",
                "toolCallId": tool_id,
                "toolName": tool_name,
                "args": args_payload,
                "attempt": state["tool_calls"],
            })
            if cfg.verbose:
                print(f"\n[pi] running tool: {tool_name}", flush=True)
        elif t == "tool_execution_end":
            tool_id = ev.get("toolCallId") or f"call_{state.get('tool_calls', 1)}"
            is_err = ev.get("isError", False)
            res = ev.get("result") or {}
            details = res.get("details") or {} if isinstance(res, dict) else {}
            ok = details.get("ok", not is_err)
            exit_code = details.get("exit_code", -1 if is_err else 0)
            attempt = details.get("attempt", state.get("tool_calls", 1))
            duration_s = details.get("duration", 0.0)
            err_tail = (details.get("error") or details.get("message") or "")[-500:]
            stdout_tail = ""
            if isinstance(res, dict) and res.get("content"):
                for item in res["content"]:
                    if isinstance(item, dict) and item.get("text"):
                        stdout_tail = item["text"][:300]
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
            for attempt in range(max_r + 1):          # +1 = final re-check after the last fix
                rels = _png_rels(run_dir)
                if not rels:
                    break
                task_stub = SimpleNamespace(
                    name="geospatial analysis",
                    description=question,
                    expected_outputs=[str(a) for a in _read_status(run_dir).get("artifacts", [])]
                                     or ["the outputs the question asks for"],
                )
                try:
                    verdicts = visual_check.check_images(task_stub, run_dir, rels, run_dir / "feedback", on_step=step)
                except Exception as e:
                    warnings.append(f"Vision check failed: {e}")
                    break
                bad = [v for v in verdicts if v.get("status") == "needs_revision"]
                skipped = [v for v in verdicts if v.get("status") == "skipped"]
                passed = [v for v in verdicts if v.get("status") == "ok"]

                vision_log.append({
                    "round": attempt + 1,
                    "checked": len(verdicts),
                    "bad": [{"file": v["file"], "issues": v.get("issues", [])} for v in bad],
                    "skipped": [{"file": v["file"], "reason": v.get("recommended_action", "")} for v in skipped]
                })

                if skipped:
                    reason = skipped[0].get("recommended_action", "unknown vision error")
                    warnings.append(f"Vision check warning: {reason}")

                if not bad:
                    break
                if attempt == max_r:
                    warnings.append("Vision issues remain after max retries: "
                                    + "; ".join(v["file"] for v in bad))
                    break

                step({"type": "status", "status": "running"})
                critique = "\n".join(
                    f"- {v['file']}: {'; '.join(map(str, v.get('issues', [])))} "
                    f"| fix: {v.get('recommended_action', '')}" for v in bad)
                pi.drain()
                stats = pi.run_prompt(
                    "A visual review of your output maps found problems:\n"
                    f"{critique}\n"
                    "Fix them by patching your existing script (sandbox files may not persist, so "
                    "re-run the full corrected script), and save the corrected outputs. "
                    "You have a fresh tool-call budget for this fix.",
                    cfg.idle_timeout_s, cfg.total_timeout_s, cfg.max_tool_calls,
                    on_event, images=_b64_images([Path(run_dir) / v["file"] for v in bad]))
                answer = pi.last_assistant_text()
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