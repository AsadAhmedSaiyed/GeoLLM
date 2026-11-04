"""Preflight input quality gate for vision validation.

Runs *before* any model call.  Uses the deterministic quality gate
(``inspect_raster_quality`` / ``evaluate_quality_gate``) on the real
uploaded raster paths — never on a mtime heuristic or a guessed filename.

If the inputs are unusable (nodata fraction, cloud fraction, or
multi-date intersection below the configured thresholds) the gate emits
``vision_input_gate`` and ``vision_insufficient_data`` SSE events and
returns ``None`` so the caller stops without making a model call.

Thresholds are read from the environment via
``harness.validation.config.get_validation_config``:

* ``GEOLLM_MAX_NODATA_FRACTION``   (default 0.60)
* ``GEOLLM_MAX_CLOUD_FRACTION``    (default 0.70)
"""
from __future__ import annotations

import logging
from typing import Callable, List, Optional, Sequence, Union

from .quality_gate import QualityGateResult, evaluate_quality_gate, inspect_raster_quality

log = logging.getLogger("harness.validation.input_gate")


def _file_summary(report) -> dict:
    """Build the per-file payload the UI renders in the input-gate card."""
    return {
        "name": report.path,
        "nodata_pct": round(report.nodata_fraction * 100.0, 1),
        "cloud_pct": round(report.cloud_fraction * 100.0, 1),
        "crs": report.crs,
        "resolution_m": [round(v, 3) for v in report.resolution],
        "width": report.width,
        "height": report.height,
        "is_usable": report.is_usable,
        "issues": list(report.issues),
    }


def run_input_gate(
    files: Sequence[Union[str, "object"]],
    on_step: Optional[Callable] = None,
) -> Optional[QualityGateResult]:
    """Evaluate the uploaded inputs.  Returns the gate result, or ``None``.

    A return value of ``None`` means the gate blocked execution — the caller
    must stop without making any model call.  The SSE events
    (``vision_input_gate`` and ``vision_insufficient_data``) are emitted
    through ``on_step`` before returning ``None``.
    """
    step = on_step or (lambda ev: None)

    # Resolve real paths.  ``files`` may be Path-like objects or strings;
    # the gate only cares about GeoTIFF rasters, so non-raster inputs are
    # ignored (they cannot carry nodata/cloud statistics).
    raster_paths = [str(f) for f in files if str(f).lower().endswith((".tif", ".tiff"))]

    step({
        "type": "vision_input_gate",
        "state": "started",
        "raster_count": len(raster_paths),
        "raster_paths": raster_paths,
    })

    result = evaluate_quality_gate(raster_paths)

    # Build the per-file summaries the UI needs.  evaluate_quality_gate
    # already inspected every raster, so we reuse those reports rather than
    # re-opening the files.
    files_summary = [_file_summary(r) for r in result.reports]

    if result.verdict == "insufficient_data":
        log.warning("Input gate blocked: %s", result.reason)
        step({
            "type": "vision_input_gate",
            "state": "done",
            "verdict": "insufficient_data",
            "reason": result.reason,
            "area_verified_pct": result.area_verified_pct,
            "raster_count": len(raster_paths),
            "raster_paths": raster_paths,
            "files": files_summary,
        })
        step({
            "type": "vision_insufficient_data",
            "reason": result.reason,
            "area_verified_pct": result.area_verified_pct,
            "raster_count": len(raster_paths),
            "files": files_summary,
        })
        step({
            "type": "vision_stopped",
            "reason": "insufficient_data",
            "detail": result.reason,
        })
        return None

    step({
        "type": "vision_input_gate",
        "state": "done",
        "verdict": result.verdict,
        "reason": result.reason,
        "area_verified_pct": result.area_verified_pct,
        "raster_count": len(raster_paths),
        "raster_paths": raster_paths,
        "files": files_summary,
    })
    return result