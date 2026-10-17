"""GeoLLM Web UI Server (FastAPI + Server-Sent Events + Live Chat + Instant Outputs)."""
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import List

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

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

active_process = None


class ChatMessage(BaseModel):
    message: str


def find_artifacts(run_dir):
    """Scans the run directory for all output images, rasters, and vectors."""
    artifacts = []
    if not run_dir or not Path(run_dir).exists():
        return artifacts
    for p in Path(run_dir).rglob("*"):
        if p.is_file() and p.suffix.lower() in [".png", ".tif", ".geojson", ".csv", ".json"]:
            if any(x in p.name.lower() for x in ["feedback", "events", "stderr", "stdout", "code.py", "script.py", "last_status"]):
                continue
            try:
                rel = p.relative_to(Path.cwd()).as_posix()
            except ValueError:
                parts = p.parts
                if "runs" in parts:
                    idx = parts.index("runs")
                    rel = "/".join(parts[idx:])
                else:
                    rel = p.name
            artifacts.append({
                "name": p.name,
                "url": f"/{rel}",
                "type": "image" if p.suffix.lower() == ".png" else "file",
                "ext": p.suffix.lower()
            })
    return artifacts


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
        dest = DATA_DIR / file.filename
        with dest.open("wb") as buffer:
            while chunk := await file.read(1024 * 1024):
                buffer.write(chunk)
        uploaded.append(file.filename)
    return JSONResponse({"uploaded": uploaded})


@app.post("/api/chat")
async def send_chat_message(payload: ChatMessage):
    """Sends user input to main.py's stdin for interactive supervisor chat."""
    global active_process
    if not active_process or active_process.poll() is not None:
        return JSONResponse({"error": "No active analysis process running."}, status_code=400)

    try:
        active_process.stdin.write(payload.message.strip() + "\n")
        active_process.stdin.flush()
        return JSONResponse({"status": "sent"})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/stream_run")
def stream_run(question: str, files: str, bands: str = ""):
    global active_process
    selected_files = [f.strip() for f in files.split(",") if f.strip()]
    file_args = []
    for f in selected_files:
        p = Path(f) if Path(f).exists() else DATA_DIR / f
        file_args.append(str(p))

    cmd = [sys.executable, "-u", "main.py", question] + file_args
    if bands:
        cmd.extend(["--bands", bands])

    def log_generator():
        global active_process
        yield f"data: {json.dumps({'type': 'start', 'cmd': ' '.join(cmd)})}\n\n"

        active_process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
            env=os.environ.copy(),
        )

        run_dir = None
        artifacts_sent = False

        for line in iter(active_process.stdout.readline, ""):
            # Capture run folder path
            if "run folder:" in line.lower() or "run directory:" in line.lower():
                parts = line.split(":", 1)
                if len(parts) > 1:
                    run_dir = parts[1].strip()

            yield f"data: {json.dumps({'type': 'log', 'text': line})}\n\n"

            # When subagent finishes, immediately push artifacts to the UI
            lower = line.lower()
            if ("[geollm] run success" in lower or "[geollm] finished" in lower or "[geollm] run partial" in lower) and not artifacts_sent:
                time.sleep(1.0)
                artifacts = find_artifacts(run_dir)
                if artifacts:
                    artifacts_sent = True
                    yield f"data: {json.dumps({'type': 'artifacts', 'artifacts': artifacts})}\n\n"

        if not artifacts_sent and run_dir:
            artifacts = find_artifacts(run_dir)
            yield f"data: {json.dumps({'type': 'artifacts', 'artifacts': artifacts})}\n\n"

        if active_process.stdout:
            active_process.stdout.close()
        returncode = active_process.wait()
        yield f"data: {json.dumps({'type': 'finish', 'returncode': returncode})}\n\n"

    return StreamingResponse(log_generator(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn
    print("Starting GeoLLM Web UI on http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)
