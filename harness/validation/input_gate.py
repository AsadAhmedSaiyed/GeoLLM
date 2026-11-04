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

from .quality_gate import QualityGateResult, evaluate_quality_gate

log = logging.getLogger("harness.validation.input_gate")


def run_input_gate(
    files: Sequence[Union[str, "object"]],
    on_step: Optional[Callable] = None,
) -> Optional[QualityGateResult]:
    """Evaluate the uploaded inputs.  Returns the gate result, or ``None``.

    A return value of ``None`` means the gate blocked execution — the caller
    must stop without making any model call.  The two SSE events
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
        "raster_count": len(raster_paths),
        "raster_paths": raster_paths,
        "state": "started",
    })

    result = evaluate_quality_gate(raster_paths)

    if result.verdict == "insufficient_data":
        log.warning("Input gate blocked: %s", result.reason)
        step({
            "type": "vision_input_gate",
            "raster_count": len(raster_paths),
            "raster_paths": raster_paths,
            "state": "done",
            "verdict": "insufficient_data",
            "reason": result.reason,
        })
        step({
            "type": "vision_insufficient_data",
            "reason": result.reason,
            "area_verified_pct": result.area_verified_pct,
            "reports": [
                {
                    "path": r.path,
                    "nodata_fraction": r.nodata_fraction,
                    "cloud_fraction": r.cloud_fraction,
                    "is_usable": r.is_usable,
                    "issues": list(r.issues),
                }
                for r in result.reports
            ],
        })
        return None

    step({
        "type": "vision_input_gate",
        "raster_count": len(raster_paths),
        "raster_paths": raster_paths,
        "state": "done",
        "verdict": result.verdict,
        "reason": result.reason,
        "area_verified_pct": result.area_verified_pct,
    })
    return result