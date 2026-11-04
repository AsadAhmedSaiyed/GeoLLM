"""Validation upgrade package for GeoLLM.

Exposes deterministic data quality gates, geospatial window cropping,
multi-panel side-by-side comparison rendering, and validation configuration.
"""
from .config import ValidationConfig, get_validation_config
from .quality_gate import (
    MutualValidMaskResult,
    QualityGateResult,
    RasterQualityReport,
    compute_mutual_valid_mask,
    evaluate_quality_gate,
    inspect_raster_quality,
)
from .geo_crop import (
    ExtractedCrop,
    extract_png_crop,
    extract_raster_crop,
    generate_side_by_side_comparison,
    render_crop_to_rgb,
)
from .tools import (
    InspectionSession,
    TileRecord,
    TOOL_REGISTRY,
    dispatch_tool,
    make_grid,
    crop,
    get_stats,
    get_source_info,
    mark_result,
    report_insufficient_data,
    finish,
)
from .consensus import re_verify_flagged_tiles
from .graph_check import validate_graph_deliverable
from .feedback import format_structured_feedback

__all__ = [
    # config
    "ValidationConfig",
    "get_validation_config",
    # quality_gate
    "MutualValidMaskResult",
    "QualityGateResult",
    "RasterQualityReport",
    "inspect_raster_quality",
    "compute_mutual_valid_mask",
    "evaluate_quality_gate",
    # geo_crop
    "ExtractedCrop",
    "extract_raster_crop",
    "extract_png_crop",
    "render_crop_to_rgb",
    "generate_side_by_side_comparison",
    # tools
    "InspectionSession",
    "TileRecord",
    "TOOL_REGISTRY",
    "dispatch_tool",
    "make_grid",
    "crop",
    "get_stats",
    "get_source_info",
    "mark_result",
    "report_insufficient_data",
    "finish",
    # consensus
    "re_verify_flagged_tiles",
    # graph_check
    "validate_graph_deliverable",
    # feedback
    "format_structured_feedback",
]

