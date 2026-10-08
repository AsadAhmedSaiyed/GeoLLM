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


def solve(question, files, overrides=None, max_turns=None, explain=True,
          on_step=None, state=None) -> dict:
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
    run_dir = cfg.runs_dir / (time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:4])
    run_dir.mkdir(parents=True, exist_ok=True)
    state.update(run_dir=str(run_dir), facts=json.dumps(facts, default=str)[:3000],
                 tool_calls=0, pi_text="", last_tool="")

    env = {**os.environ,
           "GEOLLM_PYTHON": sys.executable,
           "GEOLLM_RUNNER": str(RUNNER),
           "GEOLLM_RUN_DIR": str(run_dir),
           "GEOLLM_ALLOWED_FILES": json.dumps([str(f) for f in files]),
           "GEOLLM_TOOL_TIMEOUT_S": str(cfg.tool_timeout_s),
           "GEOLLM_MAX_TOOL_CALLS": str(cfg.max_tool_calls),
           "GEOLLM_QUESTION": question}

    args = [pi_exe, "--mode", "rpc", "--no-session", "--no-builtin-tools",
            "--no-context-files", "--no-extensions", "-e", str(EXTENSION)]
    if cfg.provider:
        args += ["--provider", cfg.provider]
    if cfg.model:
        args += ["--model", cfg.model]

    def on_event(ev):
        t = ev.get("type")
        if t == "message_update":
            d = ev.get("assistantMessageEvent", {})
            if d.get("type") == "text_delta":
                piece = d.get("delta", "")
                state["pi_text"] = (state.get("pi_text", "") + piece)[-800:]
                if cfg.verbose:
                    print(piece, end="", flush=True)
        elif t == "turn_start":
            step("Pi is thinking")
        elif t == "tool_execution_start":
            state["tool_calls"] = state.get("tool_calls", 0) + 1
            state["last_tool"] = f"running {ev.get('toolName')}"
            step(f"Pi running sandbox tool (call {state['tool_calls']})")
            if cfg.verbose:
                print(f"\n[pi] running tool: {ev.get('toolName')}", flush=True)
        elif t == "tool_execution_end":
            state["last_tool"] = f"finished (isError={ev.get('isError')})"
            step(f"Sandbox run finished (isError={ev.get('isError')})")
            if cfg.verbose:
                print(f"[pi] tool finished (isError={ev.get('isError')})", flush=True)

    print("[GeoLLM] Starting Pi RPC...", flush=True)
    print(f"[GeoLLM] Run directory: {run_dir}", flush=True)
    pi = PiRPC(args, cwd=Path.cwd(), env=env, stderr_path=run_dir / "pi_stderr.log")
    state["pi_live"] = pi.snapshot          # lets the status chat read real Pi state

    warnings, answer = [], ""
    stats = {"tool_calls": 0, "turns": 0, "aborted": False}
    vision_log = []
    session_problem = False
    try:
        prompt = _build_prompt(cfg, question, files, facts, overrides, explain)
        step("Pi is reading the data and writing code")
        stats = pi.run_prompt(prompt, cfg.idle_timeout_s, cfg.total_timeout_s,
                              cfg.max_tool_calls, on_event)
        answer = pi.last_assistant_text()
        step("First analysis finished")

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
                step(f"Vision model checking {len(rels)} map(s) (round {attempt + 1})")
                try:
                    verdicts = visual_check.check_images(task_stub, run_dir, rels, run_dir / "feedback")
                except Exception as e:
                    warnings.append(f"Vision check failed: {e}")
                    break
                bad = [v for v in verdicts if v.get("status") == "needs_revision"]
                vision_log.append({"round": attempt + 1, "checked": len(verdicts),
                                   "bad": [{"file": v["file"], "issues": v.get("issues", [])} for v in bad]})
                if not bad:
                    step("Vision check passed")
                    break
                if attempt == max_r:
                    warnings.append("Vision issues remain after max retries: "
                                    + "; ".join(v["file"] for v in bad))
                    break
                step(f"Pi fixing {len(bad)} map issue(s) (retry {attempt + 1}/{max_r})")
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
        step(f"Pi session problem: {e}")
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

    step(f"Finished ({status})")
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