"""Phase 2 – Tool Registry & Pixel Execution Backend.

Implements all backend tools callable by the vision model during agentic
validation.  Every number that enters a verdict MUST come from these tools —
the vision model is never allowed to do counting or area arithmetic itself.

Tools
-----
make_grid         Divide output PNG / GeoTIFF into an N×M tile grid.
crop              Extract full-resolution side-by-side comparison for a tile.
get_stats         Pixel-exact area stats from the GeoTIFF (no model math).
get_source_info   Sensor metadata (CRS, resolution, acquisition date, bands).
mark_result       Record the model's judgement for one tile.
report_insufficient_data  Abort validation because raw data quality is too low.
finish            Aggregate all tile marks and emit the final verdict.

All tools are pure Python functions that operate on host disk after Docker has
already exited.  They are completely stateless with respect to the LLM — they
only mutate the InspectionSession passed in by the caller.
"""
from __future__ import annotations

import base64
import dataclasses
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from rasterio.enums import Resampling

from .config import ValidationConfig, get_validation_config
from .geo_crop import (
    ExtractedCrop,
    _transform_bounds,
    extract_png_crop,
    extract_raster_crop,
    generate_side_by_side_comparison,
    render_crop_to_rgb,
)
from .quality_gate import RasterQualityReport, inspect_raster_quality


# ---------------------------------------------------------------------------
# Session state – carries all mutable state across tool calls
# ---------------------------------------------------------------------------

@dataclass
class TileRecord:
    """Tracks a single grid tile and its inspection state."""
    tile_id: str
    bbox_norm: Tuple[float, float, float, float]   # (ymin, xmin, ymax, xmax) normalised
    bounds_geo: Optional[Tuple[float, float, float, float]] = None
    verdict: Optional[str] = None                  # correct|wrong|unsure|not_verifiable
    defect_category: Optional[str] = None
    confidence: float = 0.0
    rationale: str = ""
    defect_bbox: Optional[Tuple[float, float, float, float]] = None
    evidence_crop_path: Optional[str] = None
    stats: Optional[Dict[str, Any]] = None
    step_number: int = 0


@dataclass
class InspectionSession:
    """Mutable state for one complete agentic validation run.

    Created once per `check_images` call and threaded through every tool.
    Serialisable to JSON for disk persistence and SSE forwarding.
    """
    # Inputs
    image_name: str
    output_dir: Path
    input_raster_paths: List[Path]
    output_raster_paths: List[Path]
    png_map_path: Optional[Path]
    feedback_dir: Path
    cfg: ValidationConfig = field(default_factory=get_validation_config)

    # Step accounting
    steps_used: int = 0
    start_time: float = field(default_factory=time.time)

    # Grid
    grid_rows: int = 0
    grid_cols: int = 0
    tiles: Dict[str, TileRecord] = field(default_factory=dict)

    # Terminal state
    aborted: bool = False
    abort_reason: str = ""
    abort_tile_id: Optional[str] = None
    abort_missing_fraction: float = 0.0

    finish_called: bool = False
    finish_summary: str = ""

    # True when the loop bailed out because the model could not emit a
    # parseable tool call (prose, a hallucinated ``call_tool``, a
    # ``tool_code`` reply...).  ``finish()`` cannot express this on its own,
    # so the session carries it and ``_session_to_verdict`` maps it to
    # ``not_verified`` — which must never be reported as ``ok``.
    not_verified: bool = False
    not_verified_reason: str = ""

    # SSE event queue – caller drains this after each tool call
    pending_events: List[Dict[str, Any]] = field(default_factory=list)

    def _emit(self, ev: Dict[str, Any]) -> None:
        self.pending_events.append(ev)

    def drain_events(self) -> List[Dict[str, Any]]:
        evs = list(self.pending_events)
        self.pending_events.clear()
        return evs

    def budget_exceeded(self) -> bool:
        elapsed = time.time() - self.start_time
        return (
            self.steps_used >= self.cfg.step_budget
            or elapsed >= float(60 * 3)  # hard 3-minute wall-clock cap per image
        )

    def verified_area_pct(self) -> float:
        """Fraction of tile area whose verdict is definitive (correct or wrong)."""
        if not self.tiles:
            return 0.0
        definitive = sum(
            1 for t in self.tiles.values()
            if t.verdict in ("correct", "wrong")
        )
        return round(100.0 * definitive / len(self.tiles), 1)

    def to_summary_dict(self) -> Dict[str, Any]:
        return {
            "image": self.image_name,
            "steps_used": self.steps_used,
            "grid": f"{self.grid_rows}x{self.grid_cols}",
            "tiles_total": len(self.tiles),
            "aborted": self.aborted,
            "abort_reason": self.abort_reason,
            "finish_called": self.finish_called,
            "verified_area_pct": self.verified_area_pct(),
            "tiles": {tid: dataclasses.asdict(t) for tid, t in self.tiles.items()},
        }


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _save_thumb(arr_rgb: np.ndarray, path: Path, max_side: int = 512) -> Path:
    """Saves an RGB uint8 array as a thumbnail PNG, returning the path."""
    from PIL import Image
    img = Image.fromarray(arr_rgb)
    h, w = arr_rgb.shape[:2]
    if max(h, w) > max_side:
        scale = max_side / max(h, w)
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(path))
    return path


def _geo_bounds_for_norm(
    bbox_norm: Tuple[float, float, float, float],
    raster_path: Optional[Path],
) -> Optional[Tuple[float, float, float, float]]:
    """Converts normalised image coords to geographic bounds using the companion GeoTIFF."""
    if raster_path is None or not raster_path.is_file():
        return None
    ymin, xmin, ymax, xmax = bbox_norm
    try:
        with rasterio.open(raster_path) as src:
            t = src.transform
            # Top-left corner mapped from pixel fraction
            west = t.c + xmin * src.width * t.a
            north = t.f + ymin * src.height * t.e
            east = t.c + xmax * src.width * t.a
            south = t.f + ymax * src.height * t.e
            return (
                min(west, east),
                min(north, south),
                max(west, east),
                max(north, south),
            )
    except Exception:
        return None


def _anchor_raster(session: InspectionSession) -> Optional[Path]:
    """Returns the best raster to anchor geographic calculations (output first, then input)."""
    for p in session.output_raster_paths:
        if p.is_file():
            return p
    for p in session.input_raster_paths:
        if p.is_file():
            return p
    return None


# ---------------------------------------------------------------------------
# Tool 1: make_grid
# ---------------------------------------------------------------------------

def make_grid(session: InspectionSession, rows: int, cols: int) -> Dict[str, Any]:
    """Divide the output map into an N×M spatial tile grid.

    Returns tile IDs, normalised pixel bounding boxes, and geographic bounds.
    Emits a ``vision_grid`` SSE event.
    """
    session.steps_used += 1
    rows = max(1, min(rows, 6))
    cols = max(1, min(cols, 6))
    session.grid_rows = rows
    session.grid_cols = cols
    session.tiles.clear()

    anchor = _anchor_raster(session)
    tile_records: List[Dict[str, Any]] = []

    for r in range(rows):
        for c in range(cols):
            tid = f"T{r}_{c}"
            ymin = r / rows
            xmin = c / cols
            ymax = (r + 1) / rows
            xmax = (c + 1) / cols
            bbox_norm = (ymin, xmin, ymax, xmax)
            bounds_geo = _geo_bounds_for_norm(bbox_norm, anchor)

            rec = TileRecord(
                tile_id=tid,
                bbox_norm=bbox_norm,
                bounds_geo=bounds_geo,
                step_number=session.steps_used,
            )
            session.tiles[tid] = rec

            tile_records.append({
                "id": tid,
                "bbox_norm": list(bbox_norm),
                "bounds_geo": list(bounds_geo) if bounds_geo else None,
            })

    ev = {
        "type": "vision_grid",
        "image": session.image_name,
        "rows": rows,
        "cols": cols,
        "tiles": tile_records,
        "steps_used": session.steps_used,
        "budget": session.cfg.step_budget,
    }
    session._emit(ev)

    return {
        "ok": True,
        "grid": f"{rows}x{cols}",
        "tiles": tile_records,
        "message": f"Grid {rows}×{cols} created ({rows * cols} tiles). Call crop(tile_id) to inspect each.",
    }


# ---------------------------------------------------------------------------
# Tool 2: crop
# ---------------------------------------------------------------------------

def crop(
    session: InspectionSession,
    tile_id: Optional[str] = None,
    bbox_norm: Optional[Sequence[float]] = None,
    include_source: bool = True,
    include_output_raster: bool = True,
    zoom_level: int = 1,
) -> Dict[str, Any]:
    """Extract a full-resolution side-by-side comparison crop for a tile.

    The comparison image is saved to ``feedback/thumbs/`` so that the
    browser can display it via the SSE ``vision_inspecting_tile`` event.

    Returns the saved thumbnail URL and image stats.
    """
    session.steps_used += 1

    # Resolve bounding box from tile registry or raw argument
    resolved_bbox_norm: Optional[Tuple[float, float, float, float]] = None
    resolved_tid = tile_id or "custom"

    if tile_id and tile_id in session.tiles:
        rec = session.tiles[tile_id]
        resolved_bbox_norm = rec.bbox_norm
        resolved_tid = tile_id
    elif bbox_norm is not None and len(bbox_norm) == 4:
        resolved_bbox_norm = (
            float(bbox_norm[0]), float(bbox_norm[1]),
            float(bbox_norm[2]), float(bbox_norm[3]),
        )
    else:
        return {"ok": False, "error": f"Unknown tile_id '{tile_id}' and no bbox_norm provided."}

    # Apply zoom: narrow the bounding box around the centre
    if zoom_level >= 2:
        ymin, xmin, ymax, xmax = resolved_bbox_norm
        cy, cx = (ymin + ymax) / 2, (xmin + xmax) / 2
        hy = (ymax - ymin) / (2 * zoom_level)
        hx = (xmax - xmin) / (2 * zoom_level)
        resolved_bbox_norm = (
            max(0.0, cy - hy), max(0.0, cx - hx),
            min(1.0, cy + hy), min(1.0, cx + hx),
        )

    thumb_name = f"{resolved_tid}_z{zoom_level}.png"
    thumb_path = session.feedback_dir / "thumbs" / thumb_name

    # Select best input raster
    input_raster = next((p for p in session.input_raster_paths if p.is_file()), None)
    output_raster = next((p for p in session.output_raster_paths if p.is_file()), None) \
        if include_output_raster else None

    if input_raster is None and output_raster is None and session.png_map_path is None:
        return {"ok": False, "error": "No source files available for cropping."}

    anchor = input_raster or output_raster

    try:
        if anchor is None:
            # PNG-only session: crop directly from the map PNG, no GeoTIFF panels.
            assert session.png_map_path is not None  # guaranteed by the check above
            png_arr = extract_png_crop(session.png_map_path, resolved_bbox_norm)
            if png_arr is None:
                return {"ok": False, "error": "PNG crop returned no data."}
            thumb_path.parent.mkdir(parents=True, exist_ok=True)
            from PIL import Image as _PIL_Image
            _PIL_Image.fromarray(png_arr).save(str(thumb_path))
            saved = thumb_path
        else:
            # Full multi-panel comparison using raster(s) ± PNG.
            saved = generate_side_by_side_comparison(
                input_raster_path=anchor,
                output_raster_path=output_raster if include_output_raster else None,
                png_map_path=session.png_map_path if session.png_map_path and session.png_map_path.is_file() else None,
                bbox_norm=resolved_bbox_norm,
                out_path=thumb_path,
                cfg=session.cfg,
            )

        # Build a relative URL for the frontend
        try:
            rel_url = "/" + saved.relative_to(Path.cwd()).as_posix()
        except ValueError:
            parts = saved.parts
            idx = next((i for i, p in enumerate(parts) if p == "runs"), 0)
            rel_url = "/" + "/".join(parts[idx:])

        # Store evidence path on tile record
        if tile_id and tile_id in session.tiles:
            session.tiles[tile_id].evidence_crop_path = str(saved)
            session.tiles[tile_id].step_number = session.steps_used

        ev = {
            "type": "vision_inspecting_tile",
            "image": session.image_name,
            "tile_id": resolved_tid,
            "bbox_norm": list(resolved_bbox_norm),
            "zoom_level": zoom_level,
            "thumb_url": rel_url,
            "step_number": session.steps_used,
            "max_steps": session.cfg.step_budget,
        }
        session._emit(ev)

        # Encode thumbnail as base64 for direct LLM consumption
        b64 = base64.b64encode(saved.read_bytes()).decode()

        return {
            "ok": True,
            "tile_id": resolved_tid,
            "zoom_level": zoom_level,
            "thumb_url": rel_url,
            # The image PATH is the contract the agentic loop uses: the loop
            # attaches this file to the next user message as a real image
            # attachment instead of embedding image_b64 as text inside the
            # JSON tool result (which the model could never actually see).
            "image_path": str(saved),
            "image_b64": b64,
            "bbox_norm": list(resolved_bbox_norm),
            "message": (
                f"Comparison image ready for tile {resolved_tid} (zoom ×{zoom_level}). "
                "Inspect visually then call mark_result() or get_stats() for pixel evidence."
            ),
        }
    except Exception as exc:
        return {"ok": False, "error": f"Crop generation failed: {exc}"}


# ---------------------------------------------------------------------------
# Tool 3: get_stats
# ---------------------------------------------------------------------------

def get_stats(
    session: InspectionSession,
    tile_id: Optional[str] = None,
    bbox_norm: Optional[Sequence[float]] = None,
) -> Dict[str, Any]:
    """Compute pixel-exact area statistics from the GeoTIFF for a tile.

    ALL numbers come from numpy operations on raw arrays — the vision model
    must NOT calculate counts or percentages itself.
    """
    session.steps_used += 1

    resolved_bbox_norm: Optional[Tuple[float, float, float, float]] = None
    if tile_id and tile_id in session.tiles:
        resolved_bbox_norm = session.tiles[tile_id].bbox_norm
    elif bbox_norm and len(bbox_norm) == 4:
        resolved_bbox_norm = tuple(float(v) for v in bbox_norm)  # type: ignore[assignment]
    else:
        return {"ok": False, "error": f"Unknown tile_id '{tile_id}' and no bbox_norm provided."}

    # Prefer output raster for classification stats; fall back to input
    raster_path = (
        next((p for p in session.output_raster_paths if p.is_file()), None)
        or next((p for p in session.input_raster_paths if p.is_file()), None)
    )
    if raster_path is None:
        return {"ok": False, "error": "No GeoTIFF available for pixel statistics."}

    try:
        crop_obj = extract_raster_crop(raster_path, bbox_norm=resolved_bbox_norm, cfg=session.cfg)
        arr = crop_obj.array

        if hasattr(arr, "filled"):
            raw = arr.astype("float32").filled(np.nan)
        else:
            raw = arr.astype("float32")

        # Always operate on first band (primary classification / index band)
        band = raw[0] if raw.ndim == 3 else raw
        total_px = int(band.size)
        nodata_px = int(np.isnan(band).sum())
        valid_px = total_px - nodata_px

        stats: Dict[str, Any] = {
            "tile_id": tile_id or "custom",
            "raster_path": raster_path.name,
            "total_pixels": total_px,
            "valid_pixels": valid_px,
            "nodata_pixels": nodata_px,
            "nodata_pct": round(100.0 * nodata_px / max(1, total_px), 2),
        }

        if valid_px > 0:
            valid_vals = band[np.isfinite(band)]
            stats["min"] = round(float(valid_vals.min()), 6)
            stats["max"] = round(float(valid_vals.max()), 6)
            stats["mean"] = round(float(valid_vals.mean()), 6)
            stats["std"] = round(float(valid_vals.std()), 6)

            # Class breakdown for mask / classified outputs (integer or small unique-count arrays)
            unique_vals = np.unique(np.round(valid_vals).astype(int))
            if len(unique_vals) <= 32:
                class_counts = {
                    int(v): int(np.sum(np.round(band[np.isfinite(band)]).astype(int) == v))
                    for v in unique_vals
                }
                stats["class_counts"] = class_counts
                # Surface fraction for dominant non-zero class
                dominant = max(class_counts, key=lambda k: class_counts[k] if k != 0 else -1)
                if dominant != 0:
                    stats["dominant_class"] = dominant
                    stats["dominant_class_pct"] = round(100.0 * class_counts[dominant] / max(1, valid_px), 2)

        # Store stats on tile record
        if tile_id and tile_id in session.tiles:
            session.tiles[tile_id].stats = stats

        return {"ok": True, **stats}

    except Exception as exc:
        return {"ok": False, "error": f"Pixel statistics failed: {exc}"}


# ---------------------------------------------------------------------------
# Tool 4: get_source_info
# ---------------------------------------------------------------------------

def get_source_info(session: InspectionSession) -> Dict[str, Any]:
    """Return authoritative sensor metadata for the input satellite data."""
    session.steps_used += 1

    info: Dict[str, Any] = {
        "input_files": [p.name for p in session.input_raster_paths],
        "output_files": [p.name for p in session.output_raster_paths],
    }

    for p in session.input_raster_paths:
        if not p.is_file():
            continue
        try:
            with rasterio.open(p) as src:
                tags = src.tags()
                descs = list(src.descriptions)
                info["sensor"] = tags.get("SENSOR", tags.get("SPACECRAFT_ID", tags.get("sensor", "unknown")))
                info["acquisition_date"] = tags.get("ACQUISITION_DATETIME", tags.get("DATE_ACQUIRED", tags.get("date", None)))
                info["crs"] = src.crs.to_string() if src.crs else None
                info["is_projected"] = bool(src.crs and src.crs.is_projected)
                info["resolution_m"] = list(src.res)
                info["width"] = src.width
                info["height"] = src.height
                info["band_count"] = src.count
                info["nodata"] = src.nodata
                info["band_descriptions"] = descs
                info["bounds"] = list(src.bounds)
            break  # Only need info from primary input
        except Exception as exc:
            info["read_error"] = str(exc)

    return {"ok": True, **info}


# ---------------------------------------------------------------------------
# Tool 5: mark_result
# ---------------------------------------------------------------------------

_ALLOWED_VERDICTS = frozenset({"correct", "wrong", "unsure", "not_verifiable"})
_ALLOWED_CATEGORIES = frozenset({
    "semantic_mismatch", "missing_legend", "scale_error",
    "artifact", "cloud_confusion", "coordinate_error", "blank_output",
})


def mark_result(
    session: InspectionSession,
    tile_id: str,
    verdict: str,
    rationale: str,
    defect_category: Optional[str] = None,
    confidence: float = 0.8,
    defect_bbox: Optional[Sequence[float]] = None,
) -> Dict[str, Any]:
    """Record the vision model's judgement for one tile.

    Emits a ``vision_tile_verdict`` SSE event after recording.
    """
    session.steps_used += 1

    if tile_id not in session.tiles:
        return {"ok": False, "error": f"Tile '{tile_id}' does not exist. Call make_grid first."}

    if verdict not in _ALLOWED_VERDICTS:
        return {
            "ok": False,
            "error": f"Verdict '{verdict}' is invalid. Use: {sorted(_ALLOWED_VERDICTS)}",
        }

    if defect_category and defect_category not in _ALLOWED_CATEGORIES:
        defect_category = None   # Ignore unknown category rather than failing

    rec = session.tiles[tile_id]
    session.tiles[tile_id] = dataclasses.replace(
        rec,
        verdict=verdict,
        defect_category=defect_category,
        confidence=float(np.clip(confidence, 0.0, 1.0)),
        rationale=rationale[:500],  # Cap to prevent prompt injection via very long strings
        defect_bbox=tuple(float(v) for v in defect_bbox) if defect_bbox and len(defect_bbox) == 4 else None,
        step_number=session.steps_used,
    )

    _VERDICT_COLORS = {
        "correct": "#22C55E",
        "wrong": "#EF4444",
        "unsure": "#EAB308",
        "not_verifiable": "#6B7280",
    }

    ev = {
        "type": "vision_tile_verdict",
        "image": session.image_name,
        "tile_id": tile_id,
        "verdict": verdict,
        "color": _VERDICT_COLORS.get(verdict, "#6B7280"),
        "bbox_norm": list(rec.bbox_norm),
        "defect_category": defect_category,
        "rationale": rationale[:200],
        "confidence": round(float(np.clip(confidence, 0.0, 1.0)), 3),
        "crop_url": session.tiles[tile_id].evidence_crop_path,
        "thumb_url": session.tiles[tile_id].evidence_crop_path,
        "verified_area_pct": session.verified_area_pct(),
    }
    session._emit(ev)

    return {
        "ok": True,
        "tile_id": tile_id,
        "verdict": verdict,
        "verified_area_pct": session.verified_area_pct(),
        "message": f"Tile {tile_id} marked '{verdict}'. {session.verified_area_pct():.1f}% of grid area judged.",
    }


# ---------------------------------------------------------------------------
# Tool 6: report_insufficient_data
# ---------------------------------------------------------------------------

def report_insufficient_data(
    session: InspectionSession,
    reason: str,
    evidence_tile_id: Optional[str] = None,
    missing_data_fraction: float = 0.0,
) -> Dict[str, Any]:
    """Abort validation — input data quality too poor to verify.

    This outcome is NOT sent back to the sub-agent as a code bug.
    The caller is responsible for surfacing it directly to the user.
    """
    session.steps_used += 1
    session.aborted = True
    session.abort_reason = reason[:600]
    session.abort_tile_id = evidence_tile_id
    session.abort_missing_fraction = float(np.clip(missing_data_fraction, 0.0, 1.0))

    ev = {
        "type": "vision_insufficient_data",
        "image": session.image_name,
        "tile_id": evidence_tile_id,
        "reason": session.abort_reason,
        "missing_data_fraction": session.abort_missing_fraction,
        "steps_used": session.steps_used,
        "budget": session.cfg.step_budget,
    }
    session._emit(ev)
    session._emit({
        "type": "vision_stopped",
        "image": session.image_name,
        "reason": "insufficient_data",
        "detail": session.abort_reason,
    })

    return {
        "ok": True,
        "verdict": "insufficient_data",
        "reason": session.abort_reason,
        "message": (
            "Validation aborted: insufficient data quality. This is an INPUT problem — "
            "do NOT retry the sub-agent. Report the limitation to the user."
        ),
    }


# ---------------------------------------------------------------------------
# Tool 7: finish
# ---------------------------------------------------------------------------

def finish(session: InspectionSession, summary: str) -> Dict[str, Any]:
    """Aggregate all tile marks and emit the final verdict + summary event.

    Marks any un-judged tiles as ``not_verifiable`` before computing the
    overall verdict.  Emits a ``vision_summary`` SSE event.
    """
    session.steps_used += 1
    session.finish_called = True
    session.finish_summary = summary[:800]

    # Auto-close any tiles that the model ran out of steps to inspect
    for tid, rec in session.tiles.items():
        if rec.verdict is None:
            session.tiles[tid] = dataclasses.replace(rec, verdict="not_verifiable")

    # Derive overall verdict
    if session.aborted:
        final_verdict = "insufficient_data"
    else:
        wrong_tiles = [t for t in session.tiles.values() if t.verdict == "wrong"]
        if wrong_tiles:
            final_verdict = "not_valid"
        elif any(t.verdict in ("unsure", "needs_review") for t in session.tiles.values()):
            final_verdict = "needs_review"
        else:
            final_verdict = "valid"

    flagged = [
        {
            "tile_id": t.tile_id,
            "verdict": t.verdict,
            "defect_category": t.defect_category,
            "rationale": t.rationale,
            "confidence": t.confidence,
            "crop_url": t.evidence_crop_path,
            "stats": t.stats,
            "defect_bbox": list(t.defect_bbox) if t.defect_bbox else None,
        }
        for t in session.tiles.values()
        if t.verdict in ("wrong", "unsure", "needs_review", "not_verifiable")
    ]

    ev = {
        "type": "vision_summary",
        "image": session.image_name,
        "final_verdict": final_verdict,
        "verified_area_pct": session.verified_area_pct(),
        "tiles_checked": len(session.tiles),
        "defects_count": len([t for t in session.tiles.values() if t.verdict == "wrong"]),
        "flagged_regions": flagged,
        "summary": session.finish_summary,
    }
    session._emit(ev)

    # Persist session summary to disk next to feedback/
    try:
        out = session.feedback_dir / f"validation_{session.image_name.replace('/', '_')}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(session.to_summary_dict(), indent=2, default=str), encoding="utf-8")
    except Exception:
        pass

    return {
        "ok": True,
        "final_verdict": final_verdict,
        "verified_area_pct": session.verified_area_pct(),
        "flagged_regions": flagged,
        "summary": session.finish_summary,
        "message": f"Validation complete: {final_verdict}. {session.verified_area_pct():.1f}% area verified.",
    }


# ---------------------------------------------------------------------------
# Tool dispatcher (used by the agentic loop in Phase 3)
# ---------------------------------------------------------------------------

TOOL_REGISTRY: Dict[str, Any] = {
    "make_grid": make_grid,
    "crop": crop,
    "get_stats": get_stats,
    "get_source_info": get_source_info,
    "mark_result": mark_result,
    "report_insufficient_data": report_insufficient_data,
    "finish": finish,
}


def dispatch_tool(
    session: InspectionSession,
    tool_name: str,
    tool_args: Dict[str, Any],
) -> Dict[str, Any]:
    """Route a model tool call to the correct backend function.

    Returns the tool result dict.  Never raises — errors are returned as
    ``{"ok": False, "error": "..."}`` so the calling agent loop can decide
    how to proceed.
    """
    fn = TOOL_REGISTRY.get(tool_name)
    if fn is None:
        return {
            "ok": False,
            "error": (
                f"Unknown tool '{tool_name}'. "
                f"Available tools: {sorted(TOOL_REGISTRY)}"
            ),
        }
    if session.aborted and tool_name not in ("finish",):
        return {"ok": False, "error": "Session is already aborted — call finish() to conclude."}
    if session.finish_called:
        return {"ok": False, "error": "finish() has already been called."}
    if session.budget_exceeded() and tool_name not in ("finish", "report_insufficient_data"):
        # Force finish rather than letting the model keep spending tokens
        return finish(session, summary="Step budget exhausted — session auto-closed.")
    try:
        return fn(session, **tool_args)
    except TypeError as exc:
        return {"ok": False, "error": f"Bad arguments for tool '{tool_name}': {exc}"}
    except Exception as exc:
        return {"ok": False, "error": f"Tool '{tool_name}' raised an unexpected error: {exc}"}

