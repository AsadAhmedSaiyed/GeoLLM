"""Phase 3 – Agentic Vision Validation Loop.

Replaces the single ``check_images()`` call with a structured multi-turn
loop where the vision model drives inspection by issuing tool calls.

The loop is feature-gated: set ``GEOLLM_VALIDATION_MODE=agentic`` to
activate it.  The legacy path in ``visual_check.py`` remains the default
and is untouched.

Entry point
-----------
``validate_artifacts(task, output_dir, pngs, feedback_dir, on_step)``

Returns the exact same list[dict] format as ``visual_check.check_images``::

    [{"file": rel, "status": "ok"|"needs_revision"|"insufficient_data"|"skipped",
      "issues": [...], "recommended_action": "..."}]

so ``pi_harness.py`` needs no changes.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Tuple

from PIL import Image

from .config import ValidationConfig, get_validation_config
from .tools import (
    InspectionSession,
    TOOL_REGISTRY,
    dispatch_tool,
    finish as tool_finish,
)

logger = logging.getLogger(__name__)

import logging as _logging_dv
_dvlog_agent = _logging_dv.getLogger("geollm.debug_vision")
_DEBUG_VISION_AGENT = os.environ.get("GEOLLM_DEBUG_VISION", "") == "1"


def _dva(msg: str, *args) -> None:
    if _DEBUG_VISION_AGENT:
        _dvlog_agent.debug(msg, *args)


# ---------------------------------------------------------------------------
# Constants (all overridable via env)
# ---------------------------------------------------------------------------

_DEFAULT_MAX_TURNS: int = 20
_DEFAULT_OVERVIEW_MAX_PX: int = 768
_MAX_PNGS_PER_RUN: int = 3   # mirrors legacy visual_check.py cap


# ---------------------------------------------------------------------------
# Raster discovery
# ---------------------------------------------------------------------------

_MAP_SUFFIXES = ("_map", "_plot", "_viz", "_output", "_result", "_classified")


def _discover_rasters(png_path: Path, output_dir: Path) -> Tuple[List[Path], List[Path]]:
    """Locate input and output GeoTIFFs associated with a PNG map.

    Search order (output rasters):
    1. ``output_dir/<png_stem>.tif[f]``
    2. Strip known trailing tokens from stem, then try ``.tif[f]``
    3. All ``*.tif``/``*.tiff`` in ``output_dir`` sorted by mtime (newest first)
    4. Repeat step 3 for ``output_dir.parent``

    Input rasters are identified as any ``*.tif``/``*.tiff`` in ``output_dir``
    or its parent that is NOT in the output set.

    Returns
    -------
    (input_rasters, output_rasters) — each up to 3 paths, may be empty.
    """
    stem = png_path.stem
    candidates: List[Path] = []

    # 1 & 2 — exact and stripped stem matches
    for try_stem in _stem_variants(stem):
        for ext in (".tif", ".tiff"):
            p = output_dir / (try_stem + ext)
            if p.is_file():
                candidates.append(p)

    # 3 — scan output_dir
    candidates.extend(_tifs_by_mtime(output_dir))

    # 4 — scan parent
    if output_dir.parent != output_dir:
        candidates.extend(_tifs_by_mtime(output_dir.parent))

    # Deduplicate while preserving order
    seen: set[Path] = set()
    unique: List[Path] = []
    for p in candidates:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            unique.append(p)

    output_rasters = unique[:3]
    # For now treat all discovered TIFFs as both input and output candidates;
    # a future version can use naming heuristics to distinguish them.
    input_rasters = unique[:3]
    return input_rasters, output_rasters


def _stem_variants(stem: str) -> List[str]:
    """Return the original stem plus versions with known map-suffixes stripped."""
    variants = [stem]
    lower = stem.lower()
    for sfx in _MAP_SUFFIXES:
        if lower.endswith(sfx):
            variants.append(stem[: -len(sfx)])
            break
    return variants


def _tifs_by_mtime(directory: Path) -> List[Path]:
    """Return up to 3 GeoTIFF files in *directory* sorted by mtime descending."""
    try:
        tifs = [p for p in directory.iterdir()
                if p.suffix.lower() in (".tif", ".tiff") and p.is_file()]
        tifs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return tifs[:3]
    except (OSError, PermissionError):
        return []


# ---------------------------------------------------------------------------
# Overview thumbnail
# ---------------------------------------------------------------------------

def _make_overview(png_path: Path, feedback_dir: Path, max_px: int) -> Path:
    """Downscale *png_path* to at most *max_px* on the longest side.

    Saves to ``feedback_dir/thumbs/overview_<stem>.png`` and returns that path.
    """
    out = feedback_dir / "thumbs" / f"overview_{png_path.stem}.png"
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        with Image.open(png_path) as img:
            img_rgb = img.convert("RGB")
            w, h = img_rgb.size
            if max(w, h) > max_px:
                scale = max_px / max(w, h)
                new_w, new_h = max(1, int(w * scale)), max(1, int(h * scale))
                img_rgb = img_rgb.resize((new_w, new_h), Image.Resampling.LANCZOS)
            img_rgb.save(str(out))
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent: could not create overview thumbnail for %s: %s", png_path, exc)
        # Copy original as fallback
        import shutil
        shutil.copy2(png_path, out)

    return out


# ---------------------------------------------------------------------------
# Tool-call JSON parsing
# ---------------------------------------------------------------------------

_JSON_FENCE_RE = re.compile(
    r"```(?:json)?\s*(\{.*?\})\s*```",
    re.DOTALL | re.IGNORECASE,
)


def _extract_json_objects(text: str):
    """Yield all top-level JSON objects from *text* by brace-counting."""
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start != -1:
                yield text[start : i + 1]
                start = -1


def _parse_tool_call(text: str) -> Optional[Dict[str, Any]]:
    """Extract the first ``{"tool": ..., "args": {...}}`` object from *text*.

    Tries fenced JSON blocks first, then bare top-level JSON objects.
    Returns ``None`` if nothing parseable is found.
    """
    # 1. Fenced ```json ... ``` block
    for m in _JSON_FENCE_RE.finditer(text):
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict) and "tool" in obj:
                return obj
        except json.JSONDecodeError:
            continue

    # 2. Any JSON object in the text (handles nested braces correctly)
    for raw in _extract_json_objects(text):
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict) and "tool" in obj:
                return obj
        except json.JSONDecodeError:
            continue

    return None


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------

_TOOL_SUMMARIES: Dict[str, str] = {
    "make_grid": 'make_grid(rows, cols) → divide image into N×M tiles. Call first.',
    "crop": 'crop(tile_id?, bbox_norm?, zoom_level=1) → get hi-res comparison image for a tile.',
    "get_stats": 'get_stats(tile_id?, bbox_norm?) → pixel-exact counts/min/max/std from GeoTIFF. Use instead of estimating.',
    "get_source_info": 'get_source_info() → sensor metadata (CRS, resolution, bands, date).',
    "mark_result": (
        'mark_result(tile_id, verdict, rationale, defect_category?, confidence?, defect_bbox?) '
        '→ record verdict. verdict ∈ {correct, wrong, unsure, not_verifiable}.'
    ),
    "report_insufficient_data": (
        'report_insufficient_data(reason, evidence_tile_id?, missing_data_fraction?) '
        '→ abort — raw data quality too poor. NOT a code bug.'
    ),
    "finish": 'finish(summary) → aggregate all verdicts and end validation.',
}


def _build_system_prompt(task_name: str, task_description: str, image_name: str) -> str:
    tool_lines = "\n".join(f"  • {v}" for v in _TOOL_SUMMARIES.values())
    return (
        f"You are a geospatial map validation AI for task: {task_name!r}.\n"
        f"Description: {task_description}\n"
        f"Image under inspection: {image_name}\n\n"
        "RULES:\n"
        "1. Drive inspection by calling tools one at a time.\n"
        "2. NEVER calculate counts, percentages, or areas yourself — always call get_stats().\n"
        "3. Start with make_grid() to plan your inspection, then crop() each tile, then mark_result().\n"
        "4. When data quality is too poor to judge, call report_insufficient_data() instead of guessing.\n"
        "5. Call finish() when all important tiles have a verdict.\n\n"
        f"Available tools:\n{tool_lines}\n\n"
        "Respond ONLY with a ```json ... ``` block:\n"
        '{"tool": "<name>", "args": {<arguments as JSON>}}\n\n'
        "Do not include any other text outside the JSON block."
    )


# ---------------------------------------------------------------------------
# Session → legacy verdict conversion
# ---------------------------------------------------------------------------

def _session_to_verdict(session: InspectionSession, rel: str) -> Dict[str, Any]:
    """Convert a finished InspectionSession to the legacy check_images() dict."""
    if session.aborted:
        return {
            "file": rel,
            "status": "insufficient_data",
            "issues": [session.abort_reason],
            "recommended_action": (
                "Input data quality is too poor to validate — "
                "check cloud cover, nodata fraction, and acquisition date."
            ),
        }

    if not session.finish_called:
        # Budget exhausted without finish — treat as skipped
        return {
            "file": rel,
            "status": "skipped",
            "issues": ["Validation step budget exhausted before a verdict was reached."],
            "recommended_action": "Increase GEOLLM_VALIDATION_STEP_BUDGET or inspect manually.",
        }

    wrong = [t for t in session.tiles.values() if t.verdict == "wrong"]
    review = [t for t in session.tiles.values() if t.verdict in ("unsure", "needs_review")]

    if wrong:
        status = "needs_revision"
        issues = [
            f"Tile {t.tile_id} [{t.defect_category or 'defect'}]: {t.rationale}"
            for t in wrong
        ]
        recommended = (
            f"{len(wrong)} tile(s) marked wrong. "
            + " | ".join(
                t.defect_category or "check output" for t in wrong
            )
        )
    elif review:
        status = "needs_revision"
        issues = [f"Tile {t.tile_id}: {t.rationale} ({t.verdict})" for t in review]
        recommended = f"{len(review)} tile(s) require manual review ({', '.join(set(t.verdict for t in review))})."
    else:
        status = "ok"
        issues = []
        recommended = (
            f"Validation passed. {session.verified_area_pct():.0f}% of area verified."
        )

    return {
        "file": rel,
        "status": status,
        "issues": issues,
        "recommended_action": recommended,
    }


# ---------------------------------------------------------------------------
# Single-image agentic loop
# ---------------------------------------------------------------------------

def _run_agentic_loop(
    rel: str,
    png_path: Path,
    output_dir: Path,
    feedback_dir: Path,
    task: Any,
    on_step: Callable,
    cfg: ValidationConfig,
    llm_call: Callable[[str, List[str]], str],
    max_turns: int,
) -> Dict[str, Any]:
    """Run the multi-turn tool-call loop for one PNG.

    Parameters
    ----------
    llm_call:
        Callable with signature ``(prompt, image_paths) -> str``.
        Injected so tests can mock without touching the network.

    Returns
    -------
    Legacy verdict dict (same shape as ``check_images()`` list items).
    """
    input_rasters, output_rasters = _discover_rasters(png_path, output_dir)

    session = InspectionSession(
        image_name=rel,
        output_dir=output_dir,
        input_raster_paths=input_rasters,
        output_raster_paths=output_rasters,
        png_map_path=png_path,
        feedback_dir=feedback_dir,
        cfg=cfg,
    )

    overview_max_px: int = int(
        os.environ.get("GEOLLM_VALIDATION_OVERVIEW_PX", str(_DEFAULT_OVERVIEW_MAX_PX))
    )
    overview_path = _make_overview(png_path, feedback_dir, overview_max_px)

    system_prompt = _build_system_prompt(
        task_name=getattr(task, "name", "geospatial analysis"),
        task_description=getattr(task, "description", ""),
        image_name=rel,
    )

    # First turn includes the overview image; subsequent turns are text-only
    turn_prompt = system_prompt
    image_paths_for_turn: List[str] = [str(overview_path)]
    conversation: List[Dict[str, str]] = []

    for turn_idx in range(max_turns):
        if session.finish_called or session.aborted:
            break
        if session.budget_exceeded():
            tool_finish(session, summary="Step budget exhausted — auto-closed.")
            break

        _t0 = time.time()
        if _DEBUG_VISION_AGENT:
            _dva(
                "[agent turn %d] frame=%r prompt_len=%d image_count=%d prompt_preview=%r",
                turn_idx, rel, len(turn_prompt), len(image_paths_for_turn), turn_prompt[:200],
            )
        try:
            raw_response = llm_call(turn_prompt, image_paths_for_turn)
        except Exception as exc:  # noqa: BLE001
            logger.warning("agent: LLM call failed on turn %d for %s: %s", turn_idx, rel, exc)
            return {
                "file": rel,
                "status": "skipped",
                "issues": [f"Vision model call failed: {exc}"],
                "recommended_action": "Check GEOLLM_VISION_MODEL and OPENROUTER_API_KEY.",
            }

        if _DEBUG_VISION_AGENT:
            _elapsed = time.time() - _t0
            _dva(
                "[agent turn %d] frame=%r elapsed=%.2fs response_len=%d response_preview=%r",
                turn_idx, rel, _elapsed, len(raw_response), raw_response[:200],
            )
        conversation.append({"role": "assistant", "content": raw_response})

        parsed = _parse_tool_call(raw_response)
        if _DEBUG_VISION_AGENT:
            if parsed:
                _dva("[agent turn %d] frame=%r tool_call=%r args=%r", turn_idx, rel, parsed.get("tool"), parsed.get("args"))
            else:
                _dva("[agent turn %d] frame=%r no tool call parsed", turn_idx, rel)
        if parsed is None:
            logger.warning(
                "agent: turn %d — no tool call found in response for %s; finishing.",
                turn_idx,
                rel,
            )
            # Give the model one more chance with an explicit nudge
            turn_prompt = (
                "Your previous response did not contain a valid ```json ...``` tool call block. "
                "Reply ONLY with a JSON block: {\"tool\": \"<name>\", \"args\": {...}}"
            )
            image_paths_for_turn = []
            continue

        tool_name = parsed.get("tool", "")
        tool_args = parsed.get("args", {})
        if not isinstance(tool_args, dict):
            tool_args = {}

        result = dispatch_tool(session, tool_name, tool_args)

        # Forward any pending SSE events to the harness
        for ev in session.drain_events():
            on_step(ev)

        # Build next turn: show the tool result as user context
        turn_prompt = f"Tool result for {tool_name!r}:\n```json\n{json.dumps(result, default=str)}\n```\nContinue inspection. Reply with the next tool call."
        # Keep overview image attached so vision model doesn't lose visual context on multi-turn tool calls
        image_paths_for_turn = [str(overview_path)]

    # Ensure session is terminated even if loop exhausted without finish/abort
    if not session.finish_called and not session.aborted:
        tool_finish(session, summary="Max turns reached — auto-closed.")
        for ev in session.drain_events():
            on_step(ev)

    # ---- Phase 4: consensus re-verification --------------------------------
    # Only run when there are flagged tiles and consensus is enabled (default on).
    _consensus_enabled = os.environ.get("GEOLLM_CONSENSUS_ENABLED", "1") != "0"
    if _consensus_enabled and not session.aborted and session.finish_called:
        _flagged = [t for t in session.tiles.values()
                    if t.verdict in ("wrong", "unsure")]
        if _flagged:
            from .consensus import re_verify_flagged_tiles
            logger.info(
                "agent: running consensus re-verification on %d flagged tile(s) for %s",
                len(_flagged),
                rel,
            )
            re_verify_flagged_tiles(session, llm_call_fn=llm_call)
            for ev in session.drain_events():
                on_step(ev)
            # Emit one SSE event so the frontend knows consensus ran
            on_step({
                "type": "vision_consensus_done",
                "image": rel,
                "re_verified": len(_flagged),
                "tiles": {
                    tid: t.verdict
                    for tid, t in session.tiles.items()
                    if tid in {f.tile_id for f in _flagged}
                },
            })
            try:
                out = session.feedback_dir / f"validation_{session.image_name.replace('/', '_')}.json"
                if out.parent.is_dir():
                    out.write_text(json.dumps(session.to_summary_dict(), indent=2, default=str), encoding="utf-8")
            except Exception:
                pass
    # ------------------------------------------------------------------------

    return _session_to_verdict(session, rel)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def validate_artifacts(
    task: Any,
    output_dir: Any,
    pngs: List[str],
    feedback_dir: Any,
    on_step: Optional[Callable] = None,
    cfg: Optional[ValidationConfig] = None,
) -> List[Dict[str, Any]]:
    """Agentic drop-in replacement for ``visual_check.check_images()``.

    Activated when ``GEOLLM_VALIDATION_MODE=agentic``.  Returns the same
    ``list[dict]`` format so ``pi_harness.py`` needs zero changes.

    Parameters
    ----------
    task:
        Object with ``.name`` and ``.description`` attributes (same as
        the ``SimpleNamespace`` passed by ``pi_harness``).
    output_dir:
        Directory that holds the sub-agent's output files.
    pngs:
        List of relative PNG paths (relative to *output_dir*).
    feedback_dir:
        Directory where feedback artefacts are written.
    on_step:
        SSE event callback, signature ``(event_dict) -> None``.
    cfg:
        ``ValidationConfig`` instance; defaults to ``get_validation_config()``.
    """
    # Lazy import so tests that mock llm don't trigger real network calls
    from harness import llm as _llm

    _cfg = cfg or get_validation_config()
    _on_step = on_step or (lambda ev: None)
    _output_dir = Path(output_dir)
    _feedback_dir = Path(feedback_dir)
    _feedback_dir.mkdir(parents=True, exist_ok=True)

    # Set up debug-vision file handler (gated by GEOLLM_DEBUG_VISION=1)
    if os.environ.get("GEOLLM_DEBUG_VISION", "") == "1":
        import logging as _lmod
        _dv_logger = _lmod.getLogger("geollm.debug_vision")
        if not _dv_logger.handlers:
            _dv_logger.setLevel(_lmod.DEBUG)
            # Console handler
            _ch = _lmod.StreamHandler()
            _ch.setLevel(_lmod.DEBUG)
            _dv_logger.addHandler(_ch)
        # File handler in feedback dir (survives after the run)
        _dv_log_path = _feedback_dir / "debug_vision.log"
        _fh = _lmod.FileHandler(str(_dv_log_path), encoding="utf-8")
        _fh.setLevel(_lmod.DEBUG)
        _fh.setFormatter(_lmod.Formatter("%(asctime)s %(message)s"))
        _dv_logger.addHandler(_fh)
        _dv_logger.propagate = False
        _dvlog_agent.debug(
            "[debug_vision] Logging enabled — writing to %s", _dv_log_path
        )

    max_turns: int = int(
        os.environ.get("GEOLLM_VALIDATION_MAX_TURNS", str(_DEFAULT_MAX_TURNS))
    )

    # Mirror the legacy cap of 3 PNGs per run
    target_pngs = pngs[:_MAX_PNGS_PER_RUN]
    total = len(target_pngs)
    verdicts: List[Dict[str, Any]] = []

    if not _llm.vision_available():
        return [
            {
                "file": rel,
                "status": "skipped",
                "issues": [],
                "recommended_action": "No vision model configured (set GEOLLM_VISION_MODEL).",
            }
            for rel in target_pngs
        ]

    for i, rel in enumerate(target_pngs):
        png_path = _output_dir / rel

        _on_step({
            "type": "vision_check",
            "image": rel,
            "index": i + 1,
            "total": total,
            "state": "started",
            "mode": "agentic",
        })

        if not png_path.is_file():
            verdict = {
                "file": rel,
                "status": "skipped",
                "issues": [f"PNG file not found: {rel}"],
                "recommended_action": "Verify the sub-agent wrote the expected output file.",
            }
        else:
            verdict = _run_agentic_loop(
                rel=rel,
                png_path=png_path,
                output_dir=_output_dir,
                feedback_dir=_feedback_dir,
                task=task,
                on_step=_on_step,
                cfg=_cfg,
                llm_call=_llm.chat_vision,
                max_turns=max_turns,
            )

        verdicts.append(verdict)

        _on_step({
            "type": "vision_check",
            "image": rel,
            "index": i + 1,
            "total": total,
            "state": "done",
            "verdict": verdict["status"],
            "text": "; ".join(verdict["issues"]) if verdict["issues"] else verdict["status"],
            "mode": "agentic",
        })

    # Persist combined feedback file (mirrors legacy visual_check.py behaviour)
    try:
        feedback_path = _feedback_dir / "visual.json"
        feedback_path.write_text(json.dumps(verdicts, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent: could not write visual.json: %s", exc)

    return verdicts
