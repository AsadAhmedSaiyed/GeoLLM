"""GeoLLM Web UI Server (FastAPI + SSE + Multi-Task)."""
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import List

from fastapi import FastAPI, File, UploadFile, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import harness
from geollm_lib.bands import ROLES
from harness.orchestrator import TaskManager, find_artifacts
from harness import chat

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

app = FastAPI(title="GeoLLM Web Interface")

DATA_DIR = Path("data")
RUNS_DIR = Path("runs")
STATIC_DIR = Path("static")
TEMPLATES_DIR = Path("templates")

DATA_DIR.mkdir(exist_ok=True)
RUNS_DIR.mkdir(exist_ok=True)
TEMPLATES_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)

app.mount("/runs", StaticFiles(directory="runs"), name="runs")
app.mount("/data", StaticFiles(directory="data"), name="data")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Web manager requires human plan approval in browser
task_manager = TaskManager(auto_approve=False)


class ChatMessage(BaseModel):
    message: str
    history: list = []

class TaskSubmission(BaseModel):
    question: str
    files: str = ""
    bands: str = ""

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
async def index():
    html_file = TEMPLATES_DIR / "index.html"
    if not html_file.exists():
        return HTMLResponse("<h1>Error: templates/index.html not found</h1>", status_code=404)
    return html_file.read_text(encoding="utf-8")


@app.get("/api/files")
async def list_data_files():
    valid_exts = {".tif", ".tiff", ".geojson", ".gpkg", ".json", ".nc", ".h5"}
    files = [
        {"name": f.name, "size_mb": round(f.stat().st_size / (1024 * 1024), 2)}
        for f in sorted(DATA_DIR.glob("*"))
        if f.suffix.lower() in valid_exts
    ]
    return JSONResponse({"files": files})


@app.post("/api/upload")
async def upload_file(files: List[UploadFile] = File(...)):
    uploaded = []
    for file in files:
        safe_name = Path(file.filename).name
        dest = DATA_DIR / safe_name
        with dest.open("wb") as buffer:
            while chunk := await file.read(1024 * 1024):
                buffer.write(chunk)
        uploaded.append(safe_name)
    return JSONResponse({"uploaded": uploaded})


@app.post("/api/tasks")
async def submit_task(payload: TaskSubmission):
    selected_files = [f.strip() for f in payload.files.split(",") if f.strip()]
    if not selected_files:
        return JSONResponse({"error": "Please select at least one dataset file to analyze."}, status_code=400)

    file_args = []
    for f in selected_files:
        p = Path(f) if Path(f).exists() else DATA_DIR / f
        if not p.exists():
            return JSONResponse({"error": f"File not found: '{f}' in workspace or data/"}, status_code=400)
        file_args.append(str(p))

    overrides = {}
    if payload.bands:
        for part in filter(None, payload.bands.split(",")):
            role, _, num = part.partition("=")
            role = role.strip()
            num = num.strip()
            if role not in ROLES or not num.isdigit():
                return JSONResponse({"error": f"Invalid band format '{part}'. Use role=number with {ROLES}"}, status_code=400)
            overrides[role] = int(num)

    task_id = task_manager.submit_task(payload.question, file_args, overrides=overrides)
    if task_id is None:
        return JSONResponse({"error": "All 3 task slots are busy."}, status_code=429)
    return JSONResponse({"task_id": task_id, "status": "running"})


@app.get("/api/tasks")
async def list_tasks():
    tasks = []
    for tid in task_manager.tasks:
        ts = task_manager.tasks[tid]
        tasks.append({
            "task_id": tid,
            "status": ts.status,
            "question": ts.question,
            "step": ts.step,
            "error": ts.error,
            "elapsed": round((ts.ended or time.time()) - ts.started, 1) if ts.started else 0,
            "plan": ts.plan,
        })
    return JSONResponse({"tasks": tasks})


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
            if await request.is_disconnected():
                break

            current = task_manager.get_task(task_id)
            if not current:
                break

            events_to_send = []
            with task_manager._lock:
                for ev in current.event_log:
                    ev_id = ev.get("id", 0)
                    if ev_id > last_sent_id:
                        events_to_send.append(ev)

            for ev in events_to_send:
                ev_id = ev.get("id")
                last_sent_id = ev_id
                last_keepalive = time.time()
                yield f"id: {ev_id}\ndata: {json.dumps(ev)}\n\n"

            # Stop streaming only after a finish event
            if current.status in ("done", "partial", "failed"):
                if any(ev.get("type") == "finish" for ev in events_to_send) or (
                    len(current.event_log) > 0 and current.event_log[-1].get("type") == "finish" and last_sent_id >= current.event_log[-1].get("id", 0)
                ):
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


@app.get("/api/tasks/{task_id}/artifacts")
async def get_task_artifacts(task_id: str):
    ts = task_manager.get_task(task_id)
    if not ts:
        return JSONResponse({"artifacts": []})
    run_dir = ts.state.get("run_dir") or (ts.result.get("run_dir") if ts.result else None)
    return JSONResponse({"artifacts": find_artifacts(run_dir)})


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
    uvicorn.run(app, host="127.0.0.1", port=8000)
