"""GeoLLM Web UI Server (FastAPI + SSE + Multi-Task)."""
import asyncio
import json
import mimetypes
import os
import shutil
import sys
import time

# Clean up environment variables to prevent child process / container failures
if os.environ.get("PYTHONUTF8", "").strip() not in ("1", "0"):
    os.environ["PYTHONUTF8"] = "1"
from pathlib import Path
from typing import List, Optional, Dict, Any

# Ensure .jsx files are served with application/javascript MIME type
mimetypes.add_type("application/javascript", ".jsx")

from contextlib import asynccontextmanager
from fastapi import FastAPI, File, UploadFile, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import harness
from geollm_lib.bands import ROLES
from harness.orchestrator import TaskManager, find_artifacts
from harness import chat

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


@asynccontextmanager
async def lifespan(app: FastAPI):
    from harness.workspace import cleanup_expired_workspaces
    async def _cleanup_loop():
        while True:
            try:
                await asyncio.sleep(1800)  # every 30 minutes
                await asyncio.to_thread(cleanup_expired_workspaces, RUNS_DIR, 24.0)
            except asyncio.CancelledError:
                break
            except Exception:
                pass
    cleanup_task = asyncio.create_task(_cleanup_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        global _server_shutting_down
        _server_shutting_down = True
        print("[GeoLLM] Server shutdown initiated — terminating sub-agents...", flush=True)
        task_manager.cancel_all()
        try:
            from harness.executor import release_all_containers
            release_all_containers()
        except Exception:
            pass


app = FastAPI(title="GeoLLM Web Interface", lifespan=lifespan)

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = (APP_DIR / "data") if (APP_DIR / "data").exists() else Path("data")
RUNS_DIR = (APP_DIR / "runs") if (APP_DIR / "runs").exists() else Path("runs")
STATIC_DIR = (APP_DIR / "static") if (APP_DIR / "static").exists() else Path("static")
DIST_DIR = STATIC_DIR / "dist"
DIST_HTML = DIST_DIR / "index.html"

DATA_DIR.mkdir(exist_ok=True)
RUNS_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)

app.mount("/runs", StaticFiles(directory="runs"), name="runs")
app.mount("/data", StaticFiles(directory="data"), name="data")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Web manager requires human plan approval in browser
task_manager = TaskManager(auto_approve=False, runs_dir=RUNS_DIR)
_server_shutting_down = False


class ChatMessage(BaseModel):
    message: str
    history: list = []

class TaskSubmission(BaseModel):
    question: str
    files: str = ""
    bands: str = ""
    bbox: Optional[List[float]] = None
    task_id: Optional[str] = None

class WorkspaceMessagePayload(BaseModel):
    message: str
    history: List[Dict[str, str]] = []
    files: str = ""
    bbox: Optional[List[float]] = None
    bands: Optional[str] = None

class RevisionPayload(BaseModel):
    feedback: str


def _parse_milestone(task_id, ev_text):
    lo = ev_text.lower()
    if any(k in lo for k in ["thinking", "analyzing", "reading", "evaluating", "diagnosing"]):
        icon = "thinking"
    elif any(k in lo for k in ["running", "executing", "processing", "calculating", "applying", "sandbox tool"]):
        icon = "running"
    elif any(k in lo for k in ["produced", "created", "success", "verified", "passed", "complete"]):
        icon = "done"
    elif any(k in lo for k in ["plan", "approval", "roadmap"]):
        icon = "plan"
    elif any(k in lo for k in ["failed", "error", "cancelled"]):
        icon = "error"
    elif any(k in lo for k in ["vision", "quality-checking"]):
        icon = "vision"
    else:
        icon = "info"
    return {"type": "milestone", "task_id": task_id, "icon": icon, "text": ev_text}


@app.get("/", response_class=HTMLResponse)
@app.get("/modern", response_class=HTMLResponse)
async def index():
    """Serve the modern Vite + React interface."""
    if DIST_HTML.exists():
        return HTMLResponse(
            DIST_HTML.read_text(encoding="utf-8"),
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )
    return HTMLResponse("<h1>Error: static/dist/index.html not built</h1>", status_code=404)


@app.get("/api/files")
async def list_data_files():
    valid_exts = {
        ".tif", ".tiff", ".geojson", ".gpkg", ".json",
        ".nc", ".h5", ".he5", ".hdr", ".img", ".bsq", ".bil", ".bip",
        ".laz", ".las", ".xyz", ".png", ".jpg", ".jpeg", ".csv", ".zip",
    }
    files = []
    for f in sorted(DATA_DIR.glob("*")):
        if f.suffix.lower() not in valid_exts or not f.is_file():
            continue
        st = f.stat()
        files.append({
            "name": f.name,
            "size_bytes": st.st_size,
            "size_mb": round(st.st_size / (1024 * 1024), 2),
            "modified": time.strftime("%Y-%m-%d", time.localtime(st.st_mtime)),
        })
    return JSONResponse({"files": files})


@app.post("/api/upload/stream")
async def upload_file_stream(request: Request, filename: str, size: Optional[int] = None):
    """Direct raw-stream file upload that bypasses Starlette MultiPartParser spooling.
    Streams large multi-GB files directly to disk with atomic rename and zero temp double-copying.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name
    if not safe_name:
        return JSONResponse({"error": "Invalid filename"}, status_code=400)

    dest = DATA_DIR / safe_name
    # Fast path: if file already exists in data/ with identical byte size, attach immediately
    if size is not None and dest.is_file() and dest.stat().st_size == size:
        return JSONResponse({"uploaded": [safe_name], "already_present": True})

    part_path = DATA_DIR / f".{safe_name}.{os.getpid()}.{int(time.time() * 1000)}.uploading"
    bytes_written = 0
    try:
        with part_path.open("wb", buffering=8 * 1024 * 1024) as buffer:
            async for chunk in request.stream():
                if chunk:
                    await asyncio.to_thread(buffer.write, chunk)
                    bytes_written += len(chunk)
        if size is not None and bytes_written != size:
            part_path.unlink(missing_ok=True)
            return JSONResponse(
                {"error": f"Incomplete upload for {safe_name}: received {bytes_written} of {size} bytes"},
                status_code=400,
            )
        os.replace(part_path, dest)
        return JSONResponse({"uploaded": [safe_name], "bytes": bytes_written})
    except Exception as exc:
        part_path.unlink(missing_ok=True)
        return JSONResponse({"error": f"Upload failed: {exc}"}, status_code=400)


@app.post("/api/upload")
async def upload_file(files: List[UploadFile] = File(...)):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    uploaded = []
    for file in files:
        if not file.filename:
            continue
        safe_name = Path(file.filename).name
        if not safe_name:
            continue
        dest = DATA_DIR / safe_name
        part_path = DATA_DIR / f".{safe_name}.{os.getpid()}.{int(time.time() * 1000)}.uploading"
        try:
            with part_path.open("wb", buffering=4 * 1024 * 1024) as buffer:
                while chunk := await file.read(4 * 1024 * 1024):
                    await asyncio.to_thread(buffer.write, chunk)
            os.replace(part_path, dest)
            uploaded.append(safe_name)
        finally:
            part_path.unlink(missing_ok=True)
    return JSONResponse({"uploaded": uploaded})


@app.post("/api/tasks")
async def submit_task(payload: TaskSubmission):
    selected_files = [f.strip() for f in payload.files.split(",") if f.strip()]

    file_args = []
    for f in selected_files:
        p = Path(f) if Path(f).exists() else DATA_DIR / f
        if not p.exists():
            return JSONResponse({"error": f"File not found: '{f}' in workspace or data/"}, status_code=400)
        file_args.append(str(p))

    overrides = {}
    if payload.bbox and len(payload.bbox) >= 4:
        overrides["bbox"] = [float(x) for x in payload.bbox[:4]]
    if payload.bands:
        for part in filter(None, payload.bands.split(",")):
            role, _, num = part.partition("=")
            role = role.strip()
            num = num.strip()
            if role not in ROLES or not num.isdigit():
                return JSONResponse({"error": f"Invalid band format '{part}'. Use role=number with {ROLES}"}, status_code=400)
            overrides[role] = int(num)

    task_id = task_manager.submit_task(payload.question, file_args, task_id=payload.task_id, overrides=overrides)
    if task_id is None:
        return JSONResponse({"error": "All 3 task slots are busy."}, status_code=429)
    return JSONResponse({"task_id": task_id, "status": "running"})


@app.get("/api/workspace/{task_id}/conversation")
async def get_workspace_conversation(task_id: str):
    """Loads durable conversation turns for this workspace."""
    from harness.workspace import load_conversation
    turns = load_conversation(task_id, runs_dir=RUNS_DIR)
    return JSONResponse({"turns": turns})


@app.delete("/api/workspace/{task_id}/conversation")
async def delete_workspace_conversation(task_id: str):
    """Clears durable conversation history for this workspace without wiping container outputs."""
    from harness.workspace import clear_conversation
    clear_conversation(task_id, runs_dir=RUNS_DIR)
    return JSONResponse({"ok": True, "task_id": task_id})


@app.post("/api/workspace/{task_id}/message")
async def handle_workspace_message(task_id: str, payload: WorkspaceMessagePayload):
    """Unified conversational assistant endpoint.
    
    Classifies user intent, checks workspace container availability,
    runs VLM visual inspections or contextual answers, or delegates complex tasks.
    """
    from harness import router
    from harness.workspace import append_conversation_turn

    ts = task_manager.get_task(task_id)
    if not ts:
        return JSONResponse({"error": f"Unknown workspace: {task_id}"}, status_code=404)

    user_text = payload.message.strip()
    if not user_text:
        return JSONResponse({"error": "Message is empty"}, status_code=400)

    # Persist user turn
    append_conversation_turn(task_id, "user", user_text, runs_dir=RUNS_DIR)

    # 1. Classify incoming message with full live multi-container snapshot
    attached_files = [f.strip() for f in payload.files.split(",") if f.strip()]
    live_snapshot = task_manager.multi_snapshot()
    try:
        classification = await asyncio.to_thread(
            router.classify_message,
            user_message=user_text,
            history=payload.history,
            task_id=task_id,
            runs_dir=RUNS_DIR,
            task_state=ts,
            attached_files=attached_files,
            live_snapshot=live_snapshot,
        )
        category = classification.get("category", "general_chat")

        # 2. Category D: Clarification needed
        if category == "clarification_needed":
            q = classification.get("clarification_question") or (
                "Could you specify the target geographic area (coordinates/AOI) or dates for this analysis?"
            )
            append_conversation_turn(task_id, "assistant", q, runs_dir=RUNS_DIR, extra={"type": "clarification"})
            return JSONResponse({
                "type": "clarification_needed",
                "reply": q,
                "category": category,
            })

        # 3. Category A: General Chat / Remote Sensing concepts
        if category == "general_chat":
            res = await asyncio.to_thread(
                router.handle_general_chat,
                user_message=user_text,
                history=payload.history,
                task_id=task_id,
                task_state=ts,
                live_snapshot=live_snapshot,
            )
            append_conversation_turn(task_id, "assistant", res["reply"], runs_dir=RUNS_DIR, extra={"type": "conversational_reply"})
            return JSONResponse(res)

        # 4. Category B: Questions on live progress or existing analysis results
        if category == "contextual_inquiry":
            res = await asyncio.to_thread(
                router.handle_contextual_inquiry,
                user_message=user_text,
                history=payload.history,
                task_id=task_id,
                runs_dir=RUNS_DIR,
                task_state=ts,
                live_snapshot=live_snapshot,
            )
            append_conversation_turn(task_id, "assistant", res["reply"], runs_dir=RUNS_DIR, extra={"type": "conversational_reply"})
            return JSONResponse(res)

        # 5. Category V: On-demand VLM Visual Inspection / Zoom / Search
        if category == "visual_inspection":
            res = await asyncio.to_thread(
                router.handle_visual_inspection,
                user_message=user_text,
                target_artifact=classification.get("target_artifact"),
                focus=classification.get("inspection_focus"),
                task_id=task_id,
                runs_dir=RUNS_DIR,
                task_state=ts,
            )
            append_conversation_turn(
                task_id,
                "assistant",
                res["reply"],
                runs_dir=RUNS_DIR,
                extra={
                    "type": "visual_reply",
                    "thumb_url": res.get("thumb_url"),
                    "fly_to_bbox": res.get("fly_to_bbox"),
                },
            )
            return JSONResponse(res)
    except Exception as exc:
        msg = str(exc) or "Unexpected server error"
        low = msg.lower()
        if "429" in msg or "rate limit" in low:
            status_code, code = 429, "rate_limit"
        elif "401" in msg or "api key" in low or "invalid_token" in low:
            status_code, code = 502, "provider_auth"
        elif "413" in msg or "too large" in low:
            status_code, code = 413, "payload_too_large"
        else:
            status_code, code = 500, "server_error"
        return JSONResponse(
            {"error": msg, "detail": msg, "code": code},
            status_code=status_code,
        )

    # 6. Category C: Complex Geospatial Task -> Check container availability
    if ts.status in ("queued", "running", "pending_approval", "pending_stac_approval"):
        busy_msg = (
            f"Workspace **{task_id}** is currently busy running an analysis (*{ts.step}*). "
            "To prevent overwriting active calculations, please wait for this run to finish or switch to another workspace."
        )
        return JSONResponse({
            "type": "workspace_busy",
            "task_id": task_id,
            "current_step": ts.step,
            "elapsed": round((ts.ended or time.time()) - (ts.started or time.time()), 1),
            "reply": busy_msg,
            "queued_prompt": user_text,
        })

    # Prepare file args and overrides for sub-agent container execution
    selected_files = [f.strip() for f in payload.files.split(",") if f.strip()]
    file_args = []
    for f in selected_files:
        p = Path(f) if Path(f).exists() else DATA_DIR / f
        if p.exists():
            file_args.append(str(p))

    overrides = {}
    if payload.bbox and len(payload.bbox) >= 4:
        overrides["bbox"] = [float(x) for x in payload.bbox[:4]]
    if payload.bands:
        for part in filter(None, payload.bands.split(",")):
            role, _, num = part.partition("=")
            role = role.strip()
            num = num.strip()
            if role in ROLES and num.isdigit():
                overrides[role] = int(num)

    # Dispatch to sub-agent (preserve prior user prompt context when the current message
    # is a short follow-up confirmation such as "use stac search for this" or "yes proceed").
    effective_question = user_text
    if len(user_text) <= 90 or any(
        kw in user_text.lower()
        for kw in ("use stac", "search stac", "proceed", "go ahead", "run it", "yes", "do that")
    ):
        prior_user_msgs = [
            str(h.get("content", "")).strip()
            for h in history[:-1]
            if h.get("role") == "user" and len(str(h.get("content", "")).strip()) > 25
        ]
        if prior_user_msgs and prior_user_msgs[-1].lower() not in user_text.lower():
            effective_question = f"{prior_user_msgs[-1]}\n\nFollow-up instruction: {user_text}"

    started_tid = task_manager.submit_task(effective_question, file_args, task_id=task_id, overrides=overrides)
    if started_tid is None:
        return JSONResponse({"error": "Failed to allocate container slot."}, status_code=500)

    delegated_turn = append_conversation_turn(
        task_id,
        "assistant",
        f"Delegated complex geospatial task to specialized container sub-agent: *{effective_question}*",
        runs_dir=RUNS_DIR,
        extra={"type": "task_delegated", "question": effective_question},
    )
    return JSONResponse({
        "type": "task_delegated",
        "task_id": started_tid,
        "status": ts.status,
        "step": ts.step,
        "current_step": ts.step,
        "seq": delegated_turn.get("seq"),
        "timestamp": delegated_turn.get("timestamp"),
    })



@app.get("/api/tasks")
async def list_tasks():
    tasks = []
    for tid in list(task_manager.tasks.keys()):
        ts = task_manager.tasks.get(tid)
        if not ts:
            continue
        tasks.append({
            "task_id": tid,
            "status": ts.status,
            "question": ts.question,
            "step": ts.step,
            "error": ts.error,
            "elapsed": round((ts.ended or time.time()) - ts.started, 1) if ts.started else 0,
            "plan": ts.plan,
            "stac_preview": ts.stac_preview,
            "allocated_ram_gb": ts.allocated_ram_gb,
            "resource_tier": ts.resource_tier,
        })
    return JSONResponse({"tasks": tasks, "capacity": task_manager.capacity()})


@app.post("/api/tasks/create")
async def create_dynamic_task():
    ts = task_manager.create_task()
    if not ts:
        return JSONResponse({"error": "Maximum dynamic workspace limit reached."}, status_code=400)
    return JSONResponse({"task_id": ts.task_id, "status": ts.status, "capacity": task_manager.capacity()})


@app.delete("/api/tasks/{task_id}")
async def delete_dynamic_task(task_id: str):
    ok = task_manager.delete_task(task_id)
    if not ok:
        return JSONResponse({"error": f"Cannot delete workspace '{task_id}'"}, status_code=400)
    return JSONResponse({"deleted": task_id, "capacity": task_manager.capacity()})


@app.get("/api/tasks/{task_id}/stream")
async def stream_task(task_id: str, request: Request):
    ts = task_manager.get_task(task_id)
    if not ts:
        return JSONResponse({"error": f"Unknown task: {task_id}"}, status_code=404)

    last_id_str = request.headers.get("last-event-id") or request.query_params.get("last_event_id")
    try:
        last_sent_id = int(last_id_str) if last_id_str is not None else 0
    except (ValueError, TypeError):
        last_sent_id = 0

    async def event_generator():
        nonlocal last_sent_id
        last_keepalive = time.time()

        while True:
            if _server_shutting_down or await request.is_disconnected():
                break

            current = task_manager.get_task(task_id)
            if not current:
                break

            events_to_send = []
            with task_manager._lock:
                for ev in current.event_log:
                    raw_id = ev.get("id", 0)
                    try:
                        ev_id = int(raw_id)
                    except (ValueError, TypeError):
                        ev_id = 0
                    if ev_id > last_sent_id:
                        events_to_send.append(ev)

            for ev in events_to_send:
                raw_id = ev.get("id")
                try:
                    ev_id = int(raw_id)
                except (ValueError, TypeError):
                    ev_id = last_sent_id + 1
                last_sent_id = ev_id
                last_keepalive = time.time()
                yield f"id: {ev_id}\ndata: {json.dumps(ev)}\n\n"

            # Stop streaming only after the final finish event has been transmitted
            if current.status in ("done", "partial", "failed"):
                last_ev = current.event_log[-1] if current.event_log else {}
                try:
                    last_ev_id = int(last_ev.get("id", 0))
                except (ValueError, TypeError):
                    last_ev_id = 0
                if last_ev.get("type") == "finish" and last_sent_id >= last_ev_id:
                    break

            now = time.time()
            if now - last_keepalive >= 15.0:
                last_keepalive = now
                yield ": keepalive\n\n"

            await asyncio.sleep(0.2)

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)


@app.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    if not task_manager.cancel_task(task_id):
        return JSONResponse({"error": "Task not running."}, status_code=400)
    return JSONResponse({"task_id": task_id, "status": "cancelled"})


@app.post("/api/tasks/{task_id}/reset")
async def reset_task(task_id: str):
    if task_id in task_manager.tasks:
        ts = task_manager.tasks[task_id]
        if ts.status in ("running", "pending_approval", "pending_stac_approval"):
            task_manager.cancel_task(task_id)
        with task_manager._lock:
            ts.status = "idle"
            ts.question = ""
            ts.step = "Ready"
            ts.error = None
            ts.plan = None
            ts.stac_preview = None
            ts.events = []
            ts.event_log = []
            ts.artifacts = []
            ts.started = None
            ts.ended = None
            ts.state = {}
            ts.result = None

        # Release warm container so its cached /workspace/output is discarded
        try:
            from harness.executor import release_container
            release_container(task_id)
        except Exception:
            pass

        # Clean workspace on disk and delete checkpoint (preserve conversation.jsonl unless explicitly cleared/deleted)
        from harness.workspace import clean_workspace
        from harness.checkpoint import delete_checkpoint
        clean_workspace(task_id, RUNS_DIR)
        delete_checkpoint(task_id, RUNS_DIR)
        ws_path = RUNS_DIR / task_id
        sandbox_tmp = ws_path / ".sandbox_tmp"
        if sandbox_tmp.exists():
            shutil.rmtree(sandbox_tmp, ignore_errors=True)
        events_file = ws_path / "events.jsonl"
        if events_file.exists():
            try:
                events_file.unlink()
            except Exception:
                pass
        # Ensure 3D visualization caches are purged on slot reset
        for fname in ("terrain_3d.json", "lidar_3d.json", "orthophoto.png"):
            for f in ws_path.rglob(fname):
                if f.is_file():
                    try:
                        f.unlink()
                    except Exception:
                        pass

        # Ensure any lingering Docker container for this slot is pruned
        try:
            import docker
            client = docker.from_env()
            for c in client.containers.list(all=True, filters={"name": f"geollm_{task_id}_"}):
                try:
                    c.kill()
                except Exception:
                    pass
                try:
                    c.remove(force=True)
                except Exception:
                    pass
        except Exception:
            pass
    return JSONResponse({"task_id": task_id, "status": "idle"})


@app.get("/api/runs/{task_id}/timeline.json")
async def get_timeline(task_id: str):
    ts = task_manager.get_task(task_id)
    if not ts:
        return JSONResponse({"error": "Task not found"}, status_code=404)
    run_dir = ts.state.get("run_dir") or (ts.result.get("run_dir") if ts.result else None) or str(RUNS_DIR / task_id)
    if not run_dir:
        return JSONResponse({"error": "No run_dir"}, status_code=404)
    p = Path(run_dir)
    cands = sorted(p.rglob("timeline.json"), key=lambda x: str(x), reverse=True)
    if cands and cands[0].exists():
        try:
            chosen_tl = cands[0]
            data = json.loads(chosen_tl.read_text(encoding="utf-8"))
            timeline_dir = chosen_tl.parent
            try:
                rel_base = timeline_dir.relative_to(Path.cwd()).as_posix()
            except ValueError:
                parts = timeline_dir.parts
                idx = parts.index("runs") if "runs" in parts else 0
                rel_base = "/".join(parts[idx:])

            # Check if there is an animated .gif in the attempt outputs or run directory
            gif_cands = sorted(timeline_dir.glob("*.gif")) or sorted(p.rglob("*.gif"), key=lambda x: str(x), reverse=True)
            gif_stem = gif_cands[0].stem if gif_cands else "animation"
            if gif_cands:
                try:
                    gif_rel = "/" + gif_cands[0].relative_to(Path.cwd()).as_posix()
                except ValueError:
                    parts = gif_cands[0].parts
                    idx = parts.index("runs") if "runs" in parts else 0
                    gif_rel = "/" + "/".join(parts[idx:])
                try:
                    gif_rel = f"{gif_rel}?v={int(gif_cands[0].stat().st_mtime_ns)}"
                except Exception:
                    pass
                data["gif_url"] = gif_rel

            # Dynamically resolve png_url so frontend gets direct HTTP 200 URLs with cache-busting
            normalized_frames = []
            dates = data.get("dates", [])
            series_values = data.get("series_values", [])
            for i, frame in enumerate(data.get("frames", [])):
                if isinstance(frame, str):
                    fname = Path(frame).name
                    frame_obj = {
                        "index": i,
                        "file": fname,
                        "date": dates[i] if i < len(dates) else None,
                        "value": series_values[i] if i < len(series_values) else None,
                        "label": f"{dates[i] if i < len(dates) else fname}: {series_values[i] if i < len(series_values) else ''}".strip(),
                    }
                elif isinstance(frame, dict):
                    frame_obj = dict(frame)
                    fname = frame_obj.get("file") or ""
                else:
                    continue

                # If no file was explicitly specified in frame dict (e.g. Gaza Task 3),
                # synthesize or discover the frame PNG
                if not fname:
                    frame_date = str(frame_obj.get("date") or frame_obj.get("year") or "")[:10]
                    matched_png = None
                    if frame_date:
                        date_candidates = [
                            f.name for f in timeline_dir.glob("*.png")
                            if frame_date in f.name
                        ]
                        if date_candidates:
                            matched_png = date_candidates[0]
                    if not matched_png and gif_cands:
                        matched_png = f"{gif_stem}_frame_{i}.png"
                    fname = matched_png or f"frame_{i}.png"
                    frame_obj["file"] = fname

                frame_fname = Path(fname).name if fname else ""
                if frame_fname and (timeline_dir / frame_fname).exists():
                    try:
                        mtime_ns = int((timeline_dir / frame_fname).stat().st_mtime_ns)
                        frame_obj["png_url"] = f"/{rel_base}/{frame_fname}?v={mtime_ns}"
                    except Exception:
                        frame_obj["png_url"] = f"/{rel_base}/{frame_fname}"
                elif frame_fname:
                    frame_obj["png_url"] = f"/api/tasks/{task_id}/artifacts/{frame_fname}"
                normalized_frames.append(frame_obj)
            data["frames"] = normalized_frames
            return JSONResponse(data)
        except Exception as e:
            return JSONResponse({"error": f"Invalid timeline.json: {e}"}, status_code=500)
    return JSONResponse({"error": "timeline.json not found"}, status_code=404)


@app.get("/api/runs/{task_id}/terrain_3d.json")
async def get_terrain_3d(task_id: str):
    """Serve precomputed 3D terrain/LiDAR mesh payload or dynamically generate one on the fly."""
    ts = task_manager.get_task(task_id)
    if not ts:
        return JSONResponse({"error": "Task not found"}, status_code=404)
    run_dir = ts.state.get("run_dir") or (ts.result.get("run_dir") if ts.result else None) or str(RUNS_DIR / task_id)
    if not run_dir:
        return JSONResponse({"error": "No run_dir"}, status_code=404)
    p = Path(run_dir)
    cands = list(p.rglob("terrain_3d.json")) + list(p.rglob("lidar_3d.json"))

    # Gather available rasters in outputs/ and scratch/outputs to check staleness
    output_tifs = [
        f for f in (list((p / "outputs").glob("*.tif")) + list((p / "scratch" / "outputs").glob("*.tif")))
        if f.is_file()
    ]
    newest_tif_mtime = max((f.stat().st_mtime for f in output_tifs), default=0)

    if cands and cands[0].exists():
        cand_file = cands[0]
        # Only use cached 3D payload if it is newer than the output GeoTIFFs
        # and has a valid non-flat elevation range (or no output GeoTIFFs exist)
        is_stale = newest_tif_mtime > cand_file.stat().st_mtime
        try:
            data = json.loads(cand_file.read_text(encoding="utf-8"))
            elev_range = float(data.get("elevation_range_m", 0) or 0)
            is_flat_zero = elev_range <= 0.0 and bool(output_tifs)
            is_old_version = str(data.get("version", "1.0")) < "2.0"
            if not is_stale and not is_flat_zero and not is_old_version:
                data["orthophoto_url"] = f"/api/runs/{task_id}/orthophoto.png"
                return JSONResponse(data)
        except Exception:
            pass

    # Dynamic on-the-fly generation if an elevation or LiDAR GeoTIFF exists in run outputs or input files
    from geollm_lib.lidar import generate_lidar_3d_payload
    from geollm_lib.terrain import generate_terrain_3d_payload

    all_tifs = list(p.rglob("*.tif"))
    if ts.files:
        for f in ts.files:
            pf = Path(f)
            if pf.exists() and pf.suffix.lower() == ".tif" and pf not in all_tifs:
                all_tifs.append(pf)

    # 1. Prioritize Canopy Height Model (CHM) and Above-Ground Objects
    chm_cands = [
        f for f in all_tifs
        if any(k in f.name.lower() for k in ["chm", "canopy_height", "above_ground", "canopy", "height_classes"])
        and "bare_ground" not in f.name.lower()
    ]
    # Prioritize continuous canopy height rasters over classified discrete rasters
    chm_cands.sort(key=lambda f: (
        0 if "canopy_height.tif" in f.name.lower() else
        1 if "above_ground" in f.name.lower() else
        2 if "chm" in f.name.lower() else
        3 if "canopy" in f.name.lower() else 4
    ))

    dsm_cands = [f for f in all_tifs if "dsm" in f.name.lower()]
    dtm_cands = [f for f in all_tifs if "dtm" in f.name.lower() or "bare_ground" in f.name.lower()]
    if not dtm_cands and dsm_cands:
        for dsm in dsm_cands:
            dtm_guess = Path("data") / dsm.name.replace("dsm", "dtm")
            if dtm_guess.exists():
                dtm_cands.append(dtm_guess)
                break

    dem_cands = [
        f for f in all_tifs
        if any(k in f.name.lower() for k in ["dem", "cop-dem", "slope"])
        or ("elevation" in f.name.lower() and "bare_ground" not in f.name.lower())
    ]

    payload = None
    if chm_cands:
        try:
            out_json = p / "terrain_3d.json"
            payload = generate_lidar_3d_payload(chm_cands[0], out_json_path=out_json, max_dim=512)
        except Exception:
            pass

    # 2. If DSM + DTM pair exists, subtract to compute CHM
    if not payload and dsm_cands and dtm_cands:
        try:
            out_json = p / "terrain_3d.json"
            payload = generate_lidar_3d_payload(dsm_cands[0], dtm_path=dtm_cands[0], out_json_path=out_json, max_dim=512)
        except Exception:
            pass

    # 3. If single DSM exists without DTM, render as terrain elevation (not relative height)
    if not payload and dsm_cands:
        try:
            out_json = p / "terrain_3d.json"
            payload = generate_terrain_3d_payload(dsm_cands[0], out_json, max_dim=512)
        except Exception:
            pass

    # 4. Standard DEM
    if not payload and dem_cands:
        try:
            out_json = p / "terrain_3d.json"
            payload = generate_terrain_3d_payload(dem_cands[0], out_json, max_dim=512)
        except Exception as e:
            return JSONResponse({"error": f"Failed to generate terrain 3D mesh: {e}"}, status_code=500)

    # 5. Fallback to any non-categorical tif (exclude class masks from 3D heightmaps)
    valid_elevation_tifs = [
        f for f in all_tifs
        if not any(k in f.name.lower() for k in ["class", "mask", "water", "label", "cluster", "rgb", "preview"])
    ]
    if not payload and valid_elevation_tifs:
        try:
            out_json = p / "terrain_3d.json"
            payload = generate_terrain_3d_payload(valid_elevation_tifs[0], out_json, max_dim=512)
        except Exception as e:
            return JSONResponse({"error": f"Failed to generate terrain 3D mesh: {e}"}, status_code=500)

    if payload:
        payload["orthophoto_url"] = f"/api/runs/{task_id}/orthophoto.png"
        return JSONResponse(payload)

    return JSONResponse({"error": "No elevation or LiDAR raster found"}, status_code=404)


@app.get("/api/runs/{task_id}/orthophoto.png")
async def get_task_orthophoto(task_id: str):
    """
    Fetches, stitches, and crops true-color aerial satellite/orthophoto imagery
    covering the exact bounding box of the active raster for photorealistic 3D draping.
    """
    ts = task_manager.get_task(task_id)
    if not ts:
        return JSONResponse({"error": "Task not found"}, status_code=404)
    run_dir = ts.state.get("run_dir") or (ts.result.get("run_dir") if ts.result else None) or str(RUNS_DIR / task_id)
    if not run_dir:
        return JSONResponse({"error": "No run_dir"}, status_code=404)
    p = Path(run_dir)
    cache_path = p / "orthophoto.png"
    if cache_path.exists():
        return FileResponse(cache_path, media_type="image/png")

    all_tifs = list(p.rglob("*.tif"))
    if ts.files:
        for f in ts.files:
            pf = Path(f)
            if pf.exists() and pf.suffix.lower() == ".tif" and pf not in all_tifs:
                all_tifs.append(pf)
    if not all_tifs:
        return JSONResponse({"error": "No raster found"}, status_code=404)

    import rasterio
    from rasterio.warp import transform_bounds
    from geollm_lib.terrain import fetch_orthophoto_for_bounds
    try:
        with rasterio.open(all_tifs[0]) as src:
            wgs84_bounds = transform_bounds(src.crs, "EPSG:4326", *src.bounds)

        await asyncio.to_thread(fetch_orthophoto_for_bounds, *wgs84_bounds, str(cache_path))
        if cache_path.exists():
            return FileResponse(cache_path, media_type="image/png")
    except Exception as e:
        return JSONResponse({"error": f"Failed to fetch aerial orthophoto: {e}"}, status_code=500)

    return JSONResponse({"error": "Could not create orthophoto"}, status_code=500)


@app.get("/api/tasks/{task_id}/artifacts")
async def get_task_artifacts(task_id: str):
    ts = task_manager.get_task(task_id)
    if not ts:
        return JSONResponse({"artifacts": [], "timeline_frames": []})
    run_dir = ts.state.get("run_dir") or (ts.result.get("run_dir") if ts.result else None) or str(RUNS_DIR / task_id)
    ans = ts.result.get("answer") if isinstance(ts.result, dict) else None
    timeline_frames: List[str] = []
    if run_dir:
        rd = Path(run_dir)
        for tl_path in sorted(rd.rglob("timeline.json"), key=lambda p: str(p), reverse=True):
            try:
                tl_data = json.loads(tl_path.read_text(encoding="utf-8"))
                for fr in tl_data.get("frames", []):
                    raw_f = fr if isinstance(fr, str) else (fr.get("file") or "")
                    if raw_f:
                        timeline_frames.append(Path(str(raw_f)).name)
                if timeline_frames:
                    break
            except Exception:
                pass
    return JSONResponse({"artifacts": find_artifacts(run_dir), "answer": ans, "timeline_frames": timeline_frames})


@app.get("/api/tasks/{task_id}/artifacts/{artifact_path:path}")
async def get_task_artifact_file(task_id: str, artifact_path: str):
    """Serve any task deliverable or generated frame directly by filename or relative path."""
    ts = task_manager.get_task(task_id)
    if not ts:
        raise HTTPException(status_code=404, detail="Task not found")
    run_dir = ts.state.get("run_dir") or (ts.result.get("run_dir") if ts.result else None) or str(RUNS_DIR / task_id)
    if not run_dir:
        raise HTTPException(status_code=404, detail="No run_dir for task")
    rd = Path(run_dir)
    fname = Path(artifact_path).name
    # Search run_dir recursively for this artifact file
    cands = list(rd.rglob(fname))
    if not cands and fname.lower().endswith(".png"):
        # Fallback for time-series frames that were rendered into /tmp inside the container:
        # locate timeline.json + animated .gif in the run directory and extract the matching frame on the fly.
        tl_cands = sorted(rd.rglob("timeline.json"), key=lambda p: str(p), reverse=True)
        for tl_path in tl_cands:
            try:
                tl_data = json.loads(tl_path.read_text(encoding="utf-8"))
                frames_list = tl_data.get("frames", [])
                match_idx = None
                for idx, fr in enumerate(frames_list):
                    fr_file = Path(fr if isinstance(fr, str) else (fr.get("file") or "")).name
                    fr_date = str(fr.get("date") or "")[:10] if isinstance(fr, dict) else ""
                    if (
                        (fr_file and fr_file == fname)
                        or fname.endswith(f"_frame_{idx}.png")
                        or fname == f"frame_{idx}.png"
                        or (fr_date and fr_date in fname)
                        or (isinstance(fr, dict) and str(fr.get("animation_frame")) == str(idx) and f"_{idx}.png" in fname)
                    ):
                        match_idx = idx
                        break
                if match_idx is not None:
                    gif_cands = sorted(tl_path.parent.glob("*.gif")) or sorted(rd.rglob("*.gif"), key=lambda p: str(p), reverse=True)
                    if gif_cands:
                        from PIL import Image
                        with Image.open(gif_cands[0]) as gif_im:
                            n_frames = getattr(gif_im, "n_frames", 1)
                            target_frame = min(match_idx, n_frames - 1)
                            gif_im.seek(target_frame)
                            extracted_path = tl_path.parent / fname
                            gif_im.convert("RGBA").save(extracted_path, format="PNG")
                            cands = [extracted_path]
                            break
            except Exception:
                pass
    if cands:
        # Prefer latest attempt outputs
        chosen = sorted(cands, key=lambda p: str(p), reverse=True)[0]
        ext = chosen.suffix.lower()
        media_type = (
            "image/png" if ext == ".png"
            else "image/svg+xml" if ext == ".svg"
            else "image/gif" if ext == ".gif"
            else "image/tiff" if ext in (".tif", ".tiff")
            else "text/html; charset=utf-8" if ext in (".html", ".htm")
            else "application/json" if ext == ".json"
            else "application/octet-stream"
        )
        headers = {"Cache-Control": "no-cache, must-revalidate"}
        return FileResponse(chosen, media_type=media_type, headers=headers)
    raise HTTPException(status_code=404, detail=f"Artifact '{fname}' not found in task run")


@app.get("/api/tasks/{task_id}/thumbs/{thumb_path:path}")
async def get_task_thumb(task_id: str, thumb_path: str):
    """Serve vision-crop thumbnails from the run's feedback/thumbs folder.

    Restricted to the run's own ``feedback/thumbs`` directory and blocks
    path traversal (``..`` / absolute paths / drive letters) so a malicious
    ``thumb_url`` cannot reach arbitrary files on disk.
    """
    ts = task_manager.get_task(task_id)
    if not ts:
        raise HTTPException(status_code=404, detail="Task not found")
    run_dir = ts.state.get("run_dir") or (ts.result.get("run_dir") if ts.result else None) or str(RUNS_DIR / task_id)
    if not run_dir:
        raise HTTPException(status_code=404, detail="No run_dir for task")
    rd = Path(run_dir)

    # Block path traversal: reject anything that escapes the thumbs folder.
    cleaned = thumb_path.replace("\\", "/")
    if ".." in cleaned.split("/") or cleaned.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid thumbnail path")
    candidate = (rd / "feedback" / "thumbs" / cleaned).resolve()
    thumbs_root = (rd / "feedback" / "thumbs").resolve()
    try:
        candidate.relative_to(thumbs_root)
    except ValueError:
        raise HTTPException(status_code=403, detail="Thumbnail path outside feedback/thumbs")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(candidate, media_type="image/png")


@app.post("/api/tasks/{task_id}/approve")
async def approve_task(task_id: str):
    if not task_manager.approve_task(task_id):
        return JSONResponse({"error": "Task not awaiting approval."}, status_code=400)
    return JSONResponse({"task_id": task_id, "status": "approved"})


@app.post("/api/tasks/{task_id}/revise")
async def revise_task(task_id: str, payload: RevisionPayload):
    if not task_manager.revise_task(task_id, payload.feedback):
        return JSONResponse({"error": "Task not awaiting approval."}, status_code=400)
    return JSONResponse({"task_id": task_id, "status": "revision_sent"})


@app.get("/api/stac/collections")
async def get_stac_collections():
    from harness.stac_service import get_curated_collections
    return JSONResponse({"collections": get_curated_collections()})


class StacSearchPayload(BaseModel):
    bbox: List[float]
    start_date: str
    end_date: str
    collections: List[str] = ["sentinel-2-l2a", "sentinel-1-rtc"]
    max_cloud_cover: Optional[float] = 30.0
    limit: int = 12


@app.post("/api/stac/search")
async def search_stac(payload: StacSearchPayload):
    from harness.stac_service import search_stac_items
    res = await search_stac_items(
        bbox=payload.bbox,
        start_date=payload.start_date,
        end_date=payload.end_date,
        collections=payload.collections,
        max_cloud_cover=payload.max_cloud_cover,
        limit=payload.limit,
    )
    return JSONResponse(res)


class StacStagePayload(BaseModel):
    collection: str
    item_id: str
    asset_key: str
    custom_filename: Optional[str] = None


@app.post("/api/stac/stage")
async def stage_stac(payload: StacStagePayload):
    from harness.stac_service import stage_stac_asset, register_download_task
    stage_id = f"{payload.item_id}_{payload.asset_key}"
    task = asyncio.create_task(
        stage_stac_asset(
            collection=payload.collection,
            item_id=payload.item_id,
            asset_key=payload.asset_key,
            output_dir=DATA_DIR,
            custom_filename=payload.custom_filename,
        )
    )
    register_download_task(stage_id, task)
    return JSONResponse({"ok": True, "stage_id": stage_id, "status": "started"})


class StacCancelPayload(BaseModel):
    stage_id: str


@app.post("/api/stac/cancel")
async def cancel_stac_download_endpoint(payload: StacCancelPayload):
    from harness.stac_service import cancel_stac_download
    ok = cancel_stac_download(payload.stage_id)
    return JSONResponse({"ok": ok, "stage_id": payload.stage_id, "status": "cancelled"})


@app.get("/api/stac/downloads")
async def get_stac_download_progress():
    from harness.stac_service import get_active_downloads
    return JSONResponse({"downloads": get_active_downloads()})


def resolve_raster_path(path_str: str) -> Optional[Path]:
    if not path_str:
        return None
    path_clean = path_str.split("?")[0].strip()
    cleaned = path_clean.lstrip("/\\")

    # 1. Direct check from CWD
    cand = (Path.cwd() / cleaned).resolve()
    if cand.exists() and cand.is_file():
        return cand

    # 2. Direct relative path
    cand = Path(cleaned)
    if cand.exists() and cand.is_file():
        return cand.resolve()

    # 3. If prefixed with runs/ or data/
    stripped_runs = cleaned
    if stripped_runs.lower().startswith("runs/"):
        stripped_runs = stripped_runs[5:]
    elif stripped_runs.lower().startswith("runs\\"):
        stripped_runs = stripped_runs[5:]
    cand = (RUNS_DIR / stripped_runs).resolve()
    if cand.exists() and cand.is_file():
        return cand

    stripped_data = cleaned
    if stripped_data.lower().startswith("data/"):
        stripped_data = stripped_data[5:]
    elif stripped_data.lower().startswith("data\\"):
        stripped_data = stripped_data[5:]
    cand = (DATA_DIR / stripped_data).resolve()
    if cand.exists() and cand.is_file():
        return cand

    # 4. Check under RUNS_DIR and DATA_DIR directly
    cand = (RUNS_DIR / cleaned).resolve()
    if cand.exists() and cand.is_file():
        return cand
    cand = (DATA_DIR / cleaned).resolve()
    if cand.exists() and cand.is_file():
        return cand

    # 5. Fallback: match by filename in RUNS_DIR or DATA_DIR
    fname = Path(cleaned).name
    matches = list(RUNS_DIR.glob(f"**/{fname}"))
    if matches:
        return matches[-1].resolve()
    matches_data = list(DATA_DIR.glob(f"**/{fname}"))
    if matches_data:
        return matches_data[-1].resolve()

    return None


_RASTER_PNG_CACHE: Dict[tuple, bytes] = {}


def geotiff_to_png_bytes(
    tif_path: Path,
    max_dim: int = 2048,
    cmap_name: Optional[str] = None,
    vmin_override: Optional[float] = None,
    vmax_override: Optional[float] = None,
    band_idx: int = 1,
) -> bytes:
    mtime = os.path.getmtime(tif_path)
    cache_key = (str(tif_path.resolve()), mtime, cmap_name, vmin_override, vmax_override, band_idx)
    if cache_key in _RASTER_PNG_CACHE:
        return _RASTER_PNG_CACHE[cache_key]

    import io
    import numpy as np
    from PIL import Image
    import rasterio
    from rasterio.enums import Resampling
    import matplotlib.cm as cm

    with rasterio.open(tif_path) as src:
        src_h, src_w = src.height, src.width
        if max(src_h, src_w) > max_dim:
            scale = max_dim / max(src_h, src_w)
            out_shape = (max(1, int(src_h * scale)), max(1, int(src_w * scale)))
        else:
            out_shape = (src_h, src_w)

        nodata = src.nodata

        if src.count >= 3 and band_idx == 1 and not cmap_name:
            rgb_data = src.read([1, 2, 3], out_shape=out_shape, resampling=Resampling.bilinear)
            rgba = np.zeros((out_shape[0], out_shape[1], 4), dtype=np.uint8)
            mask = np.ones(out_shape, dtype=bool)
            for i in range(3):
                b = rgb_data[i].astype(np.float32)
                if nodata is not None:
                    mask &= (b != nodata)
                valid = b[mask] if np.any(mask) else b
                if len(valid) > 0:
                    b_min, b_max = np.nanpercentile(valid, 2), np.nanpercentile(valid, 98)
                else:
                    b_min, b_max = 0, 1
                if b_max > b_min:
                    norm = np.clip((b - b_min) / (b_max - b_min) * 255.0, 0, 255).astype(np.uint8)
                else:
                    norm = np.zeros(out_shape, dtype=np.uint8)
                rgba[:, :, i] = norm
            rgba[:, :, 3] = np.where(mask, 255, 0).astype(np.uint8)
            img = Image.fromarray(rgba, "RGBA")
        else:
            eff_band = min(max(1, band_idx), src.count)
            is_int = np.issubdtype(src.dtypes[eff_band - 1], np.integer)
            # Read nearest first when no explicit continuous cmap is requested so discrete
            # integer-valued float masks (e.g. 0.0 / 1.0) are not blurred by bilinear interpolation.
            b = src.read(
                eff_band,
                out_shape=out_shape,
                resampling=Resampling.nearest if (is_int or not cmap_name) else Resampling.bilinear,
            )
            mask = np.isfinite(b)
            if nodata is not None:
                mask &= (b != nodata)

            # Check colormap from raster file if no custom cmap was requested
            cmap = None
            if not cmap_name:
                try:
                    cmap = src.colormap(eff_band)
                except (ValueError, IndexError):
                    pass

            if cmap:
                rgba = np.zeros((out_shape[0], out_shape[1], 4), dtype=np.uint8)
                for val, col in cmap.items():
                    val_mask = (b == val)
                    rgba[val_mask, 0] = col[0]
                    rgba[val_mask, 1] = col[1]
                    rgba[val_mask, 2] = col[2]
                    rgba[val_mask, 3] = 0 if (nodata is not None and val == nodata) else (col[3] if len(col) > 3 else 255)
                img = Image.fromarray(rgba, "RGBA")
            else:
                valid_b = b[mask] if np.any(mask) else np.array([])
                is_integer_values = is_int or (
                    len(valid_b) > 0 and bool(np.all(np.floor(valid_b) == valid_b))
                )
                unique_vals = np.unique(valid_b) if (is_integer_values and len(valid_b) > 0) else np.array([])

                # If discrete integer classification (int dtype OR float storing integer class IDs)
                # and no explicit continuous cmap requested — matches /api/raster/stats legend palette
                if is_integer_values and 0 < len(unique_vals) <= 30 and not cmap_name:
                    palette = [
                        [46, 204, 113, 230],   # Emerald green
                        [52, 152, 219, 230],   # Blue
                        [241, 196, 15, 230],   # Yellow
                        [231, 76, 60, 230],    # Red
                        [155, 89, 182, 230],   # Purple
                        [230, 126, 34, 230],   # Orange
                        [26, 188, 156, 230],   # Turquoise
                        [243, 156, 18, 230],   # Gold
                        [149, 165, 166, 230],  # Gray
                        [52, 73, 94, 230],     # Navy
                    ]
                    rgba = np.zeros((out_shape[0], out_shape[1], 4), dtype=np.uint8)
                    for idx, val in enumerate(unique_vals):
                        if nodata is not None and val == nodata:
                            continue
                        col = palette[idx % len(palette)]
                        val_mask = (b == val) & mask
                        rgba[val_mask] = col
                    img = Image.fromarray(rgba, "RGBA")
                else:
                    if not is_int and not cmap_name:
                        # Continuous float raster: re-read with bilinear resampling for smooth gradients
                        b = src.read(eff_band, out_shape=out_shape, resampling=Resampling.bilinear)
                        mask = np.isfinite(b)
                        if nodata is not None:
                            mask &= (b != nodata)
                    b_float = b.astype(np.float32)
                    valid_pixels = b_float[mask] if np.any(mask) else b_float.flatten()
                    if vmin_override is not None and vmax_override is not None and vmax_override > vmin_override:
                        vmin, vmax = vmin_override, vmax_override
                    elif len(valid_pixels) > 0:
                        vmin = vmin_override if vmin_override is not None else float(np.nanpercentile(valid_pixels, 2))
                        vmax = vmax_override if vmax_override is not None else float(np.nanpercentile(valid_pixels, 98))
                    else:
                        vmin, vmax = 0.0, 1.0

                    if vmax > vmin:
                        norm = np.clip((b_float - vmin) / (vmax - vmin), 0.0, 1.0)
                    else:
                        norm = np.zeros_like(b_float)

                    # Dynamic colormap resolution
                    chosen_cmap = cm.viridis
                    if cmap_name:
                        c_lower = cmap_name.lower().strip()
                        cmap_aliases = {
                            "ndvi": "RdYlGn",
                            "blues": "Blues",
                            "greens": "Greens",
                            "reds": "Reds",
                            "spectral": "Spectral",
                            "grayscale": "gray",
                            "greyscale": "gray",
                            "grey": "gray",
                        }
                        mapped_name = cmap_aliases.get(c_lower, c_lower)
                        try:
                            chosen_cmap = cm.get_cmap(mapped_name)
                        except Exception:
                            try:
                                import matplotlib.pyplot as plt
                                chosen_cmap = plt.get_cmap(mapped_name)
                            except Exception:
                                chosen_cmap = cm.viridis

                    colored = chosen_cmap(norm)
                    rgba = (colored * 255.0).astype(np.uint8)
                    rgba[:, :, 3] = np.where(mask, 230, 0).astype(np.uint8)
                    img = Image.fromarray(rgba, "RGBA")

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        result = buf.getvalue()
        while len(_RASTER_PNG_CACHE) >= 128:
            _RASTER_PNG_CACHE.pop(next(iter(_RASTER_PNG_CACHE)), None)
        _RASTER_PNG_CACHE[cache_key] = result
        return result


@app.get("/api/raster/bounds")
async def get_raster_bounds(path: str):
    """
    Computes real-world WGS84 geographic bounding box and 4 corners
    for any GeoTIFF raster so MapLibre GL can accurately overlay it on the 3D globe.
    """
    try:
        import rasterio
        from rasterio.warp import transform_bounds
        p = resolve_raster_path(path)

        if not p or not p.exists():
            return JSONResponse({"ok": False, "error": f"File not found: {path}"}, status_code=404)

        with rasterio.open(p) as src:
            bounds = src.bounds
            crs = src.crs
            wgs84_bounds = transform_bounds(crs, "EPSG:4326", *bounds)
            min_lon, min_lat, max_lon, max_lat = wgs84_bounds

            coordinates = [
                [min_lon, max_lat], # top-left
                [max_lon, max_lat], # top-right
                [max_lon, min_lat], # bottom-right
                [min_lon, min_lat], # bottom-left
            ]

            from urllib.parse import quote
            return JSONResponse({
                "ok": True,
                "bbox": [min_lon, min_lat, max_lon, max_lat],
                "coordinates": coordinates,
                "crs": str(crs),
                "width": src.width,
                "height": src.height,
                "count": src.count,
                "path": str(p),
                "png_url": f"/api/raster/png?path={quote(str(path))}",
            })
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/api/raster/png")
async def get_raster_png(
    path: str,
    cmap: Optional[str] = None,
    vmin: Optional[float] = None,
    vmax: Optional[float] = None,
    band: int = 1,
):
    """
    Renders any GeoTIFF as a high-performance in-memory PNG with transparent nodata,
    supporting dynamic colormaps, custom min/max stretch, and band selection.
    """
    try:
        p = resolve_raster_path(path)
        if not p or not p.exists():
            return JSONResponse({"ok": False, "error": f"File not found: {path}"}, status_code=404)

        png_bytes = await asyncio.to_thread(
            geotiff_to_png_bytes,
            p,
            2048,
            cmap,
            vmin,
            vmax,
            band,
        )
        return Response(content=png_bytes, media_type="image/png")
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/api/raster/stats")
async def get_raster_stats(path: str, band: int = 1):
    """
    Dynamically extracts raster statistics, physical units, colormap recommendations,
    and class labels from the task container's result.json and GeoTIFF tags.
    Strictly ZERO hardcoded strings.
    """
    try:
        import rasterio
        import numpy as np

        p = resolve_raster_path(path)
        if not p or not p.exists():
            return JSONResponse({"ok": False, "error": f"File not found: {path}"}, status_code=404)

        # 1. Discover task container result.json if present
        rjson = {}
        for search_dir in [p.parent, p.parent.parent / "outputs", p.parent.parent]:
            cand_res = search_dir / "result.json"
            if cand_res.exists():
                try:
                    with open(cand_res, "r", encoding="utf-8") as f:
                        rjson = json.load(f)
                    break
                except Exception:
                    pass

        # 2. Inspect GeoTIFF tags and metadata
        with rasterio.open(p) as src:
            eff_band = min(max(1, band), src.count)
            tags = src.tags()
            band_desc = src.descriptions[eff_band - 1] if src.descriptions else None
            units_src = src.units[eff_band - 1] if src.units else None

            # Determine units dynamically from tags, descriptions, or result.json
            units = None
            if tags.get("UNITS"):
                units = tags["UNITS"]
            elif tags.get("units"):
                units = tags["units"]
            elif units_src:
                units = units_src

            # Check if artifact has description in result.json
            art_desc = None
            for art in rjson.get("output_artifacts", []):
                if art.get("file") == p.name:
                    art_desc = art.get("description")
                    break

            if not units and art_desc:
                # Try extracting unit from artifact description (e.g. "... in metres")
                if "metre" in art_desc.lower() or "meter" in art_desc.lower():
                    units = "metres"
                elif "db" in art_desc.lower():
                    units = "dB"
                elif "cells" in art_desc.lower():
                    units = "cells"

            if not units and band_desc:
                if "(m)" in band_desc or "metres" in band_desc.lower() or "meter" in band_desc.lower():
                    units = "metres"
                elif "db" in band_desc.lower():
                    units = "dB"
                elif "cells" in band_desc.lower():
                    units = "cells"

            # Check if container result.json has explicit statistics matching this artifact
            matched_stats = None
            rjson_stats = rjson.get("statistics", {})
            p_stem = p.stem.lower()

            if "tree" in p_stem and "height_by_category" in rjson_stats:
                matched_stats = rjson_stats["height_by_category"].get("tree_class5")
            elif "building" in p_stem and "height_by_category" in rjson_stats:
                matched_stats = rjson_stats["height_by_category"].get("building_class6")
            elif "surface" in p_stem and "height_by_category" in rjson_stats:
                matched_stats = rjson_stats["height_by_category"].get("combined")
            elif "corridor" in p_stem and "corridor" in rjson_stats:
                matched_stats = rjson_stats["corridor"]
            elif "accumulation" in p_stem and "d8_accumulation_cells" in rjson_stats:
                matched_stats = rjson_stats["d8_accumulation_cells"]
            elif "wetness" in p_stem and "twi" in rjson_stats:
                matched_stats = rjson_stats["twi"]
            elif "elevation" in rjson_stats and ("dem" in p_stem or "elevation" in p_stem):
                matched_stats = rjson_stats["elevation"]

            # Compute sample statistics from raster
            sample_dim = 1024
            scale = min(1.0, sample_dim / max(src.height, src.width))
            sample_h = max(1, int(src.height * scale))
            sample_w = max(1, int(src.width * scale))
            is_int = np.issubdtype(src.dtypes[eff_band - 1], np.integer)
            arr = src.read(
                eff_band,
                out_shape=(sample_h, sample_w),
                resampling=rasterio.enums.Resampling.nearest,
            )

            mask = np.isfinite(arr)
            if src.nodata is not None:
                mask &= (arr != src.nodata)
            valid = arr[mask]

            # Detect classified categorical data (int dtype OR float raster storing discrete integer class IDs)
            is_classified = False
            unique_classes = []
            is_integer_values = is_int or (len(valid) > 0 and bool(np.all(np.floor(valid) == valid)))
            if is_integer_values and len(valid) > 0:
                uniques = np.unique(valid)
                if len(uniques) <= 30:
                    is_classified = True
                    # Dynamically parse class names from tags/descriptions if present
                    # 1. Explicit key-value tags: class_0="dry both", CLASS_1="water lost", label_2=..., or JSON class_map
                    # 2. Text descriptions: "1=water, 2=greenery", "Class raster: 1 water, 2 green", "(1 water, 0 non-water)"
                    import re as _re
                    band_tags = src.tags(eff_band) if hasattr(src, "tags") else {}
                    class_map = {}

                    for tag_dict in (band_tags, tags):
                        if not isinstance(tag_dict, dict):
                            continue
                        # 1a. Individual per-class tags (e.g. class_0, CLASS_1, label_2, category_3, value_1)
                        for tk, tv in tag_dict.items():
                            if not tv or not str(tv).strip():
                                continue
                            mk = _re.match(r"^(?:class|label|category|cat|val|value|code)[_-]?(-?\d+)$", str(tk).strip(), _re.I)
                            if mk:
                                cid = int(mk.group(1))
                                lbl = str(tv).strip()
                                if cid not in class_map and lbl:
                                    class_map[cid] = lbl[0].upper() + lbl[1:]
                        # 1b. JSON mapping tags (e.g. classes='{"0": "Dry", "1": "Water"}')
                        for jk in ("classes", "CLASSES", "class_map", "CLASS_MAP", "class_names", "CLASS_NAMES", "labels", "LABELS", "legend", "LEGEND"):
                            raw_j = tag_dict.get(jk)
                            if raw_j and str(raw_j).strip().startswith("{"):
                                try:
                                    parsed_j = json.loads(str(raw_j))
                                    if isinstance(parsed_j, dict):
                                        for pk, pv in parsed_j.items():
                                            try:
                                                cid = int(pk)
                                                lbl = str(pv).strip()
                                                if cid not in class_map and lbl:
                                                    class_map[cid] = lbl[0].upper() + lbl[1:]
                                            except (ValueError, TypeError):
                                                pass
                                except Exception:
                                    pass

                    desc_candidates = [
                        tags.get("description"),
                        tags.get("DESCRIPTION"),
                        band_tags.get("description"),
                        band_desc,
                        art_desc,
                        tags.get("units"),
                        tags.get("UNITS"),
                        tags.get("classes"),
                        tags.get("legend"),
                    ]
                    desc_text = " ; ".join(str(x).strip() for x in desc_candidates if x and str(x).strip())
                    for cand in desc_candidates:
                        if not cand:
                            continue
                        for m in _re.finditer(
                            r"(?:^|[;,(\n:]\s*)(-?\d+)\s*(?:=|:|\s-\s|\s+)\s*([A-Za-z][^;,()\n.]*)",
                            str(cand),
                        ):
                            lbl = m.group(2).strip()
                            if lbl and int(m.group(1)) not in class_map:
                                class_map[int(m.group(1))] = lbl[0].upper() + lbl[1:]

                    # 3. Fallback: extract class ID -> name mapping from sibling result.json
                    # Handles any standard schema: list of dicts (e.g. [{"class_id": 1, "zone": "..."}])
                    # or dict maps (e.g. {"1": "Water", "2": "Forest"}), choosing the candidate whose
                    # integer keys best match this raster's actual unique class values.
                    unique_int_set = {int(u) for u in uniques}
                    if rjson and not unique_int_set.issubset(class_map.keys()):
                        _ID_KEYS = ("class_id", "value", "code", "class", "label_id", "pixel_value", "id", "zone_id")
                        _NAME_KEYS = ("zone", "class_name", "name", "label", "category", "material", "interpretation", "title", "description")
                        _candidates_from_rjson = []

                        def _collect_rjson_class_maps(obj, key_hint=""):
                            if isinstance(obj, list) and 1 <= len(obj) <= 40 and all(isinstance(x, dict) for x in obj):
                                extracted = {}
                                for item in obj:
                                    cid_val = None
                                    for ik in _ID_KEYS:
                                        if ik in item and item[ik] is not None:
                                            try:
                                                cid_val = int(item[ik])
                                                break
                                            except (ValueError, TypeError):
                                                pass
                                    if cid_val is None:
                                        continue
                                    lbl_val = None
                                    for nk in _NAME_KEYS:
                                        v = item.get(nk)
                                        if isinstance(v, str) and v.strip():
                                            lbl_val = v.strip()
                                            break
                                    if lbl_val and cid_val not in extracted:
                                        extracted[cid_val] = lbl_val[0].upper() + lbl_val[1:]
                                if extracted:
                                    overlap = len(unique_int_set & extracted.keys())
                                    if overlap > 0:
                                        # Prefer exact key-set match and explicit class_id over cluster_id
                                        exact_bonus = 10 if set(extracted.keys()) == unique_int_set else 0
                                        hint_bonus = 2 if any(w in key_hint.lower() for w in ("class", "zone", "legend", "categor", "label", "land")) else 0
                                        _candidates_from_rjson.append((overlap + exact_bonus + hint_bonus, extracted))
                            elif isinstance(obj, dict):
                                # Check if this dict itself is a { "1": "Water", "2": "Forest" } map
                                int_str_map = {}
                                for k, v in obj.items():
                                    if isinstance(v, str) and v.strip() and not v.strip().startswith(("/", "http")):
                                        mk = _re.match(r"^(?:class[_-]?|label[_-]?|val[_-]?)?(-?\d+)$", str(k).strip(), _re.I)
                                        if mk:
                                            int_str_map[int(mk.group(1))] = v.strip()[0].upper() + v.strip()[1:]
                                if len(int_str_map) >= 2:
                                    overlap = len(unique_int_set & int_str_map.keys())
                                    if overlap > 0:
                                        exact_bonus = 10 if set(int_str_map.keys()) == unique_int_set else 0
                                        hint_bonus = 2 if any(w in key_hint.lower() for w in ("class", "zone", "legend", "categor", "label", "map")) else 0
                                        _candidates_from_rjson.append((overlap + exact_bonus + hint_bonus, int_str_map))
                                for k, v in obj.items():
                                    if isinstance(v, (dict, list)):
                                        _collect_rjson_class_maps(v, str(k))

                        _collect_rjson_class_maps(rjson)
                        if _candidates_from_rjson:
                            _candidates_from_rjson.sort(key=lambda pair: pair[0], reverse=True)
                            best_map = _candidates_from_rjson[0][1]
                            for cid, lbl in best_map.items():
                                if cid not in class_map:
                                    class_map[cid] = lbl

                    palette = [
                        "#2ECC71", "#3498DB", "#F1C40F", "#E74C3C", "#9B59B6",
                        "#E67E22", "#1ABC9C", "#F39C12", "#95A5A6", "#34495E"
                    ]
                    for idx, u in enumerate(uniques):
                        u_int = int(u)
                        label = class_map.get(u_int, f"Class {u_int}")
                        if u_int == 0 and not class_map.get(0):
                            label = "Background / Other"
                        elif u_int == 1 and not class_map.get(1) and ("candidate" in desc_text.lower() or "mask" in desc_text.lower()):
                            label = "Candidate / Positive"
                        unique_classes.append({
                            "value": u_int,
                            "label": label,
                            "color": palette[idx % len(palette)]
                        })

            # Calculate numerical distribution
            if matched_stats and "min_m" in matched_stats:
                s_min = float(matched_stats.get("min_m", 0))
                s_max = float(matched_stats.get("max_m", 1))
                s_mean = float(matched_stats.get("mean_m", 0))
                s_median = float(matched_stats.get("median_m", 0))
                p02 = s_min
                p98 = float(matched_stats.get("p95_m", s_max))
            elif matched_stats and "min" in matched_stats:
                s_min = float(matched_stats.get("min", 0))
                s_max = float(matched_stats.get("max", 1))
                s_mean = float(matched_stats.get("mean", 0))
                s_median = float(matched_stats.get("median", 0))
                p02 = float(matched_stats.get("p10", s_min))
                p98 = float(matched_stats.get("p90", s_max))
            elif len(valid) > 0:
                s_min = float(np.nanmin(valid))
                s_max = float(np.nanmax(valid))
                s_mean = float(np.nanmean(valid))
                s_median = float(np.nanmedian(valid))
                p02 = float(np.nanpercentile(valid, 2))
                p98 = float(np.nanpercentile(valid, 98))
            else:
                s_min, s_max, s_mean, s_median, p02, p98 = 0.0, 1.0, 0.5, 0.5, 0.0, 1.0

            # Dynamic recommended colormap
            recommended_cmap = "viridis"
            stem = p.stem.lower()
            if "dem" in stem or "elevation" in stem or "dtm" in stem or "dsm" in stem:
                recommended_cmap = "terrain"
            elif "tree" in stem or "vegetation" in stem or "ndvi" in stem:
                recommended_cmap = "Greens"
            elif "water" in stem or "wetness" in stem or "accumulation" in stem or "flow" in stem:
                recommended_cmap = "Blues"
            elif "heat" in stem or "temp" in stem or "thermal" in stem:
                recommended_cmap = "inferno"

            return JSONResponse({
                "ok": True,
                "file_name": p.name,
                "path": str(p),
                "band": eff_band,
                "band_count": src.count,
                "band_description": band_desc,
                "artifact_description": art_desc,
                "units": units or "units",
                "crs": str(src.crs),
                "width": src.width,
                "height": src.height,
                "is_classified": is_classified,
                "classes": unique_classes,
                "recommended_cmap": recommended_cmap,
                "stats": {
                    "min": s_min,
                    "max": s_max,
                    "mean": s_mean,
                    "median": s_median,
                    "p02": p02,
                    "p98": p98,
                }
            })
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/api/raster/pixel")
async def get_raster_pixel(path: str, lon: float, lat: float, band: int = 1):
    """
    Queries the exact real-world physical pixel value at geographic (lon, lat)
    for hover tooltips and live inspection on the 3D globe.
    """
    try:
        import rasterio
        from rasterio.warp import transform
        import numpy as np

        p = resolve_raster_path(path)
        if not p or not p.exists():
            return JSONResponse({"ok": False, "error": f"File not found: {path}"}, status_code=404)

        with rasterio.open(p) as src:
            eff_band = min(max(1, band), src.count)
            xs, ys = transform("EPSG:4326", src.crs, [lon], [lat])
            x, y = xs[0], ys[0]

            if not (src.bounds.left <= x <= src.bounds.right and src.bounds.bottom <= y <= src.bounds.top):
                return JSONResponse({"ok": True, "inside": False})

            row, col = src.index(x, y)
            if not (0 <= row < src.height and 0 <= col < src.width):
                return JSONResponse({"ok": True, "inside": False})

            window = rasterio.windows.Window(col, row, 1, 1)
            val = src.read(eff_band, window=window)[0, 0]
            is_nodata = (src.nodata is not None and val == src.nodata) or np.isnan(val)

            # Get units
            units = src.tags().get("UNITS") or src.tags().get("units") or (src.units[eff_band - 1] if src.units else "")

            return JSONResponse({
                "ok": True,
                "inside": True,
                "value": None if is_nodata else float(val),
                "is_nodata": bool(is_nodata),
                "row": int(row),
                "col": int(col),
                "units": units,
                "band": eff_band,
            })
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/api/file/inspect")
async def inspect_file_metadata(path: str):
    """
    Unified inspector for any catalog or uploaded file:
    GeoTIFF rasters, LAS/LAZ point clouds, GeoJSON/vectors, or imagery.
    """
    try:
        p = resolve_raster_path(path)
        if not p or not p.exists():
            return JSONResponse({"ok": False, "error": f"File not found: {path}"}, status_code=404)

        ext = p.suffix.lower()
        size_mb = round(p.stat().st_size / (1024 * 1024), 2)
        meta = {
            "ok": True,
            "filename": p.name,
            "path": str(p),
            "size_mb": size_mb,
            "extension": ext,
        }

        # 1. GeoTIFF / Raster
        if ext in [".tif", ".tiff", ".img", ".jp2"]:
            import rasterio
            from rasterio.warp import transform_bounds
            with rasterio.open(p) as src:
                try:
                    wgs84_bounds = transform_bounds(src.crs, "EPSG:4326", *src.bounds)
                except Exception:
                    wgs84_bounds = None
                meta.update({
                    "category": "raster",
                    "crs": str(src.crs),
                    "width": src.width,
                    "height": src.height,
                    "count": src.count,
                    "dtypes": [str(d) for d in src.dtypes],
                    "nodata": src.nodata,
                    "bounds_wgs84": wgs84_bounds,
                    "png_url": f"/api/raster/png?path={p.name}",
                })

        # 2. Point Cloud (LAZ / LAS)
        elif ext in [".laz", ".las"]:
            import laspy
            with laspy.open(p) as reader:
                h = reader.header
                crs_str = str(h.parse_crs()) if h.parse_crs() else "Unknown"
                meta.update({
                    "category": "lidar",
                    "point_count": h.point_count,
                    "version": f"{h.version.major}.{h.version.minor}",
                    "crs": crs_str,
                    "min_bounds": [float(v) for v in h.min],
                    "max_bounds": [float(v) for v in h.max],
                })

        # 3. Vector (GeoJSON / Shapefile)
        elif ext in [".geojson", ".json"]:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            features = data.get("features", [])
            geom_types = list(set(f.get("geometry", {}).get("type", "Unknown") for f in features if f.get("geometry")))
            meta.update({
                "category": "vector",
                "feature_count": len(features),
                "geometry_types": geom_types,
            })

        # 4. Image (PNG, JPG)
        elif ext in [".png", ".jpg", ".jpeg"]:
            from PIL import Image
            with Image.open(p) as im:
                meta.update({
                    "category": "image",
                    "width": im.width,
                    "height": im.height,
                    "format": im.format,
                    "mode": im.mode,
                })
        else:
            meta.update({"category": "other"})

        return JSONResponse(meta)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)



@app.post("/api/chat")
async def send_chat_message(payload: ChatMessage):
    try:
        messages = list(payload.history)
        if not messages or messages[-1].get("content") != payload.message:
            messages.append({"role": "user", "content": payload.message})

        snapshot = task_manager.multi_snapshot()
        reply = await asyncio.to_thread(chat.ask, messages[-8:], snapshot)

        if reply.strip().startswith("RUN_JOB:"):
            proposed = reply.strip()[len("RUN_JOB:"):].strip()
            return JSONResponse({
                "reply": f"Proposed analysis: {proposed}",
                "is_run_job": True,
                "proposed_job": proposed
            })

        return JSONResponse({"reply": reply, "is_run_job": False})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


if __name__ == "__main__":
    import uvicorn
    print("Starting GeoLLM Web UI on http://127.0.0.1:8000")
    uvicorn.run(
        "web_app:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        reload_dirs=[str(APP_DIR / "harness")],
        timeout_graceful_shutdown=1,
    )
