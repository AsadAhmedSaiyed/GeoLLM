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
from typing import Optional

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
    """PNG/GIF artifact names as recorded by the runner (with fallback across succeeded attempts and durable outputs)."""
    rels = []
    seen_names = set()
    rd = Path(run_dir).resolve()
    status_data = _read_status(run_dir)

    for a in status_data.get("artifacts", []):
        cand = Path(a)
        p = None
        if cand.is_file():
            p = cand.resolve()
        elif (rd / cand).is_file():
            p = (rd / cand).resolve()
        elif (rd / "scratch" / "outputs" / cand.name).is_file():
            p = (rd / "scratch" / "outputs" / cand.name).resolve()
        elif (rd / "outputs" / cand.name).is_file():
            p = (rd / "outputs" / cand.name).resolve()

        if p and p.suffix.lower() in (".png", ".gif") and p.name not in seen_names:
            seen_names.add(p.name)
            try:
                rel = str(p.relative_to(rd))
            except ValueError:
                rel = str(p)
            rels.append(rel)

    # Durable workspaces fallback: scan scratch/outputs and outputs directly
    for out_dir in [rd / "scratch" / "outputs", rd / "outputs"]:
        if out_dir.is_dir():
            for p in sorted(out_dir.iterdir()):
                if p.is_file() and p.suffix.lower() in (".png", ".gif") and p.name not in seen_names:
                    seen_names.add(p.name)
                    try:
                        rel = str(p.relative_to(rd))
                    except ValueError:
                        rel = str(p)
                    rels.append(rel)

    # Legacy attempt directories fallback
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

    # If both a .gif animation and timeline.json exist, exclude the per-frame PNGs
    # listed in timeline.json from _png_rels so Vision QA validates the .gif (which
    # already samples frames via _expand_gifs_for_vision) without duplicate frame checks.
    has_gif = any(Path(r).suffix.lower() == ".gif" for r in rels)
    if has_gif:
        timeline_frame_names = set()
        for tl_dir in [rd / "scratch" / "outputs", rd / "outputs"] + list(rd.glob("attempt_*/outputs")):
            tl_file = tl_dir / "timeline.json"
            if tl_file.is_file():
                try:
                    tl_data = json.loads(tl_file.read_text(encoding="utf-8"))
                    for fr in tl_data.get("frames", []):
                        fname = Path(str(fr.get("file", ""))).name
                        if fname:
                            timeline_frame_names.add(fname)
                except Exception:
                    pass
        if timeline_frame_names:
            non_frame_rels = [r for r in rels if Path(r).name not in timeline_frame_names]
            if non_frame_rels:
                rels = non_frame_rels

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


def _stage_approved_stac_scenes(stac_data: dict, step, run_dir: Optional[Path] = None) -> tuple:
    """Download & crop approved STAC scenes to the target AOI bbox at 100% original native resolution."""
    import asyncio
    from harness.stac_service import stage_stac_aoi_native

    bbox = stac_data.get("bbox")
    scenes = stac_data.get("scenes") or []
    staged_files = []
    errors = []
    data_dir = (run_dir / "staged_inputs") if run_dir is not None else Path("data")
    data_dir.mkdir(parents=True, exist_ok=True)

    async def _run_all():
        for sc in scenes:
            if run_dir and (run_dir / "cancelled.flag").exists():
                errors.append("Download cancelled by user")
                break
            col = sc.get("collection") or "sentinel-2-l2a"
            item_id = sc.get("item_id") or sc.get("id")
            dt_str = str(sc.get("datetime") or "scene")[:10]
            assets = sc.get("assets") or ["B04", "B03", "B02", "B08"]
            for asset_key in assets:
                if run_dir and (run_dir / "cancelled.flag").exists():
                    errors.append("Download cancelled by user")
                    break
                custom_name = f"{col}_{dt_str}_{asset_key}.tif"
                step({
                    "type": "status",
                    "status": "running",
                    "step": f"Staging {custom_name} at native resolution...",
                })
                step({
                    "type": "stac_download_start",
                    "filename": custom_name,
                    "collection": col,
                    "item_id": item_id,
                    "asset_key": asset_key,
                    "date": dt_str,
                })
                t_dl0 = time.time()
                res = await stage_stac_aoi_native(
                    collection=col,
                    item_id=item_id,
                    asset_key=asset_key,
                    bbox_wgs84=bbox,
                    output_dir=data_dir,
                    custom_filename=custom_name,
                )
                dl_dur = round(time.time() - t_dl0, 2)
                if res.get("ok") and res.get("path"):
                    staged_files.append(str(res["path"]))
                    step({
                        "type": "stac_download_done",
                        "filename": custom_name,
                        "collection": col,
                        "asset_key": asset_key,
                        "date": dt_str,
                        "ok": True,
                        "path": str(res["path"]),
                        "size_mb": res.get("size_mb"),
                        "width": res.get("width"),
                        "height": res.get("height"),
                        "resolution": res.get("resolution"),
                        "duration_s": dl_dur,
                    })
                else:
                    err_str = res.get("error", "staging failed")
                    errors.append(f"{custom_name}: {err_str}")
                    step({
                        "type": "stac_download_done",
                        "filename": custom_name,
                        "collection": col,
                        "asset_key": asset_key,
                        "date": dt_str,
                        "ok": False,
                        "error": err_str,
                        "duration_s": dl_dur,
                    })

    asyncio.run(_run_all())
    return staged_files, errors


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

    facts = (
        inspect_dataset(files)
        if files
        else {
            "mode": "autonomous_stac_discovery",
            "note": (
                "No local files were pre-selected by the user. "
                "Start in Phase 0: use `search_stac` to find appropriate satellite scenes for the user's location and dates, "
                "then call `propose_stac_scenes` to present visual previews to the user for approval before proposing an analysis plan."
            ),
        }
    )
    from harness.workspace import init_workspace_layout
    from harness.checkpoint import save_checkpoint, load_checkpoint

    # Use configured workspace folder for task slots: runs/task_X (never timestamped!)
    if state and state.get("run_dir"):
        run_dir = Path(state["run_dir"])
        cfg = replace(cfg, runs_dir=run_dir.parent)
    elif task_id and task_id in ("task_1", "task_2", "task_3"):
        run_dir = cfg.runs_dir / task_id
    else:
        run_dir = cfg.runs_dir / task_id if task_id else cfg.runs_dir / "task_1"

    init_workspace_layout(task_id or "task_1", cfg.runs_dir)

    # Check if resuming from previous checkpoint
    cp = load_checkpoint(task_id or "task_1", cfg.runs_dir) if task_id else None
    if cp and cp.get("staged_inputs"):
        existing_staged = [f for f in cp["staged_inputs"] if Path(f).is_file() and Path(f).stat().st_size > 0]
        if existing_staged and not files:
            files = list(existing_staged)
            facts = inspect_dataset(files)
    if not files and (run_dir / "staged_inputs").is_dir():
        disk_staged = [str(p) for p in sorted((run_dir / "staged_inputs").glob("*.tif")) if p.stat().st_size > 1000]
        if disk_staged:
            files = disk_staged
            facts = inspect_dataset(files)
    if cp and cp.get("plan_approved"):
        (run_dir / "plan_approved.flag").touch()

    if not task_state or getattr(task_state, "auto_approve", False):
        (run_dir / "plan_approved.flag").touch()
    state.update(run_dir=str(run_dir), facts=json.dumps(facts, default=str)[:3000],
                 tool_calls=0, pi_text="", last_tool="")

    # Write allowed_files.json immediately with the active files of this run (unless resuming STAC downloads)
    is_resuming_stac = (run_dir / "stac_approved.flag").exists() and not (run_dir / "plan_approved.flag").exists()
    if files and not is_resuming_stac:
        try:
            (run_dir / "allowed_files.json").write_text(
                json.dumps([str(Path(f).resolve()) if Path(f).exists() else str(f) for f in files]),
                encoding="utf-8"
            )
        except Exception:
            pass
    elif not is_resuming_stac and (run_dir / "allowed_files.json").exists():
        try:
            (run_dir / "allowed_files.json").unlink()
        except Exception:
            pass


    clean_env = {**os.environ}
    if clean_env.get("PYTHONUTF8", "").strip() not in ("1", "0"):
        clean_env["PYTHONUTF8"] = "1"

    env = {**clean_env,
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
            try:
                from harness.workspace import promote_outputs
                scratch_out = run_dir / "scratch" / "outputs"
                if scratch_out.is_dir():
                    promote_outputs(task_id or run_dir.name, scratch_out, run_dir.parent)
                # Immediately promote outputs from latest attempt directory so deliverables appear live in UI
                for ad in sorted(run_dir.glob("attempt_*"), reverse=True):
                    att_out = ad / "outputs"
                    if att_out.is_dir() and any(p.is_file() for p in att_out.iterdir()):
                        promote_outputs(task_id or run_dir.name, att_out, run_dir.parent)
                        break
                from harness.orchestrator import find_artifacts
                cur_arts = find_artifacts(run_dir)
                if cur_arts:
                    step({"type": "artifacts", "artifacts": cur_arts})
                    if ok:
                        from harness.checkpoint import save_checkpoint
                        save_checkpoint(
                            task_id or "task_1",
                            "code_executed",
                            {
                                "status": "running",
                                "step": "Code executed successfully — deliverables produced",
                                "attempt": state.get("code_attempts", 1),
                                "verified_outputs": [a["name"] for a in cur_arts],
                            },
                            cfg.runs_dir,
                        )
            except Exception:
                pass
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
        # Runs on the real uploaded paths before ANY model call when files are pre-selected.
        # If files is empty (Autonomous STAC Discovery mode), the gate runs right after
        # the approved STAC scenes are staged.
        if files:
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

        is_plan_approved = (run_dir / "plan_approved.flag").exists()

        if is_plan_approved:
            # Plan is already approved and scenes are staged on disk!
            # Bypass Phase 0 (STAC discovery/download) and Phase 1 (Plan review).
            saved_plan = ""
            cp = None
            current_stage = None
            try:
                cp = load_checkpoint(task_id, cfg.runs_dir) if task_id else None
                if cp:
                    current_stage = cp.get("current_stage")
                    saved_plan = cp.get("plan", "")
                elif task_state and getattr(task_state, "plan", None):
                    saved_plan = task_state.plan
            except Exception:
                pass

            plan_file = run_dir / "plan.json"
            if plan_file.exists():
                try:
                    plan_file.unlink()
                except Exception:
                    pass

            from harness.orchestrator import find_artifacts
            existing_artifacts = find_artifacts(run_dir)
            last_status = _read_status(run_dir)
            code_already_done = bool(last_status.get("ok")) and len(existing_artifacts) > 0

            if code_already_done:
                print(f"[pi] code execution already succeeded in previous run ({len(existing_artifacts)} deliverables verified). Fast-forwarding directly to visual validation...", flush=True)
                step({"type": "artifacts", "artifacts": existing_artifacts})
                step({"type": "status", "status": "running", "step": "Code already executed — proceeding to visual validation..."})
                if task_state:
                    task_state.status = "running"
            else:
                mounted_list = "\n".join(f"- `/workspace/input/{Path(f).name}` (host: `{f}`)" for f in files)
                resume_prompt = (
                    f"You are GeoLLM analyzing: {question}\n\n"
                    f"The user has already APPROVED your scientific analysis plan:\n{saved_plan}\n\n"
                    f"All required input rasters are already verified and mounted in `/workspace/input/`:\n{mounted_list}\n\n"
                    "Proceed immediately to implement and run the analysis code using `run_geospatial_code`. "
                    "Write all requested GeoTIFF/PNG files and verify deliverables."
                )
                step({"type": "status", "status": "running", "step": "Plan approved — resuming container execution..."})
                if task_state:
                    task_state.status = "running"
                pi.drain()
                stats = pi.run_prompt(
                    resume_prompt,
                    cfg.idle_timeout_s,
                    cfg.total_timeout_s,
                    cfg.max_tool_calls,
                    on_event,
                )
                answer = pi.last_assistant_text()
        else:
            is_stac_approved = (run_dir / "stac_approved.flag").exists() and (run_dir / "stac_approved.json").exists()

            if is_stac_approved:
                # STAC satellite scenes were already approved in an earlier session!
                # Bypass Phase 0 search & preview, resume downloads of remaining bands, and advance to Plan generation.
                stac_approved_file = run_dir / "stac_approved.json"
                stac_data = None
                try:
                    stac_data = json.loads(stac_approved_file.read_text(encoding="utf-8"))
                except Exception as exc:
                    warnings.append(f"Failed to read stac_approved.json: {exc}")

                if stac_data:
                    scenes = stac_data.get("scenes") or []
                    expected_filenames = set()
                    for sc in scenes:
                        col = sc.get("collection") or "sentinel-2-l2a"
                        dt_str = str(sc.get("datetime") or "scene")[:10]
                        assets = sc.get("assets") or ["B04", "B03", "B02", "B08"]
                        for asset_key in assets:
                            expected_filenames.add(f"{col}_{dt_str}_{asset_key}.tif")

                    allowed_file = run_dir / "allowed_files.json"
                    all_staged = False
                    staged_files = []
                    stage_errors = []
                    if allowed_file.exists():
                        try:
                            cand_files = json.loads(allowed_file.read_text(encoding="utf-8"))
                            cand_names = {Path(f).name for f in cand_files}
                            if (
                                expected_filenames
                                and expected_filenames.issubset(cand_names)
                                and all(Path(f).exists() and Path(f).stat().st_size > 1000 for f in cand_files)
                            ):
                                staged_files = cand_files
                                all_staged = True
                        except Exception:
                            pass

                    staged_dir = run_dir / "staged_inputs"
                    if not all_staged and staged_dir.is_dir() and expected_filenames:
                        existing_staged = [
                            staged_dir / fname for fname in expected_filenames
                            if (staged_dir / fname).exists() and (staged_dir / fname).stat().st_size > 1000
                        ]
                        if len(existing_staged) == len(expected_filenames):
                            staged_files = [str(p) for p in existing_staged]
                            all_staged = True

                    if not all_staged:
                        step({"type": "status", "status": "running", "step": "Resuming staging approved STAC scenes at native resolution..."})
                        staged_files, stage_errors = _stage_approved_stac_scenes(stac_data, step, run_dir=run_dir)
                    else:
                        step({"type": "status", "status": "running", "step": "Approved STAC rasters already verified on disk."})

                    if staged_files and not stage_errors:
                        files = list(staged_files)
                        if task_state:
                            task_state.files = list(files)
                        (run_dir / "allowed_files.json").write_text(json.dumps([str(f) for f in files]), encoding="utf-8")
                        step({"type": "stac_staged", "files": files})
                        save_checkpoint(task_id, "stac_staged", {"staged_inputs": files, "status": "running", "step": f"Staged {len(files)} native STAC rasters"}, cfg.runs_dir)

                        # Run Input Quality Gate on staged rasters
                        try:
                            from harness.validation.input_gate import run_input_gate
                            gate = run_input_gate(files, on_step=step)
                        except Exception as exc:
                            warnings.append(f"Input quality gate error: {exc}")

                        facts = inspect_dataset(files)
                        state["facts"] = json.dumps(facts, default=str)[:3000]
                        pi.drain()
                        mounted_list = "\n".join(f"- `/workspace/input/{Path(f).name}` (host: `{f}`)" for f in files)
                        resume_stac_prompt = (
                            f"You are GeoLLM analyzing: {question}\n\n"
                            "The user approved your STAC satellite scenes! They have been cropped to the AOI at 100% original "
                            "native resolution, verified by the Input Quality Gate, and mounted in `/workspace/input/`:\n"
                            f"{mounted_list}\n\n"
                            f"Inspected dataset metadata:\n{json.dumps(facts, indent=2, default=str)[:4000]}\n\n"
                            "Now proceed directly to Phase 1: formulate your scientific methodology and call `propose_plan(plan=..., expected_outputs=[...])`."
                        )
                        step({"type": "status", "status": "running", "step": "STAC imagery staged — generating analysis plan..."})
                        if task_state:
                            task_state.status = "running"
                        stats = pi.run_prompt(
                            resume_stac_prompt,
                            cfg.idle_timeout_s,
                            cfg.total_timeout_s,
                            cfg.max_tool_calls,
                            on_event,
                        )
                        answer = pi.last_assistant_text()
            else:
                stats = pi.run_prompt(prompt, cfg.idle_timeout_s, cfg.total_timeout_s,
                                      cfg.max_tool_calls, on_event)
                answer = pi.last_assistant_text()

                # ---- Phase 0: STAC Preview & Approval Gate ----
                stac_preview_file = run_dir / "stac_preview.json"
                stac_revisions = 0
                while stac_revisions <= 5 and stac_preview_file.exists():
                    try:
                        stac_data = json.loads(stac_preview_file.read_text(encoding="utf-8"))
                        stac_preview_file.unlink()
                    except Exception:
                        break

                    if task_state and not getattr(task_state, "auto_approve", False):
                        task_state.approval_event.clear()
                        task_state.stac_preview = stac_data
                        task_state.status = "pending_stac_approval"
                        save_checkpoint(
                            task_id,
                            "stac_search_completed",
                            {
                                "status": "pending_stac_approval",
                                "step": "STAC satellite preview ready — review required",
                                "preview": stac_data,
                            },
                            cfg.runs_dir,
                        )
                        step({"type": "stac_preview_ready", "preview": stac_data})
                        step({"type": "status", "status": "pending_stac_approval"})

                        approved = task_state.approval_event.wait(timeout=1800)
                        if not approved or task_state.error == "Cancelled by user":
                            if not approved:
                                task_state.error = "STAC preview approval timed out after 30 minutes"
                            task_state.status = "failed"
                            return _result("failed", task_state.error, run_dir)

                        if task_state.revision_feedback:
                            stac_revisions += 1
                            try:
                                (run_dir / "stac_approved.flag").unlink(missing_ok=True)
                                (run_dir / "stac_approved.json").unlink(missing_ok=True)
                            except Exception:
                                pass
                            step({"type": "status", "status": "running"})
                            task_state.status = "running"
                            fb = task_state.revision_feedback
                            task_state.revision_feedback = None
                            pi.drain()
                            stats = pi.run_prompt(
                                f"The user reviewed your STAC satellite image preview and requested changes:\n{fb}\n\n"
                                "Use `search_stac` to find updated scenes matching the user's feedback, "
                                "then call `propose_stac_scenes` again.",
                                cfg.idle_timeout_s, cfg.total_timeout_s,
                                cfg.max_tool_calls, on_event,
                            )
                            answer = pi.last_assistant_text()
                            continue

                    # Approved (or CLI auto-approve): stage the scenes cropped to AOI at 100% native resolution
                    if task_state:
                        task_state.status = "running"
                        task_state.stac_preview = None

                    # Persist STAC approval immediately before launching downloads!
                    stac_approved_flag = run_dir / "stac_approved.flag"
                    stac_approved_file = run_dir / "stac_approved.json"
                    try:
                        stac_approved_file.write_text(json.dumps(stac_data, indent=2), encoding="utf-8")
                        stac_approved_flag.touch(exist_ok=True)
                        save_checkpoint(
                            task_id,
                            "stac_approved",
                            {
                                "stac_data": stac_data,
                                "status": "running",
                                "step": "Staging approved STAC scenes at native resolution...",
                            },
                            cfg.runs_dir,
                        )
                    except Exception as exc:
                        print(f"[pi] Warning: failed to save stac_approved checkpoint: {exc}", flush=True)

                    step({"type": "status", "status": "running", "step": "Staging approved STAC scenes at native resolution..."})
                    staged_files, stage_errors = _stage_approved_stac_scenes(stac_data, step, run_dir=run_dir)

                    if not staged_files or stage_errors:
                        stac_revisions += 1
                        err_msg = "; ".join(stage_errors) if stage_errors else "No files were staged."
                        pi.drain()
                        stats = pi.run_prompt(
                            f"Staging the selected STAC scenes encountered an issue:\n{err_msg}\n\n"
                            "Please adjust the bounding box or select alternative scenes/collections with `search_stac` "
                            "and call `propose_stac_scenes` again.",
                            cfg.idle_timeout_s, cfg.total_timeout_s,
                            cfg.max_tool_calls, on_event,
                        )
                        answer = pi.last_assistant_text()
                        continue

                    files = list(staged_files)
                    if task_state:
                        task_state.files = list(files)
                    (run_dir / "allowed_files.json").write_text(json.dumps([str(f) for f in files]), encoding="utf-8")
                    step({"type": "stac_staged", "files": files})
                    save_checkpoint(task_id, "stac_staged", {"staged_inputs": files, "status": "running", "step": f"Staged {len(files)} native STAC rasters"}, cfg.runs_dir)

                    # Run Input Quality Gate on the newly staged rasters
                    gate_passed = True
                    try:
                        from harness.validation.input_gate import run_input_gate
                        gate = run_input_gate(files, on_step=step)
                        if gate is None:
                            gate_passed = False
                    except Exception as exc:
                        warnings.append(f"Input quality gate error: {exc}")

                    if not gate_passed:
                        stac_revisions += 1
                        pi.drain()
                        stats = pi.run_prompt(
                            "The staged STAC scenes did not pass the Input Quality Gate (insufficient valid pixels, "
                            "cloud contamination, or <15% multi-temporal overlap inside the AOI). "
                            "Please search STAC with `search_stac` for clearer dates or better-overlapping tiles "
                            "and call `propose_stac_scenes` again.",
                            cfg.idle_timeout_s, cfg.total_timeout_s,
                            cfg.max_tool_calls, on_event,
                        )
                        answer = pi.last_assistant_text()
                        continue

                    facts = inspect_dataset(files)
                    state["facts"] = json.dumps(facts, default=str)[:3000]
                    pi.drain()
                    mounted_list = "\n".join(f"- `/workspace/input/{Path(f).name}` (host: `{f}`)" for f in files)
                    stats = pi.run_prompt(
                        "The user approved your STAC satellite scenes! They have been cropped to the AOI at 100% original "
                        "native resolution, verified by the Input Quality Gate, and mounted in `/workspace/input/`:\n"
                        f"{mounted_list}\n\n"
                        f"Inspected dataset metadata:\n{json.dumps(facts, indent=2, default=str)[:4000]}\n\n"
                        "Now proceed to Phase 1: formulate your scientific methodology and call `propose_plan(plan=..., expected_outputs=[...])`.",
                        cfg.idle_timeout_s, cfg.total_timeout_s,
                        cfg.max_tool_calls, on_event,
                    )
                    answer = pi.last_assistant_text()
                    break

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
                while not plan_approved and revisions <= 3:
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
                    save_checkpoint(
                        task_id,
                        "plan_generated",
                        {
                            "plan": task_state.plan,
                            "status": "pending_approval",
                            "step": "Plan review required",
                        },
                        cfg.runs_dir,
                    )
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
                    save_checkpoint(task_id, "plan_approved", {"plan": task_state.plan if task_state else "", "plan_approved": True, "status": "running", "step": "Plan Approved — Running Container Pipeline"}, cfg.runs_dir)
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
        cp = load_checkpoint(task_id, cfg.runs_dir) if task_id else None
        current_stage = cp.get("current_stage") if cp else None

        output_pngs = _png_rels(run_dir)
        if current_stage == "vision_validation_completed":
            print("[pi] visual validation already completed in previous checkpoint, skipping vision QA loop", flush=True)
            step({"type": "status", "status": "running", "step": "Visual validation completed — preparing findings report..."})
        elif llm.vision_available() and len(output_pngs) > 0:
            try:
                from harness.checkpoint import save_checkpoint
                save_checkpoint(
                    task_id or "task_1",
                    "vision_validation_started",
                    {
                        "status": "running",
                        "step": "Visual validation in progress...",
                        "target_maps": [Path(r).name for r in output_pngs],
                    },
                    cfg.runs_dir,
                )
            except Exception:
                pass

            max_r = cfg.vision_max_retries
            feedback_memory: list = []
            cached_passed: Dict[str, Dict[str, Any]] = {}
            seen_rel_names: set = set()
            needs_recheck_names: set = set()

            for attempt in range(max_r + 1):          # +1 = final re-check after the last fix
                if (run_dir / "cancelled.flag").exists() or (task_state and task_state.error == "Cancelled by user"):
                    print("[pi] Visual validation loop aborted due to task cancellation", flush=True)
                    break

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
                    try:
                        from harness.orchestrator import find_artifacts
                        final_arts = find_artifacts(run_dir)
                        from harness.checkpoint import save_checkpoint
                        save_checkpoint(
                            task_id or "task_1",
                            "vision_validation_completed",
                            {
                                "status": "running",
                                "step": "Visual validation completed — deliverables verified",
                                "verified_outputs": [a["name"] for a in final_arts],
                            },
                            cfg.runs_dir,
                        )
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
                    final_arts = find_artifacts(run_dir)
                    step({"type": "artifacts", "artifacts": final_arts})
                    from harness.checkpoint import save_checkpoint
                    save_checkpoint(
                        task_id or "task_1",
                        "vision_validation_completed",
                        {
                            "status": "running",
                            "step": "Visual validation completed",
                            "verified_outputs": [a["name"] for a in final_arts],
                        },
                        cfg.runs_dir,
                    )
                except Exception:
                    pass

            # If resuming after code execution without re-generating text answer, synthesize findings
            if not answer or "Plan proposed" in answer or "plan is ready" in answer:
                last_status = _read_status(run_dir)
                res_dict = last_status.get("result")
                if isinstance(res_dict, dict) and res_dict.get("summary"):
                    summary_data = res_dict["summary"]
                    if isinstance(summary_data, dict):
                        finding = summary_data.get("finding", "")
                        evidence = summary_data.get("evidence", [])
                        evidence_str = "\n".join(f"- {e}" for e in evidence) if isinstance(evidence, list) else str(evidence)
                        answer = f"### Scientific Analysis Findings\n\n{finding}\n\n**Evidence:**\n{evidence_str}"
                    else:
                        answer = str(summary_data)
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
        # Fallback: if latest attempt failed, check if an earlier attempt in THIS run succeeded
    if status != "ok" and isinstance(sf, Path) and sf.exists():
        cand_att = last.get("attempt", 0) if isinstance(last, dict) else 0
        if cand_att > 1:
            for prev_num in range(cand_att - 1, 0, -1):
                prev_out = run_dir / f"attempt_{prev_num:02d}" / "outputs"
                if prev_out.is_dir() and (prev_out / "result.json").is_file():
                    valid_files = [str(f) for f in prev_out.iterdir() if f.is_file()]
                    if valid_files:
                        artifacts = valid_files
                        status = "partial"
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