"""Replaces harness/agent.py: drives the Pi agent (RPC mode) with one sandbox tool."""
import json
import os
import shutil
import sys
import time
import uuid
from dataclasses import replace
from pathlib import Path
from string import Template

from geollm_lib.metadata import inspect_dataset
from harness import api_doc, prompts
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


def solve(question, files, overrides=None, max_turns=None, explain=True) -> dict:
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

    env = {**os.environ,
           "GEOLLM_PYTHON": sys.executable,
           "GEOLLM_RUNNER": str(RUNNER),
           "GEOLLM_RUN_DIR": str(run_dir),
           "GEOLLM_ALLOWED_FILES": json.dumps([str(f) for f in files]),
           "GEOLLM_TOOL_TIMEOUT_S": str(cfg.tool_timeout_s),
           "GEOLLM_MAX_TOOL_CALLS": str(cfg.max_tool_calls)}

    args = [pi_exe, "--mode", "rpc", "--no-session", "--no-builtin-tools",
            "--no-context-files", "--no-extensions", "-e", str(EXTENSION)]
    if cfg.provider:
        args += ["--provider", cfg.provider]
    if cfg.model:
        args += ["--model", cfg.model]

    def on_event(ev):
        if not cfg.verbose:
            return
        t = ev.get("type")
        if t == "message_update":
            d = ev.get("assistantMessageEvent", {})
            if d.get("type") == "text_delta":
                print(d.get("delta", ""), end="", flush=True)
        elif t == "tool_execution_start":
            print(f"\n[pi] running tool: {ev.get('toolName')}", flush=True)
        elif t == "tool_execution_end":
            print(f"[pi] tool finished (isError={ev.get('isError')})", flush=True)

    print("[GeoLLM] Starting Pi RPC...", flush=True)
    print(f"[GeoLLM] Command: {' '.join(args)}", flush=True)
    print(f"[GeoLLM] Run directory: {run_dir}", flush=True)
    pi = PiRPC(args, cwd=Path.cwd(), env=env, stderr_path=run_dir / "pi_stderr.log")
    warnings, stats, answer = [], {"tool_calls": 0, "turns": 0, "aborted": False}, ""
    try:
        prompt = _build_prompt(cfg, question, files, facts, overrides, explain)
        stats = pi.run_prompt(prompt, cfg.idle_timeout_s, cfg.total_timeout_s, cfg.max_tool_calls, on_event)
        answer = pi.last_assistant_text()
    except (PiRPCError, TimeoutError) as e:
        stats = pi.last_stats
        warnings.append(f"Pi session problem: {e}")
    finally:
        pi.close()

    # Ground truth for status = the sandbox runner's own record, not the model's words.
    status, artifacts = "failed", []
    sf = run_dir / "last_status.json"
    if sf.exists():
        last = json.loads(sf.read_text(encoding="utf-8"))
        artifacts = last.get("artifacts", [])
        warnings += last.get("warnings", [])
        status = "ok" if last.get("ok") else "failed"
        if not last.get("ok"):
            warnings.append(f"Last execution did not succeed: {last.get('message', '')[:300]}")
    else:
        warnings.append("The model never executed any code.")
    if stats.get("aborted"):
        warnings.append(f"Stopped after exceeding {cfg.max_tool_calls} tool calls.")

    return _result(
    status,
    answer or "No textual summary was returned.",
    run_dir,
    turns=stats["turns"],
    attempts=stats["tool_calls"],
    seconds=round(time.time() - t0, 2),
    warnings=warnings,
    artifacts=artifacts,
)