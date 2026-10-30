"""GeoLLM Web UI Server (FastAPI + SSE + Multi-Task)."""
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import List, Optional, Dict, Any

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


@app.get("/api/runs/{task_id}/timeline.json")
async def get_timeline(task_id: str):
    ts = task_manager.get_task(task_id)
    if not ts:
        return JSONResponse({"error": "Task not found"}, status_code=404)
    run_dir = ts.state.get("run_dir") or (ts.result.get("run_dir") if ts.result else None)
    if not run_dir:
        return JSONResponse({"error": "No run_dir"}, status_code=404)
    p = Path(run_dir)
    cands = list(p.rglob("timeline.json"))
    if cands and cands[0].exists():
        try:
            data = json.loads(cands[0].read_text(encoding="utf-8"))
            timeline_dir = cands[0].parent
            try:
                rel_base = timeline_dir.relative_to(Path.cwd()).as_posix()
            except ValueError:
                parts = timeline_dir.parts
                idx = parts.index("runs") if "runs" in parts else 0
                rel_base = "/".join(parts[idx:])

            # Dynamically resolve png_url so frontend gets direct HTTP 200 URLs
            for frame in data.get("frames", []):
                fname = frame.get("file") or ""
                frame_fname = Path(fname).name
                if (timeline_dir / frame_fname).exists():
                    frame["png_url"] = f"/{rel_base}/{frame_fname}"
                elif not frame.get("png_url"):
                    frame["png_url"] = f"/api/tasks/{task_id}/artifacts/{frame_fname}"
            return JSONResponse(data)
        except Exception as e:
            return JSONResponse({"error": f"Invalid timeline.json: {e}"}, status_code=500)
    return JSONResponse({"error": "timeline.json not found"}, status_code=404)


@app.get("/api/tasks/{task_id}/artifacts")
async def get_task_artifacts(task_id: str):
    ts = task_manager.get_task(task_id)
    if not ts:
        return JSONResponse({"artifacts": []})
    run_dir = ts.state.get("run_dir") or (ts.result.get("run_dir") if ts.result else None)
    return JSONResponse({"artifacts": find_artifacts(run_dir)})


@app.get("/api/tasks/{task_id}/artifacts/{artifact_path:path}")
async def get_task_artifact_file(task_id: str, artifact_path: str):
    """Serve any task deliverable or generated frame directly by filename or relative path."""
    ts = task_manager.get_task(task_id)
    if not ts:
        raise HTTPException(status_code=404, detail="Task not found")
    run_dir = ts.state.get("run_dir") or (ts.result.get("run_dir") if ts.result else None)
    if not run_dir:
        raise HTTPException(status_code=404, detail="No run_dir for task")
    rd = Path(run_dir)
    fname = Path(artifact_path).name
    # Search run_dir recursively for this artifact file
    cands = list(rd.rglob(fname))
    if cands:
        # Prefer latest attempt outputs
        chosen = sorted(cands, key=lambda p: str(p), reverse=True)[0]
        ext = chosen.suffix.lower()
        media_type = (
            "image/png" if ext == ".png"
            else "image/gif" if ext == ".gif"
            else "image/tiff" if ext in (".tif", ".tiff")
            else "application/json" if ext == ".json"
            else "application/octet-stream"
        )
        return FileResponse(chosen, media_type=media_type)
    raise HTTPException(status_code=404, detail=f"Artifact '{fname}' not found in task run")


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


def geotiff_to_png_bytes(tif_path: Path, max_dim: int = 2048) -> bytes:
    mtime = os.path.getmtime(tif_path)
    cache_key = (str(tif_path.resolve()), mtime)
    if cache_key in _RASTER_PNG_CACHE:
        return _RASTER_PNG_CACHE[cache_key]

    import io
    import numpy as np
    from PIL import Image
    import rasterio
    from rasterio.enums import Resampling

    with rasterio.open(tif_path) as src:
        src_h, src_w = src.height, src.width
        if max(src_h, src_w) > max_dim:
            scale = max_dim / max(src_h, src_w)
            out_shape = (max(1, int(src_h * scale)), max(1, int(src_w * scale)))
        else:
            out_shape = (src_h, src_w)

        nodata = src.nodata

        if src.count >= 3:
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
            is_int = np.issubdtype(src.dtypes[0], np.integer)
            b = src.read(1, out_shape=out_shape, resampling=Resampling.nearest if is_int else Resampling.bilinear)
            mask = np.ones(out_shape, dtype=bool)
            if nodata is not None:
                mask &= (b != nodata)

            # Check colormap
            cmap = None
            try:
                cmap = src.colormap(1)
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
                unique_vals = np.unique(valid_b) if len(valid_b) > 0 else np.array([])
                if is_int and len(unique_vals) <= 25:
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
                    import matplotlib.cm as cm
                    b_float = b.astype(np.float32)
                    valid_pixels = b_float[mask] if np.any(mask) else b_float.flatten()
                    if len(valid_pixels) > 0:
                        vmin, vmax = np.nanpercentile(valid_pixels, 2), np.nanpercentile(valid_pixels, 98)
                    else:
                        vmin, vmax = 0, 1
                    if vmax > vmin:
                        norm = np.clip((b_float - vmin) / (vmax - vmin), 0.0, 1.0)
                    else:
                        norm = np.zeros_like(b_float)
                    colored = cm.viridis(norm)
                    rgba = (colored * 255.0).astype(np.uint8)
                    rgba[:, :, 3] = np.where(mask, 230, 0).astype(np.uint8)
                    img = Image.fromarray(rgba, "RGBA")

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        result = buf.getvalue()
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

            # MapLibre image coordinate order: [top-left, top-right, bottom-right, bottom-left]
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
async def get_raster_png(path: str):
    """
    Renders any GeoTIFF as a high-performance in-memory PNG with transparent nodata
    and accurate georeferencing for 3D Globe overlay in MapLibre GL.
    """
    try:
        p = resolve_raster_path(path)
        if not p or not p.exists():
            return JSONResponse({"ok": False, "error": f"File not found: {path}"}, status_code=404)

        png_bytes = await asyncio.to_thread(geotiff_to_png_bytes, p)
        return Response(content=png_bytes, media_type="image/png")
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
    uvicorn.run(app, host="127.0.0.1", port=8000)
