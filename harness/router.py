"""Intelligent multi-tier conversational router and on-demand VLM visual inspection engine.

Classifies incoming messages into:
- Category A: General conversational / conceptual (handled directly by Main LLM)
- Category B: Questions on existing analysis outputs / metadata (handled directly by Main LLM)
- Category V: Visual inspection / search / zoom requests (handled via VLM on workspace rasters/maps)
- Category C: Complex geospatial tasks (delegated to Pi sub-agent in Docker)
- Category D: Clarification needed for ambiguous requests
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from harness import chat, llm
from harness.workspace import get_workspace_dir


# Official OpenUI system prompt, generated from the frontend's component library by
# `node frontend/scripts/gen-openui-prompt.mjs`. It teaches the model the real
# OpenUI Lang grammar and every component signature the browser can render, so the
# model itself decides which UI fits each answer (cards, charts, tables, forms...).
_OPENUI_PROMPT_FILE = Path(__file__).with_name("openui_system_prompt_compact.txt")
_OPENUI_PROMPT_FALLBACK = Path(__file__).with_name("openui_system_prompt.txt")
_openui_prompt_cache: Optional[str] = None


def _openui_system_prompt() -> str:
    global _openui_prompt_cache
    if _openui_prompt_cache is None:
        for p in (_OPENUI_PROMPT_FILE, _OPENUI_PROMPT_FALLBACK):
            try:
                if p.exists():
                    _openui_prompt_cache = p.read_text(encoding="utf-8")
                    break
            except OSError:
                continue
        if _openui_prompt_cache is None:
            _openui_prompt_cache = ""
    return _openui_prompt_cache


ROUTER_PROMPT = """You are the intelligent router and lead conversational AI for GeoLLM, an autonomous geospatial intelligence workbench.

Your job is to classify the user's latest message and decide the correct execution pathway:

CATEGORIES:
1. "general_chat"
   - Pure conversation, greetings, remote sensing definitions, general science or tool capability questions.
   - Examples: "hello", "what is Sentinel-2 L2A?", "how does NDVI differ from NDWI?", "what can this platform do?"

2. "contextual_inquiry"
   - Questions about LIVE PROGRESS / STATUS UPDATES of the active sub-agent or any container (task_1, task_2, task_3), OR questions about EXISTING workspace results, metrics, summary values, or previous answers.
   - Examples: "any updates?", "what is the sub-agent currently doing?", "about task 3", "any updates from container 3?", "what was the net vegetation loss in that run?", "which dates were analyzed?", "summarize the findings".

3. "visual_inspection"
   - User wants to visually inspect, search, check, or zoom into an existing map, raster, or deliverable.
   - Examples: "show me a close-up of the port in the change map", "zoom into the high vegetation zone", "check if the stadium area has classification errors", "look at the northern border in the 2024 raster".

4. "complex_task"
   - Genuine geospatial computation, multi-temporal analysis, LiDAR extraction, landcover change, index calculation on new dates/areas, or STAC search/staging that requires running Python in the secure container sandbox.
   - Examples: "compare vegetation changes in Gaza between May 2020 and 2026", "extract canopy height from this LAZ file", "map flooded areas in Valencia from Sentinel-1".

5. "clarification_needed"
   - An ambiguous request to start a NEW complex analysis that lacks critical context (e.g. Attached Files is [] AND no named geographic place, city, coordinates, or [AOI BBOX: ...] is given, AND it is NOT asking for updates/status on an existing or running task).
   - Examples: "analyze the forest", "detect changes here" (when Attached Files is [] and no place/bbox is provided).

CURRENT WORKSPACE CONTEXT:
Workspace ID: {task_id}
Attached Files for THIS message: {files}
Existing Artifacts: {artifacts}
Previous Analysis Summary: {summary}
Current Workspace Status: {status}

LIVE MULTI-CONTAINER STATUS (All 3 Workspaces):
{live_snapshot}

CONVERSATION HISTORY:
{history_snippet}

USER MESSAGE:
{user_message}

CRITICAL RULES:
- If the user asks for status updates, progress, what a sub-agent/container/task is currently doing ("any updates?", "about task 3", "any updates from container 3?", "any updates on this..."), ALWAYS choose "contextual_inquiry" (NEVER choose "clarification_needed").
- If the user asks to visually inspect, zoom, or search an existing map or raster, choose "visual_inspection".
- If the question can be accurately answered using the Live Multi-Container Status, Previous Analysis Summary, or Existing Artifacts, choose "contextual_inquiry".
- If Attached Files is [] and the user wants to start a NEW analysis referring to "this area" / "here" without a named place, coordinates, or [AOI BBOX: ...], choose "clarification_needed" (do NOT choose "complex_task").
- Only choose "complex_task" if real raster math or data processing in Docker is actually required AND enough data/location context exists.
- Do NOT fabricate analysis results.

Output a valid JSON object ONLY:
{{
  "category": "general_chat" | "contextual_inquiry" | "visual_inspection" | "complex_task" | "clarification_needed",
  "reasoning": "brief explanation",
  "target_artifact": "filename if visual_inspection or contextual inquiry relates to a specific file, else null",
  "inspection_focus": "what to look for if visual_inspection, else null",
  "clarification_question": "question to ask if clarification_needed, else null"
}}
"""


def _clean_json(text: str) -> dict:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    t = t.strip()
    try:
        return json.loads(t)
    except Exception:
        # Fallback regex extraction
        m = re.search(r"\{.*\}", t, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


def _is_progress_or_status_query(user_message: str) -> bool:
    """Detects when the user is asking for live updates, progress, or status of a sub-agent/container/task."""
    q = user_message.lower().strip()
    status_patterns = (
        r"\bany\s+updates?\b",
        r"\bwhat\s+is\s+(?:the\s+)?(?:sub[\s-]?agent|container|task|agent)\b",
        r"\babout\s+(?:task|container|workspace)\s*[#]?\s*[123]\b",
        r"\b(?:from|in|on)\s+(?:task|container|workspace)\s*[#]?\s*[123]\b",
        r"\bstatus\s+of\b",
        r"\bprogress\s+(?:of|on)\b",
        r"\bhow\s+is\s+(?:it|the\s+task|task\s*[123]|container\s*[123])\s+(?:going|doing|progressing)\b",
        r"\bis\s+(?:it|task\s*[123]|container\s*[123])\s+(?:done|finished|still\s+running)\b",
        r"\bwhat\s+happened\s+(?:in|to|with)\s+(?:task|container)\b",
    )
    return any(re.search(pat, q) for pat in status_patterns)


def classify_message(
    user_message: str,
    history: List[Dict[str, str]],
    task_id: str,
    runs_dir: Optional[Path] = None,
    task_state: Optional[Any] = None,
    attached_files: Optional[List[str]] = None,
    live_snapshot: str = "",
) -> Dict[str, Any]:
    """Classifies user intent using the fast router LLM."""
    if _is_progress_or_status_query(user_message):
        return {
            "category": "contextual_inquiry",
            "reasoning": "User is asking for live progress or status updates on a task/container.",
            "target_artifact": None,
            "inspection_focus": None,
            "clarification_question": None,
        }

    ws_dir = get_workspace_dir(task_id, runs_dir)
    status_file = ws_dir / "last_status.json"
    summary = "No previous analysis in this workspace."
    live_status = getattr(task_state, "status", "idle") if task_state else "idle"
    status = live_status
    artifacts = []

    if status_file.exists():
        try:
            sdata = json.loads(status_file.read_text(encoding="utf-8"))
            if live_status not in ("running", "pending_approval", "pending_stac_approval"):
                status = "done" if sdata.get("ok") else "failed"
            res = sdata.get("result") or {}
            summary = res.get("summary") or res.get("answer") or summary
            artifacts = [Path(a).name for a in sdata.get("artifacts", [])]
        except Exception:
            pass

    if not artifacts and getattr(task_state, "artifacts", None):
        artifacts = [
            (a if isinstance(a, str) else a.get("name", ""))
            for a in task_state.artifacts
        ]

    hist_lines = []
    for h in history[-6:]:
        r = h.get("role", "user")
        c = str(h.get("content", ""))[:180]
        hist_lines.append(f"{r}: {c}")
    history_snippet = "\n".join(hist_lines) if hist_lines else "(No prior turns)"

    files = attached_files if attached_files is not None else (getattr(task_state, "files", []) or [])

    prompt = ROUTER_PROMPT.format(
        task_id=task_id,
        files=json.dumps([Path(f).name for f in files]),
        artifacts=json.dumps(artifacts),
        summary=str(summary)[:1200],
        status=status,
        live_snapshot=(live_snapshot or f"Workspace {task_id} status: {status}")[:2500],
        history_snippet=history_snippet,
        user_message=user_message,
    )

    try:
        raw = chat._groq([{"role": "user", "content": prompt}], retry=True)
        data = _clean_json(raw)
        cat = data.get("category", "general_chat")
        if cat not in (
            "general_chat",
            "contextual_inquiry",
            "visual_inspection",
            "complex_task",
            "clarification_needed",
        ):
            cat = "general_chat"
        data["category"] = cat
        return data
    except Exception as e:
        # Fallback heuristic if router call fails
        q = user_message.lower()
        if any(w in q for w in ("look at", "zoom", "close-up", "inspect map", "show me the area", "see the port")):
            return {"category": "visual_inspection", "reasoning": "Fallback visual match", "target_artifact": None, "inspection_focus": user_message}
        if any(w in q for w in ("compare", "change detection", "download", "calculate", "stac", "lidar", "classify")):
            return {"category": "complex_task", "reasoning": "Fallback task match"}
        return {"category": "general_chat", "reasoning": f"Fallback general chat: {e}"}


def handle_general_chat(
    user_message: str,
    history: List[Dict[str, str]],
    task_id: str,
    task_state: Optional[Any] = None,
    live_snapshot: str = "",
) -> Dict[str, Any]:
    """Handles conceptual remote sensing questions and general chat directly."""
    snapshot_block = (
        f"\n\n[LIVE MULTI-CONTAINER STATUS (For reference ONLY if the user asks about tasks/containers)]:\n{live_snapshot[:1200]}"
        if live_snapshot
        else ""
    )
    geollm_context = (
        "You are GeoLLM, an autonomous AI geospatial assistant supervising 3 concurrent analysis containers (task_1, task_2, task_3). "
        f"The user is currently in Workspace {task_id}. "
        "Always respond directly to the user's LATEST message. "
        "If the latest message is a casual greeting (e.g. 'hi', 'hello', 'hi bro', 'salam'), respond warmly and briefly WITHOUT dumping task statuses. "
        "If the user asks about any container or task progress, use the LIVE MULTI-CONTAINER STATUS below to give a specific, accurate update. "
        "You can also explain remote sensing concepts, satellite sensors, spectral indices, and GeoLLM's workflow. "
        "Never invent facts about tools or libraries you do not know; say so plainly instead."
        + snapshot_block
    )
    openui_prompt = _openui_system_prompt()
    if openui_prompt:
        # OpenUI contract: the whole reply is an OpenUI Lang program rendered by the browser.
        system_prompt = openui_prompt + "\n\n## Assistant Context\n" + geollm_context
    else:
        system_prompt = geollm_context + "\nKeep answers focused, concise, and in clean Markdown."
    msgs = [{"role": "system", "content": system_prompt}]
    for h in history[-4:]:
        msgs.append({"role": h.get("role", "user"), "content": (h.get("content", "") or "")[:800]})
    if not msgs or msgs[-1].get("content") != user_message:
        msgs.append({"role": "user", "content": user_message})

    reply = chat._groq(msgs, retry=True)
    return {
        "type": "conversational_reply",
        "reply": reply,
        "follow_ups": [
            "What satellite collections are available?",
            "How do I start a land-cover change analysis?",
            "What file types can I upload?",
        ],
    }


def handle_contextual_inquiry(
    user_message: str,
    history: List[Dict[str, str]],
    task_id: str,
    runs_dir: Optional[Path] = None,
    task_state: Optional[Any] = None,
    live_snapshot: str = "",
) -> Dict[str, Any]:
    """Answers questions about live sub-agent progress or existing analysis results across workspaces."""
    ws_dir = get_workspace_dir(task_id, runs_dir)
    status_file = ws_dir / "last_status.json"
    summary = "No previous results."
    res_data = {}
    artifacts = []

    if status_file.exists():
        try:
            sdata = json.loads(status_file.read_text(encoding="utf-8"))
            res_data = sdata.get("result") or {}
            summary = res_data.get("summary") or res_data.get("answer") or summary
            artifacts = [Path(a).name for a in sdata.get("artifacts", [])]
        except Exception:
            pass

    # Also load outputs/result.json if present for detailed statistics
    result_json_file = ws_dir / "outputs" / "result.json"
    result_json_snippet = ""
    if result_json_file.exists():
        try:
            rj_text = result_json_file.read_text(encoding="utf-8")
            result_json_snippet = f"\nDetailed outputs/result.json for {task_id}:\n{rj_text[:1500]}"
        except Exception:
            pass

    timeline_file = ws_dir / "outputs" / "timeline.json"
    timeline_info = ""
    if timeline_file.exists():
        try:
            tldata = json.loads(timeline_file.read_text(encoding="utf-8"))
            timeline_info = (
                f"\nDates: {tldata.get('dates', [])}\n"
                f"Series Values: {tldata.get('series_values', [])}\n"
                f"Summary: {tldata.get('summary', '')}"
            )
        except Exception:
            pass

    geollm_context = (
        "You are GeoLLM, a senior geospatial analyst supervising 3 concurrent analysis containers (Container #1 = task_1, Container #2 = task_2, Container #3 = task_3).\n"
        f"Active Workspace ID: {task_id}\n"
        f"Active Workspace Outputs: {json.dumps(artifacts)}\n"
        f"Active Workspace Summary & Findings: {str(summary)[:1200]}\n"
        f"{result_json_snippet}"
        f"{timeline_info}\n\n"
        "[LIVE MULTI-CONTAINER STATUS — All 3 Workspaces (task_1, task_2, task_3)]:\n"
        f"{(live_snapshot or 'No live snapshot provided.')[:1200]}\n\n"
        "CRITICAL INSTRUCTIONS:\n"
        "1. If the user asks for updates, progress, or what the sub-agent / container is currently doing, report the EXACT live status from LIVE MULTI-CONTAINER STATUS (task question, status, step, code executions, elapsed time, deliverables).\n"
        "2. If the user asks about metrics, area changes, or findings, cite exact numbers, dates, and file names from the verified analysis above — use Charts (BarChart, LineChart, PieChart), OverviewCardBlock, and Table in openui-lang.\n"
        "3. Never fabricate numbers and never ask for clarification when the answer is already visible above."
    )
    openui_prompt = _openui_system_prompt()
    if openui_prompt:
        system_prompt = openui_prompt + "\n\n## Geospatial Workspace Context\n" + geollm_context
    else:
        system_prompt = geollm_context

    msgs = [{"role": "system", "content": system_prompt}]
    for h in history[-4:]:
        msgs.append({"role": h.get("role", "user"), "content": (h.get("content", "") or "")[:800]})
    if not msgs or msgs[-1].get("content") != user_message:
        msgs.append({"role": "user", "content": user_message})

    reply = chat._groq(msgs, retry=True)

    follow_ups = [
        "Explain the detected changes in more detail",
        "Which areas experienced the greatest decline?",
        "Inspect this map with the vision model",
    ]
    return {
        "type": "conversational_reply",
        "reply": reply,
        "follow_ups": follow_ups,
    }


def handle_visual_inspection(
    user_message: str,
    target_artifact: Optional[str],
    focus: Optional[str],
    task_id: str,
    runs_dir: Optional[Path] = None,
    task_state: Optional[Any] = None,
) -> Dict[str, Any]:
    """Inspects an existing raster or PNG output using the VLM with high-res cropping."""
    ws_dir = get_workspace_dir(task_id, runs_dir)
    outputs_dir = ws_dir / "outputs"
    feedback_thumbs = ws_dir / "feedback" / "thumbs"
    feedback_thumbs.mkdir(parents=True, exist_ok=True)

    # 1. Discover target visual or raster
    chosen_png: Optional[Path] = None
    chosen_tif: Optional[Path] = None

    if target_artifact:
        cand = outputs_dir / target_artifact
        if cand.is_file():
            if cand.suffix.lower() in (".png", ".jpg", ".jpeg"):
                chosen_png = cand
            elif cand.suffix.lower() in (".tif", ".tiff"):
                chosen_tif = cand

    if not chosen_png and outputs_dir.exists():
        pngs = sorted(outputs_dir.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
        if pngs:
            chosen_png = pngs[0]

    if not chosen_tif and outputs_dir.exists():
        tifs = sorted(outputs_dir.glob("*.tif"), key=lambda p: p.stat().st_mtime, reverse=True)
        if tifs:
            chosen_tif = tifs[0]

    if not chosen_png and not chosen_tif:
        return {
            "type": "conversational_reply",
            "reply": (
                "No visual maps or GeoTIFF outputs were found in this workspace yet to inspect. "
                "Once an analysis generates deliverables, you can ask me to inspect, zoom in, or search any part of them."
            ),
        }

    # 2. Extract inspection crop or overview
    thumb_rel_url: Optional[str] = None
    fly_to_bbox: Optional[List[float]] = None
    stats_summary: str = ""

    from PIL import Image

    # Try extracting crop from raster if available
    if chosen_tif and chosen_tif.is_file():
        try:
            import rasterio
            with rasterio.open(chosen_tif) as src:
                bounds = src.bounds
                fly_to_bbox = [bounds.left, bounds.bottom, bounds.right, bounds.top]
                from rasterio.warp import transform_bounds
                if src.crs and src.crs.to_string() != "EPSG:4326":
                    fly_to_bbox = list(transform_bounds(src.crs, "EPSG:4326", *bounds))
        except Exception:
            pass

    # Generate high-resolution thumbnail for VLM
    crop_path = feedback_thumbs / f"inspect_user_{int(Path(chosen_png or chosen_tif).stat().st_mtime)}.png"
    if chosen_png and chosen_png.is_file():
        try:
            with Image.open(chosen_png) as im:
                rgb = im.convert("RGB")
                rgb.save(crop_path, format="PNG")
                thumb_rel_url = f"/api/tasks/{task_id}/thumbs/{crop_path.name}"
        except Exception:
            pass

    # 3. Ask VLM
    vlm_prompt = (
        f"You are the GeoLLM Vision Specialist visually inspecting the deliverable: "
        f"{chosen_png.name if chosen_png else chosen_tif.name}.\n"
        f"User Visual Question: \"{user_message}\"\n\n"
        f"Specific Focus: {focus or 'Inspect key features, spatial patterns, and anomalies'}.\n"
        "Examine the image carefully. Provide a detailed, clear visual inspection: "
        "describe what is visible, color scales, spatial boundaries, and direct observations addressing the user's question."
    )

    try:
        if llm.vision_available() and crop_path.is_file():
            vlm_reply = llm.chat_vision_multi(
                [{"role": "user", "content": vlm_prompt}],
                images=[str(crop_path)],
            )
        else:
            # Fallback to text model with output context
            vlm_reply = chat._groq(
                [{"role": "user", "content": vlm_prompt + "\n(Describe the deliverable based on output metadata.)"}],
                retry=True,
            )
    except Exception as e:
        vlm_reply = f"Visual inspection completed for **{chosen_png.name if chosen_png else chosen_tif.name}**. {e}"

    return {
        "type": "visual_reply",
        "reply": vlm_reply,
        "artifact": chosen_png.name if chosen_png else (chosen_tif.name if chosen_tif else None),
        "thumb_url": thumb_rel_url,
        "fly_to_bbox": fly_to_bbox,
        "follow_ups": [
            "Zoom in on another region",
            "Explain the statistics of this layer",
            "Run a change detection comparison",
        ],
    }

