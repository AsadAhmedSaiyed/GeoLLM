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
from harness.orchestrator import TaskManager
from harness import chat

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

app = FastAPI(title="GeoLLM Web Interface")

DATA_DIR = Path("data")
RUNS_DIR = Path("runs")
TEMPLATES_DIR = Path("templates")

DATA_DIR.mkdir(exist_ok=True)
RUNS_DIR.mkdir(exist_ok=True)
TEMPLATES_DIR.mkdir(exist_ok=True)

app.mount("/runs", StaticFiles(directory="runs"), name="runs")
app.mount("/data", StaticFiles(directory="data"), name="data")

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


def find_artifacts(run_dir):
    artifacts = []
    if not run_dir or not Path(run_dir).exists():
        return artifacts
    for p in Path(run_dir).rglob("*"):
        if p.is_file() and p.suffix.lower() in [".png", ".tif", ".geojson", ".csv", ".json"]:
            if any(x in p.name.lower() for x in ["feedback", "events", "stderr", "stdout", "code.py", "script.py", "last_status", "plan.json", ".flag"]):
                continue
            try:
                rel = p.relative_to(Path.cwd()).as_posix()
            except ValueError:
                parts = p.parts
                idx = parts.index("runs") if "runs" in parts else 0
                rel = "/".join(parts[idx:])
            artifacts.append({
                "name": p.name,
                "url": f"/{rel}",
                "type": "image" if p.suffix.lower() == ".png" else "raster" if p.suffix.lower() in (".tif", ".tiff") else "file",
                "ext": p.suffix.lower()
            })
    return artifacts


def _parse_milestone(task_id, ev_text):
    lo = ev_text.lower()
    if "thinking" in lo or "reading" in lo or "drafting" in lo:
        icon = "thinking"
    elif "sandbox tool" in lo or "running" in lo:
        icon = "running"
    elif "finished" in lo:
        icon = "error" if "iserror=true" in lo or "failed" in lo else "check"
    elif "vision" in lo:
        icon = "vision"
    elif "success" in lo:
        icon = "done"
    elif "failed" in lo or "error" in lo:
        icon = "error"
    elif "plan" in lo or "approval" in lo:
        icon = "plan"
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

    async def event_generator():
        last_count = 0
        last_step = ""
        sent_artifacts = False
        sent_plan = False

        yield f"data: {json.dumps({'type': 'start', 'task_id': task_id, 'question': ts.question})}\n\n"

        while True:
            if await request.is_disconnected():
                break

            current = task_manager.get_task(task_id)
            if not current:
                break

            for ev in current.events[last_count:]:
                yield f"data: {json.dumps(_parse_milestone(task_id, ev))}\n\n"
            last_count = len(current.events)

            if current.step != last_step:
                last_step = current.step
                yield f"data: {json.dumps({'type': 'step', 'task_id': task_id, 'text': last_step})}\n\n"

            if current.status == "pending_approval" and current.plan and not sent_plan:
                sent_plan = True
                yield f"data: {json.dumps({'type': 'plan_ready', 'task_id': task_id, 'plan': current.plan})}\n\n"
            elif current.status != "pending_approval":
                sent_plan = False

            if current.status in ("done", "partial", "failed"):
                if not sent_artifacts and current.result:
                    arts = find_artifacts(current.result.get("run_dir"))
                    if arts:
                        sent_artifacts = True
                        yield f"data: {json.dumps({'type': 'artifacts', 'task_id': task_id, 'artifacts': arts})}\n\n"
                yield f"data: {json.dumps({'type': 'finish', 'task_id': task_id, 'status': current.status, 'error': current.error})}\n\n"
                break

            await asyncio.sleep(1.0)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    if not task_manager.cancel_task(task_id):
        return JSONResponse({"error": "Task not running."}, status_code=400)
    return JSONResponse({"task_id": task_id, "status": "cancelled"})


@app.get("/api/tasks/{task_id}/artifacts")
async def get_task_artifacts(task_id: str):
    ts = task_manager.get_task(task_id)
    if not ts or not ts.result:
        return JSONResponse({"artifacts": []})
    run_dir = ts.result.get("run_dir")
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
