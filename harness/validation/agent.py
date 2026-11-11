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
from typing import Any, Callable, Dict, List, Optional, Tuple, Sequence

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
_DEFAULT_OVERVIEW_MAX_PX: int = 1600
_MAX_PNGS_PER_RUN: int = int(os.environ.get("GEOLLM_VALIDATION_MAX_IMAGES", "16"))

# The single allowed nudge when the model replies without a tool call.
NUDGE_PROMPT = (
    "Your previous response did not contain a valid ```json ...``` tool call block. "
    "Reply ONLY with a JSON block: {\"tool\": \"<name>\", \"args\": {...}}"
)


# ---------------------------------------------------------------------------
# Raster discovery
# ---------------------------------------------------------------------------

_MAP_SUFFIXES = ("_map", "_plot", "_viz", "_output", "_result", "_classified")


def _extract_date_tokens(text: str) -> Tuple[set[str], set[str]]:
    """Extract normalized YYYY-MM[-DD] and YYYY date tokens even when bounded by underscores."""
    s = text.lower()
    raw_dates = re.findall(r"(?<!\d)\d{4}[-_]\d{2}(?:[-_]\d{2})?(?!\d)", s)
    norm_dates = {d.replace("_", "-") for d in raw_dates}
    # Also include YYYY-MM prefix for any YYYY-MM-DD token so month-level matching works
    for d in list(norm_dates):
        if len(d) == 10:
            norm_dates.add(d[:7])
    years = set(re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", s))
    return norm_dates, years


def _rank_rasters(
    rasters: Sequence[Path],
    target_path: Path,
    context_keywords: Sequence[str] = (),
) -> List[Path]:
    """Sort candidate raster paths by relevance to target_path (dates and keywords)."""
    if not rasters:
        return []

    stem = target_path.stem.lower()
    date_matches, years = _extract_date_tokens(stem)
    months = {
        "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
        "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12",
    }
    target_months = {m for m in months if m in stem}

    def score(p: Path) -> int:
        s = p.stem.lower()
        pts = 0

        # Exact stem match or variant
        if s == stem or s in _stem_variants(stem) or stem in _stem_variants(s):
            pts += 200

        p_dates, p_years = _extract_date_tokens(s)

        # Full / YYYY-MM date match
        if date_matches and (date_matches & p_dates):
            pts += 100

        # Year match
        if years and (years & p_years):
            pts += 40

        # Month match
        for m in target_months:
            if m in s or f"-{months[m]}" in s.replace("_", "-"):
                pts += 30

        # Change/diff match
        change_words = ("change", "diff", "transition", "loss", "gain", "comparison")
        has_change_kw = any(w in stem for w in change_words) or any(
            cw in kw.lower() for kw in context_keywords for cw in change_words
        )
        if has_change_kw and any(w in s for w in change_words):
            pts += 60

        # Common words
        s_tokens = set(re.split(r"[-_.]+", s)) - {"tif", "tiff", "png", "frame", "water", "mask", "aral"}
        stem_tokens = set(re.split(r"[-_.]+", stem)) - {"tif", "tiff", "png", "frame", "water", "mask", "aral"}
        pts += len(s_tokens & stem_tokens) * 10

        return pts

    scored = sorted(enumerate(rasters), key=lambda x: (score(x[1]), -x[0]), reverse=True)
    return [p for _, p in scored]


def _discover_rasters(
    png_path: Path,
    output_dir: Path,
    real_inputs: Optional[Sequence[Path]] = None,
    context_keywords: Sequence[str] = (),
) -> Tuple[List[Path], List[Path]]:
    """Locate input and output GeoTIFFs associated with a PNG map.

    If real_inputs are provided (from user upload / task facts), they are used
    directly for input_rasters.

    Search order (output rasters):
    1. ``png_path.parent/<png_stem>.tif[f]`` and ``output_dir/<png_stem>.tif[f]``
    2. Strip known trailing tokens from stem, then try ``.tif[f]``
    3. All ``*.tif``/``*.tiff`` in ``png_path.parent``, ``output_dir``, and ``attempt_*/outputs``
    4. Repeat step 3 for ``output_dir.parent``

    Returns
    -------
    (input_rasters, output_rasters) — ranked by relevance to *png_path*.
    """
    stem = png_path.stem
    candidates: List[Path] = []

    search_dirs: List[Path] = []
    if png_path.parent.is_dir() and png_path.parent.name != "thumbs":
        search_dirs.append(png_path.parent)
    if output_dir.is_dir() and output_dir not in search_dirs:
        search_dirs.append(output_dir)
    # Also scan attempt_*/outputs inside output_dir (newest attempt first)
    if output_dir.is_dir():
        for ad in sorted(output_dir.glob("attempt_*"), reverse=True):
            out_sub = ad / "outputs"
            if out_sub.is_dir() and out_sub not in search_dirs:
                search_dirs.append(out_sub)

    # 1 & 2 — exact and stripped stem matches across search_dirs
    for sdir in search_dirs:
        for try_stem in _stem_variants(stem):
            for ext in (".tif", ".tiff"):
                p = sdir / (try_stem + ext)
                if p.is_file():
                    candidates.append(p)

    # 3 — scan all search_dirs for GeoTIFFs
    for sdir in search_dirs:
        candidates.extend(_tifs_by_mtime(sdir))

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

    ranked_outputs = _rank_rasters(unique, png_path, context_keywords=context_keywords)
    output_rasters = ranked_outputs[:3]

    if real_inputs:
        valid_inputs = [Path(p) for p in real_inputs if Path(p).is_file()]
        ranked_inputs = _rank_rasters(valid_inputs, png_path, context_keywords=context_keywords)
        input_rasters = ranked_inputs
    else:
        # Heuristic fallback: treat discovered TIFFs as input candidates
        input_rasters = ranked_outputs[:3]

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
    """Return all GeoTIFF files in *directory* sorted by mtime descending."""
    try:
        tifs = [p for p in directory.iterdir()
                if p.suffix.lower() in (".tif", ".tiff") and p.is_file()]
        tifs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return tifs
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


def _build_system_prompt(task_name: str, task_description: str, image_name: str, input_gate_summary: str = "") -> str:
    tool_lines = "\n".join(f"  • {v}" for v in _TOOL_SUMMARIES.values())
    is_3d_or_chart = any(
        kw in image_name.lower()
        for kw in ("3d", "chart", "graph", "timeline", "timeseries", "time_series", "trend", "plot", "hist", "profile")
    )
    extra_guidance = ""
    if is_3d_or_chart:
        extra_guidance = (
            "\nNOTE ON 3D / CHARTS: This image is a 3D visualization or statistical data chart/plot. "
            "Do not expect 2D planimetric GeoTIFF pixel alignment. Inspect visual readability, "
            "axes, labels, and rendering quality, and call mark_result(verdict='correct' or 'not_verifiable').\n"
        )

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
        "VALIDATION GUIDELINES:\n"
        "• Single Deliverable Scope: You are inspecting ONLY the single file named in 'Image under inspection'. "
        "If the user's task asks for multiple outputs (e.g., a regional map, a trend chart, and a time-lapse animation), "
        "each output is saved as a separate file. NEVER mark this image 'wrong' because other requested outputs "
        "(like a trend chart or animation) are not inside this single image.\n"
        "• Diagnostic Panel Wrapper: When you call crop(), our verification tool automatically generates a 2x2 or side-by-side "
        "inspection composite showing 'Input Crop', 'Output GeoTIFF', 'Deliverable', and 'Discrepancy / Overlay' so you can compare them. "
        "The actual user deliverable on disk is ONLY the 'Deliverable' panel (and the initial overview image). "
        "NEVER mark an image 'wrong' for 'being a diagnostic panel showing input crop, output GeoTIFF, and discrepancy'!\n"
        "• Overview vs. Zoomed Tile Inspection:\n"
        "  - The full overview image allows verifying global elements (figure title, legend, scale bar, layout).\n"
        "  - However, macroscopic downscaling can obscure local misclassifications, boundary shifts, or pixel artifacts. "
        "When validating spatial maps, reason carefully about whether fine-scale inspection is needed to verify local accuracy. "
        "Divide the image with make_grid() and use crop(tile_id) to zoom in at full native resolution on critical regions. "
        "crop() generates an aligned multi-panel diagnostic composite (Input Crop, Output GeoTIFF, Deliverable, and Discrepancy Overlay) to verify ground-truth alignment.\n"
        "  - Full overview: Overall elements (figure title, legend, scale bar, layout) belong to the full image. NEVER mark an individual cropped tile 'wrong' for 'missing legend'; outer titles and legends belong to the overall figure and may be outside the crop. Evaluate whether geographic features in the crop match the reference imagery.\n"
        + extra_guidance +
        f"\nAvailable tools:\n{tool_lines}\n\n"
        "Respond ONLY with a ```json ... ``` block:\n"
        '{"tool": "<name>", "args": {<arguments as JSON>}}\n\n'
        "Do not include any other text outside the JSON block.\n\n"
        f"TASK: {task_description}\n"
        "CHECKLIST: Verify legend present, title present, units labeled, region matches query, dates match query, map type appropriate.\n"
        + (f"INPUT DATA QUALITY: {input_gate_summary}\n" if input_gate_summary else "")
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
    inspected = [t for t in session.tiles.values() if t.verdict is not None]
    not_verifiable = [t for t in inspected if t.verdict == "not_verifiable"]

    if wrong:
        status = "needs_revision"
        grouped: Dict[Tuple[str, str], List[str]] = {}
        for t in wrong:
            cat = t.defect_category or "defect"
            rat = (t.rationale or "").strip()
            grouped.setdefault((cat, rat), []).append(t.tile_id)

        issues = []
        for (cat, rat), tiles in grouped.items():
            prefix = f"Tile {tiles[0]}" if len(tiles) == 1 else f"Tiles {', '.join(tiles)}"
            if rat:
                issues.append(f"{prefix} [{cat}]: {rat}")
            else:
                issues.append(f"{prefix} [{cat}]")

        categories = sorted({t.defect_category for t in wrong if t.defect_category})
        cat_summary = ", ".join(categories) if categories else "check output"
        recommended = f"{len(wrong)} tile(s) marked wrong ({cat_summary})."
    elif review:
        status = "needs_revision"
        grouped_rev: Dict[Tuple[str, str], List[str]] = {}
        for t in review:
            rat = (t.rationale or "").strip()
            ver = t.verdict or "review"
            grouped_rev.setdefault((ver, rat), []).append(t.tile_id)
        issues = [
            f"Tile {tiles[0]} ({ver}): {rat}" if len(tiles) == 1 else f"Tiles {', '.join(tiles)} ({ver}): {rat}"
            if rat else (f"Tile {tiles[0]} ({ver})" if len(tiles) == 1 else f"Tiles {', '.join(tiles)} ({ver})")
            for (ver, rat), tiles in grouped_rev.items()
        ]
        recommended = f"{len(review)} tile(s) require manual review ({', '.join(sorted(set(t.verdict for t in review)))})."
    elif not inspected:
        # 0% verified MUST NOT be "ok".  This happens when the model calls
        # finish() without ever marking any tile (e.g. finish() on turn 1).
        status = "not_verified"
        issues = ["No tiles were inspected before finish() was called."]
        recommended = "Re-run validation; the model completed without inspecting any region."
    elif not_verifiable and len(not_verifiable) == len(inspected):
        # All inspected tiles were marked not_verifiable (e.g. 3D perspective animation, chart, or unreferenced raster)
        is_non_map = any(kw in rel.lower() for kw in ("3d", "chart", "graph", "timeline", "anim", "plot", "frame"))
        status = "ok" if is_non_map else "not_verified"
        issues = [f"Tile {t.tile_id}: {t.rationale}" for t in not_verifiable]
        recommended = (
            "Visual inspection noted non-standard/3D cartography: "
            + "; ".join(t.rationale for t in not_verifiable if t.rationale)[:200]
            if is_non_map else
            "Tiles could not be verified against reference rasters: "
            + "; ".join(t.rationale for t in not_verifiable if t.rationale)[:200]
        )
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
    input_files: Optional[Sequence[Union[str, Path]]] = None,
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
    real_inputs = [Path(p) for p in (input_files or getattr(task, "input_files", []) or [])]
    ctx_words: List[str] = []
    if task:
        if getattr(task, "name", None):
            ctx_words.append(str(task.name))
        if getattr(task, "description", None):
            ctx_words.extend(str(task.description).split())
        if getattr(task, "expected_outputs", None):
            ctx_words.extend(str(task.expected_outputs).split())

    input_rasters, output_rasters = _discover_rasters(
        png_path, output_dir, real_inputs=real_inputs, context_keywords=ctx_words
    )

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
        input_gate_summary=getattr(task, "input_gate_summary", ""),
    )

    # Check image resolution to guide optimal inspection
    try:
        from PIL import Image as _PILImage
        with _PILImage.open(png_path) as _im:
            _img_w, _img_h = _im.size
    except Exception:
        _img_w, _img_h = 1000, 1000

    _initial_user_msg = (
        f"Image under inspection: {rel} ({_img_w}×{_img_h} px).\n"
        "An overview of this deliverable is attached.\n"
        "1. Examine the overview for global presentation (title, legend/colorbar, spatial coverage, and overall validity).\n"
        "2. Reason about spatial complexity: Determine whether the overview alone gives you enough visual resolution to verify data accuracy, or whether fine-scale features (boundaries, classification transitions, localized artifacts) require closer inspection.\n"
        "3. Call make_grid(rows, cols) to set up your inspection plan:\n"
        "   - If the macroscopic overview is fully sufficient to judge the entire deliverable with certainty, call make_grid(rows=1, cols=1).\n"
        "   - If the task involves localized spatial variations, classifications, or boundaries that require closer verification, divide into sub-tiles (e.g. make_grid(rows=2, cols=2)).\n"
        "4. When multiple tiles exist, call crop(tile_id) to zoom in and inspect the full-resolution diagnostic comparison panel for each tile, then mark_result(tile_id, ...).\n"
        "5. Conclude your validation by calling finish(summary=...)."
    )

    # The conversation is the REAL multi-turn history.  It is sent in full on
    # every turn so the model remembers make_grid / crop / mark_result from
    # earlier turns.  (The previous implementation built this list and then
    # never sent it — each turn was a one-shot chat_vision call.)
    conversation: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": _initial_user_msg},
    ]
    # Images attach only to the turn that needs them: the overview on turn
    # 0, and a crop after the crop() tool returns.  The overview is NOT
    # re-attached on every turn — that burned ~300 KB of image payload per
    # turn and was one cause of the 429 storm.
    image_paths_for_turn: List[str] = [str(overview_path)]
    nudges_used = 0
    max_nudges = 1

    for turn_idx in range(max_turns):
        run_root = feedback_dir.parent if feedback_dir else output_dir
        if (run_root / "cancelled.flag").exists():
            session.not_verified = True
            session.not_verified_reason = "Cancelled by user"
            _emit_stopped(on_step, rel, "not_verified", "Cancelled by user")
            break
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

        # Strip binary/base64 payloads and host paths before JSON-serializing
        # into the LLM text message so they never blow up the text token budget.
        prompt_result = (
            {k: v for k, v in result.items() if k not in ("image_b64", "image_path")}
            if isinstance(result, dict)
            else result
        )
        crop_reminder = ""
        if tool_name == "crop" and isinstance(result, dict) and result.get("ok"):
            tid = result.get("tile_id", "tile")
            crop_reminder = (
                f"\nNOTE FOR TILE {tid}: You are looking at a cropped sub-region. "
                "The legend, overall title, and outer margins belong to the full figure overview. "
                "DO NOT mark this tile wrong for missing legends, sliced titles, or margin whitespace. "
                "Evaluate ONLY whether the geographic features in this crop match the satellite reference."
            )
        conversation.append({"role": "user", "content": (
            f"Tool result for {tool_name!r}:\n```json\n"
            f"{json.dumps(prompt_result, default=str)}\n```"
            f"{crop_reminder}\n"
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
    input_files: Optional[Sequence[Union[str, Path]]] = None,
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

    # Prioritize primary map deliverables (e.g. map.png, *change*, *result*) over intermediate frames
    def _priority(p: str) -> int:
        name = Path(p).name.lower()
        if name == "map.png":
            return 0
        if any(w in name for w in ("change", "result", "classified", "water_change", "overview", "final")):
            return 1
        if any(w in name for w in ("timeseries", "chart", "timeline", "plot", "graph")):
            return 2
        if name.endswith(".gif"):
            return 3
        # Deprioritize internal helper / debug frames
        if any(w in name for w in ("base_frame", "animation_frame", "frame_", "thumb", "mask_", "source_", "temp_", "slice_")):
            return 5
        if name.endswith((".png", ".jpg", ".jpeg")):
            return 4
        return 6

    sorted_pngs = sorted(pngs, key=_priority)
    target_pngs = sorted_pngs[:_cfg.max_images_per_run]

    def _resolve_gif_frame_dates(gif_p: Path, n_frames: int) -> Dict[int, str]:
        """Resolve observation date tokens for GIF frame indices without hardcoding."""
        frame_dates: Dict[int, str] = {}
        # 1. Check timeline.json in the GIF's directory or attempt_*/outputs
        tl_candidates: List[Path] = []
        if gif_p.parent.is_dir():
            tl_candidates.append(gif_p.parent / "timeline.json")
        if _output_dir.is_dir():
            tl_candidates.append(_output_dir / "timeline.json")
            for ad in sorted(_output_dir.glob("attempt_*"), reverse=True):
                tl_candidates.append(ad / "outputs" / "timeline.json")

        for tl_file in tl_candidates:
            if tl_file.is_file():
                try:
                    tl_data = json.loads(tl_file.read_text(encoding="utf-8"))
                    frames_list = tl_data.get("frames") or []
                    if isinstance(frames_list, list) and frames_list:
                        for idx, fr in enumerate(frames_list):
                            if not isinstance(fr, dict):
                                continue
                            raw_txt = " ".join(
                                str(fr.get(k) or "") for k in ("date", "label", "file")
                            )
                            dts, yrs = _extract_date_tokens(raw_txt)
                            full_dts = sorted((d for d in dts if len(d) >= 7), key=len, reverse=True)
                            if full_dts:
                                frame_dates[idx] = full_dts[0]
                            elif yrs:
                                frame_dates[idx] = sorted(yrs)[0]
                        if frame_dates:
                            return frame_dates
                except Exception:
                    pass

        # 2. Check sorted unique dates from output rasters in gif_p.parent and real input_files
        candidate_files: List[Path] = []
        if gif_p.parent.is_dir():
            candidate_files.extend(
                p for p in gif_p.parent.iterdir()
                if p.is_file() and p.suffix.lower() in (".tif", ".tiff", ".png")
            )
        if input_files:
            candidate_files.extend(Path(p) for p in input_files)

        all_ym_dates: set[str] = set()
        all_years: set[str] = set()
        for cf in candidate_files:
            dts, yrs = _extract_date_tokens(cf.stem)
            # Prefer most specific date token per file (YYYY-MM-DD over YYYY-MM)
            specific = sorted(dts, key=len, reverse=True)
            if specific:
                all_ym_dates.add(specific[0])
            all_years.update(yrs)

        sorted_dates = sorted(all_ym_dates) if all_ym_dates else sorted(all_years)
        if len(sorted_dates) == n_frames:
            for idx, dt in enumerate(sorted_dates):
                frame_dates[idx] = dt
        elif len(sorted_dates) >= 2 and n_frames >= 2:
            frame_dates[0] = sorted_dates[0]
            frame_dates[n_frames - 1] = sorted_dates[-1]
            frame_dates[n_frames // 2] = sorted_dates[len(sorted_dates) // 2]

        return frame_dates

    # Expand GIF files into sampled frames (first, middle, last)
    expanded = []
    source_artifact_map: Dict[str, str] = {}
    for rel in target_pngs:
        if str(rel).lower().endswith(".gif"):
            gif_path = _output_dir / rel
            try:
                from PIL import Image as _PILImage
                gif = _PILImage.open(gif_path)
                n = getattr(gif, "n_frames", 1)
                indices = sorted({0, n // 2, n - 1})
                stem = Path(rel).stem
                frame_date_map = _resolve_gif_frame_dates(gif_path, n)
                for idx in indices:
                    gif.seek(idx)
                    dt_suffix = f"_{frame_date_map[idx]}" if idx in frame_date_map else ""
                    frame_name = f"thumbs/{stem}_frame_{idx}{dt_suffix}.png"
                    frame_path = _feedback_dir / frame_name
                    frame_path.parent.mkdir(parents=True, exist_ok=True)
                    gif.convert("RGB").save(frame_path)
                    exp_rel = str(frame_path.relative_to(_output_dir)) if frame_path.is_relative_to(_output_dir) else frame_name
                    expanded.append(exp_rel)
                    source_artifact_map[exp_rel] = rel
            except Exception as _gif_err:
                logger.warning("GIF frame extraction failed for %s: %s", rel, _gif_err)
                expanded.append(rel)
                source_artifact_map[rel] = rel
        else:
            expanded.append(rel)
            source_artifact_map[rel] = rel

    # Respect the max_images_per_run cap even after expansion (unless single GIF was expanded)
    if len(target_pngs) > 1 and len(expanded) > _cfg.max_images_per_run:
        target_pngs = expanded[:_cfg.max_images_per_run]
    else:
        target_pngs = expanded

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
        run_root = _feedback_dir.parent if _feedback_dir else _output_dir
        if (run_root / "cancelled.flag").exists():
            break

        png_path = _output_dir / rel
        if not png_path.is_file() and (_feedback_dir / rel).is_file():
            png_path = _feedback_dir / rel

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
                input_files=input_files,
            )

        verdict["source_artifact"] = source_artifact_map.get(rel, rel)
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
