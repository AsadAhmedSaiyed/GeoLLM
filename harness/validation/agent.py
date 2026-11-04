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

# The single allowed nudge when the model replies without a tool call.
NUDGE_PROMPT = (
    "Your previous response did not contain a valid ```json ...``` tool call block. "
    "Reply ONLY with a JSON block: {\"tool\": \"<name>\", \"args\": {...}}"
)


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
    # Model could not emit a parseable tool call (prose, call_tool, tool_code).
    # This must never be reported as "ok".
    if session.not_verified:
        return {
            "file": rel,
            "status": "not_verified",
            "issues": [session.not_verified_reason or "Model did not emit a parseable tool call."],
            "recommended_action": "Re-run validation; check model provider and prompt.",
        }

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
        # 0% verified MUST NOT be "ok".  This happens when the model calls
        # finish() without ever marking any tile (e.g. finish() on turn 1).
        if session.verified_area_pct() == 0.0:
            status = "not_verified"
            issues = ["No tiles were inspected before finish() was called."]
            recommended = "Re-run validation; the model completed without inspecting any region."
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

def _emit_stopped(on_step: Callable, image: str, reason: str, detail: str) -> None:
    """Emit a vision_stopped SSE event so the UI can show a stop banner.

    reason is one of: insufficient_data | not_verified | rate_limited
    """
    try:
        on_step({
            "type": "vision_stopped",
            "image": image,
            "reason": reason,
            "detail": (detail or "")[:500],
        })
    except Exception:
        pass


# ---------------------------------------------------------------------------

def _run_agentic_loop(
    rel: str,
    png_path: Path,
    output_dir: Path,
    feedback_dir: Path,
    task: Any,
    on_step: Callable,
    cfg: ValidationConfig,
    llm_call: Callable[[List[Dict[str, Any]], List[str]], str],
    max_turns: int,
) -> Dict[str, Any]:
    """Run the multi-turn tool-call loop for one PNG.

    Parameters
    ----------
    llm_call:
        Callable with signature ``(conversation, image_paths) -> str``.
        ``conversation`` is a list of {"role": "user"|"assistant", "content": ...}
        messages (the full history).  ``image_paths`` are attached to the
        last user message.  Injected so tests can mock without touching
        the network.

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

    # The conversation is the REAL multi-turn history.  It is sent in full on
    # every turn so the model remembers make_grid / crop / mark_result from
    # earlier turns.  (The previous implementation built this list and then
    # never sent it — each turn was a one-shot chat_vision call.)
    conversation: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": (
            f"Image under inspection: {rel}\n"
            "Begin by calling make_grid() to plan your inspection."
        )},
    ]
    # Images attach only to the turn that needs them: the overview on turn
    # 0, and a crop after the crop() tool returns.  The overview is NOT
    # re-attached on every turn — that burned ~300 KB of image payload per
    # turn and was one cause of the 429 storm.
    image_paths_for_turn: List[str] = [str(overview_path)]
    nudges_used = 0
    max_nudges = 1

    for turn_idx in range(max_turns):
        if session.finish_called or session.aborted:
            break
        if session.budget_exceeded():
            tool_finish(session, summary="Step budget exhausted — auto-closed.")
            break

        # Live progress so the UI can show tiles-done / total and steps / budget.
        on_step({
            "type": "vision_progress",
            "image": rel,
            "index": turn_idx + 1,
            "total": max_turns,
            "steps_used": session.steps_used,
            "budget": session.cfg.step_budget,
            "tiles_checked": len(session.tiles),
            "tiles_marked": sum(
                1 for t in session.tiles.values() if t.verdict is not None
            ),
        })

        _t0 = time.time()
        if _DEBUG_VISION_AGENT:
            _dva(
                "[agent turn %d] frame=%r n_messages=%d image_count=%d",
                turn_idx, rel, len(conversation), len(image_paths_for_turn),
            )
        try:
            raw_response = llm_call(conversation, image_paths_for_turn)
        except Exception as exc:  # noqa: BLE001
            # A 429 that survived retry, or any other provider failure, must
            # NOT be reported as "ok".  Surface it as not_verified.
            logger.warning("agent: LLM call failed on turn %d for %s: %s", turn_idx, rel, exc)
            session.not_verified = True
            session.not_verified_reason = f"LLM call failed: {exc}"
            _emit_stopped(on_step, rel, "rate_limited" if "429" in str(exc) else "not_verified",
                          str(exc))
            break

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

        # ---- Unparseable reply: at most ONE nudge, then not_verified ----
        if parsed is None:
            if nudges_used < max_nudges:
                nudges_used += 1
                logger.warning(
                    "agent: turn %d — no tool call found for %s; nudging once.",
                    turn_idx, rel,
                )
                conversation.append({"role": "user", "content": NUDGE_PROMPT})
                image_paths_for_turn = []
                continue
            # Second parse failure: bail out as not_verified rather than
            # burning the remaining 20-turn budget on a hallucinated
            # ``call_tool`` / ``tool_code`` loop.
            logger.warning(
                "agent: turn %d — still no tool call for %s; marking not_verified.",
                turn_idx, rel,
            )
            session.not_verified = True
            session.not_verified_reason = (
                "Model did not emit a parseable tool call after a nudge."
            )
            _emit_stopped(on_step, rel, "not_verified", session.not_verified_reason)
            break

        tool_name = parsed.get("tool", "")
        tool_args = parsed.get("args", {})
        if not isinstance(tool_args, dict):
            tool_args = {}

        # Reject hallucinated tools (e.g. gemini's ``call_tool`` /
        # ``tool_code`` replies) explicitly instead of silently dispatching
        # them and feeding the "Unknown tool" error back as a new turn.
        if tool_name not in TOOL_REGISTRY:
            logger.warning(
                "agent: turn %d — unknown tool %r requested for %s; marking not_verified.",
                turn_idx, tool_name, rel,
            )
            session.not_verified = True
            session.not_verified_reason = (
                f"Model requested unknown tool {tool_name!r}."
            )
            _emit_stopped(on_step, rel, "not_verified", session.not_verified_reason)
            break

        result = dispatch_tool(session, tool_name, tool_args)

        # Forward any pending SSE events to the harness
        for ev in session.drain_events():
            on_step(ev)

        # Build next turn: show the tool result as user context.
        # If crop() produced an image, attach it as a REAL image to this
        # message (the model then actually sees the comparison panels).
        crop_image = result.get("image_path") if isinstance(result, dict) else None
        image_paths_for_turn = [crop_image] if crop_image else []

        conversation.append({"role": "user", "content": (
            f"Tool result for {tool_name!r}:\n```json\n"
            f"{json.dumps(result, default=str)}\n```\n"
            "Continue inspection. Reply with the next tool call."
        )})

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
                llm_call=_llm.chat_vision_multi,
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
