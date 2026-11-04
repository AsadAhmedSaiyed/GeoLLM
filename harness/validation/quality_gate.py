"""Deterministic data quality gate for satellite GeoTIFF inputs.

Evaluates nodata percentages, cloud contamination, spatial resolution, CRS,
and multi-date common valid areas before and during validation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import calculate_default_transform, reproject

from .config import ValidationConfig, get_validation_config


@dataclass(frozen=True)
class RasterQualityReport:
    """Quality metrics for a single GeoTIFF raster."""
    path: str
    width: int
    height: int
    crs: Optional[str]
    is_projected: bool
    resolution: Tuple[float, float]
    bounds: Tuple[float, float, float, float]
    nodata_value: Optional[float]
    total_pixels: int
    valid_pixels: int
    nodata_pixels: int
    nodata_fraction: float
    cloud_fraction: float
    cloud_detection_method: str  # "scl" | "qa_band" | "spectral_heuristic" | "none"
    is_usable: bool
    verdict: str  # "valid" | "insufficient_data" | "not_valid"
    issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    band_details: List[Dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class MutualValidMaskResult:
    """Intersection mask analysis for multi-date or multi-raster analysis."""
    raster_paths: List[str]
    reference_path: str
    reference_crs: str
    reference_shape: Tuple[int, int]
    total_pixels: int
    mutual_valid_pixels: int
    mutual_valid_fraction: float
    is_sufficient: bool
    verdict: str  # "valid" | "insufficient_data"
    issues: List[str] = field(default_factory=list)
    per_raster_valid_fractions: Dict[str, float] = field(default_factory=dict)
    # Binary 2D mask (1 = valid in all rasters, 0 = invalid in at least one)
    valid_intersection_mask: Optional[np.ndarray] = field(default=None, repr=False)


@dataclass(frozen=True)
class QualityGateResult:
    """Overall outcome of the preflight data quality gate."""
    verdict: str  # "valid" | "insufficient_data" | "not_valid"
    is_approved: bool
    reason: str
    reports: List[RasterQualityReport]
    mutual_mask_result: Optional[MutualValidMaskResult] = None
    area_verified_pct: float = 0.0


def _find_band_by_predicate(descriptions: Sequence[Optional[str]], tags: Dict[str, Any], predicates: Sequence[str]) -> Optional[int]:
    """Finds 1-based band index matching any of the given lower-case predicates."""
    for idx, desc in enumerate(descriptions, start=1):
        if desc:
            d_lower = desc.lower()
            if any(p in d_lower for p in predicates):
                return idx
    for key, val in tags.items():
        k_lower = str(key).lower()
        v_lower = str(val).lower()
        if any(p in k_lower or p in v_lower for p in predicates):
            try:
                if "band" in k_lower:
                    digits = "".join(ch for ch in k_lower if ch.isdigit())
                    if digits:
                        return int(digits)
            except Exception:
                pass
    return None


def _detect_cloud_mask(
    src: rasterio.DatasetReader,
    sample_shape: Tuple[int, int],
    cfg: ValidationConfig,
) -> Tuple[Optional[np.ndarray], str, float]:
    """Detects or estimates a boolean cloud mask (True = cloud/shadow).

    Returns:
        (cloud_mask_array, method_used, cloud_fraction)
    """
    desc = list(src.descriptions)
    tags = src.tags()

    # 1. Check for SCL (Scene Classification Layer) band
    scl_band = _find_band_by_predicate(desc, tags, ["scl", "scene_classification", "scene classification"])
    if scl_band and 1 <= scl_band <= src.count:
        scl = src.read(scl_band, out_shape=sample_shape, resampling=Resampling.nearest)
        # SCL cloud classes: 3 = Cloud Shadows, 8 = Cloud Medium, 9 = Cloud High, 10 = Cirrus
        is_cloud = np.isin(scl, [3, 8, 9, 10])
        valid_px = (scl != 0)
        c_frac = float(is_cloud.sum() / max(1, valid_px.sum())) if valid_px.any() else 0.0
        return is_cloud, "scl", round(c_frac, 4)

    # 2. Check for QA60 or dedicated QA cloud mask band
    qa_band = _find_band_by_predicate(desc, tags, ["qa60", "qa_band", "cloud_mask", "cloudmask", "qa"])
    if qa_band and 1 <= qa_band <= src.count:
        qa = src.read(qa_band, out_shape=sample_shape, resampling=Resampling.nearest)
        if "qa60" in str(desc[qa_band - 1] or "").lower():
            # Bits 10 (opaque cloud) and 11 (cirrus)
            is_cloud = ((qa & (1 << 10)) > 0) | ((qa & (1 << 11)) > 0)
        else:
            is_cloud = qa > 0
        c_frac = float(is_cloud.mean())
        return is_cloud, "qa_band", round(c_frac, 4)

    # 3. Spectral heuristic check when multi-band optical data is present
    blue_idx = _find_band_by_predicate(desc, tags, ["blue", "b02", "b2"])
    green_idx = _find_band_by_predicate(desc, tags, ["green", "b03", "b3"])
    red_idx = _find_band_by_predicate(desc, tags, ["red", "b04", "b4"])
    swir_idx = _find_band_by_predicate(desc, tags, ["swir", "swir1", "swir2", "b11", "b12"])

    if blue_idx and green_idx and red_idx and swir_idx:
        # Load sample slices
        b = src.read(blue_idx, out_shape=sample_shape, masked=True).astype("float32")
        g = src.read(green_idx, out_shape=sample_shape, masked=True).astype("float32")
        r = src.read(red_idx, out_shape=sample_shape, masked=True).astype("float32")
        s = src.read(swir_idx, out_shape=sample_shape, masked=True).astype("float32")

        # Determine if data is integer scaled (e.g. 0..10000) or float reflectance (0..1)
        valid_mask = ~(b.mask | g.mask | r.mask | s.mask)
        if valid_mask.any():
            b_arr = b.filled(np.nan)
            r_arr = r.filled(np.nan)
            s_arr = s.filled(np.nan)
            scale = 10000.0 if np.nanmax(r_arr[valid_mask]) > 10.0 else 1.0

            opt_bright = (b_arr + r_arr) / (2.0 * scale)
            swir_val = s_arr / scale

            # Clouds are bright in optical AND bright in SWIR.
            # Salt flats/dry playas/snow have high optical brightness but low SWIR.
            is_cloud = (opt_bright > cfg.cloud_optical_min) & (swir_val > cfg.cloud_swir_min)
            is_salt_flat = (opt_bright > cfg.cloud_optical_min) & (swir_val <= cfg.salt_flat_swir_max)

            c_count = int(np.nansum(is_cloud & valid_mask))
            total_valid = int(valid_mask.sum())
            c_frac = float(c_count / max(1, total_valid))
            return is_cloud, "spectral_heuristic", round(c_frac, 4)

    return None, "none", 0.0


def inspect_raster_quality(
    raster_path: Union[str, Path],
    cfg: Optional[ValidationConfig] = None,
) -> RasterQualityReport:
    """Inspects a single GeoTIFF file for data quality and integrity."""
    config = cfg or get_validation_config()
    p = Path(raster_path)
    issues: List[str] = []
    warnings: List[str] = []

    if not p.is_file():
        return RasterQualityReport(
            path=str(p), width=0, height=0, crs=None, is_projected=False,
            resolution=(0.0, 0.0), bounds=(0.0, 0.0, 0.0, 0.0), nodata_value=None,
            total_pixels=0, valid_pixels=0, nodata_pixels=0, nodata_fraction=1.0,
            cloud_fraction=0.0, cloud_detection_method="none", is_usable=False,
            verdict="not_valid", issues=[f"File not found: {p}"]
        )

    try:
        with rasterio.open(p) as src:
            w, h = src.width, src.height
            crs_str = src.crs.to_string() if src.crs else None
            is_projected = bool(src.crs and src.crs.is_projected)
            res = (abs(src.res[0]), abs(src.res[1]))
            bounds = (src.bounds.left, src.bounds.bottom, src.bounds.right, src.bounds.top)
            nodata_val = src.nodata

            if src.crs is None:
                issues.append(f"Raster '{p.name}' lacks a coordinate reference system (CRS).")

            # Determine downsampled sample shape for fast memory-bounded inspection
            step = max(1, max(w, h) // config.sample_max_px)
            sample_shape = (max(1, h // step), max(1, w // step))

            # Sample primary band for nodata and validity
            arr_masked = src.read(1, out_shape=sample_shape, masked=True)
            total_sample_px = sample_shape[0] * sample_shape[1]

            # In rasterio masked reads, mask is True for nodata/invalid pixels
            mask = arr_masked.mask
            if isinstance(mask, np.ndarray):
                nodata_px = int(mask.sum())
            else:
                nodata_px = int(total_sample_px if mask else 0)

            # Check for non-finite values (NaN / Inf) in floating arrays
            raw = arr_masked.data
            if raw.dtype.kind == "f":
                nan_mask = ~np.isfinite(raw)
                nodata_px = int(np.logical_or(mask, nan_mask).sum())

            valid_px = max(0, total_sample_px - nodata_px)
            nodata_frac = round(float(nodata_px / max(1, total_sample_px)), 4)

            # Check for cloud contamination
            _, cloud_method, cloud_frac = _detect_cloud_mask(src, sample_shape, config)

            # Collect band metadata
            band_info: List[Dict[str, Any]] = []
            for b_idx in range(1, src.count + 1):
                desc = src.descriptions[b_idx - 1] if b_idx - 1 < len(src.descriptions) else None
                band_info.append({"index": b_idx, "description": desc, "dtype": str(src.dtypes[b_idx - 1])})

    except Exception as exc:
        return RasterQualityReport(
            path=str(p), width=0, height=0, crs=None, is_projected=False,
            resolution=(0.0, 0.0), bounds=(0.0, 0.0, 0.0, 0.0), nodata_value=None,
            total_pixels=0, valid_pixels=0, nodata_pixels=0, nodata_fraction=1.0,
            cloud_fraction=0.0, cloud_detection_method="none", is_usable=False,
            verdict="not_valid", issues=[f"Failed to read raster: {exc}"]
        )

    # Determine usability and verdict
    verdict = "valid"
    is_usable = True

    if nodata_frac >= config.max_nodata_fraction:
        issues.append(f"Excessive nodata/blank area: {nodata_frac:.1%} (threshold {config.max_nodata_fraction:.1%}).")
        verdict = "insufficient_data"
        is_usable = False
    elif nodata_frac > 0.20:
        warnings.append(f"Significant nodata area: {nodata_frac:.1%}.")

    if cloud_frac >= config.max_cloud_fraction:
        issues.append(f"Severe cloud contamination: {cloud_frac:.1%} (threshold {config.max_cloud_fraction:.1%}).")
        verdict = "insufficient_data"
        is_usable = False
    elif cloud_frac > 0.30:
        warnings.append(f"Moderate cloud contamination: {cloud_frac:.1%}.")

    if not is_projected and src.crs is not None:
        warnings.append("Raster is in geographic coordinates (degrees); metric area calculations require projected CRS.")

    return RasterQualityReport(
        path=str(p),
        width=w,
        height=h,
        crs=crs_str,
        is_projected=is_projected,
        resolution=res,
        bounds=bounds,
        nodata_value=nodata_val,
        total_pixels=total_sample_px,
        valid_pixels=valid_px,
        nodata_pixels=nodata_px,
        nodata_fraction=nodata_frac,
        cloud_fraction=cloud_frac,
        cloud_detection_method=cloud_method,
        is_usable=is_usable,
        verdict=verdict,
        issues=issues,
        warnings=warnings,
        band_details=band_info,
    )


def compute_mutual_valid_mask(
    raster_paths: Sequence[Union[str, Path]],
    target_shape: Optional[Tuple[int, int]] = None,
    cfg: Optional[ValidationConfig] = None,
) -> MutualValidMaskResult:
    """Computes a pixel-by-pixel intersection mask of valid data across multiple rasters.

    All rasters are aligned to the primary reference grid. Pixels that are nodata
    or cloud-contaminated in ANY date are marked invalid (False).

    Returns:
        MutualValidMaskResult containing mutual valid fraction and binary mask.
    """
    config = cfg or get_validation_config()
    paths = [Path(p) for p in raster_paths if Path(p).is_file()]
    if not paths:
        return MutualValidMaskResult(
            raster_paths=[], reference_path="", reference_crs="",
            reference_shape=(0, 0), total_pixels=0, mutual_valid_pixels=0,
            mutual_valid_fraction=0.0, is_sufficient=False, verdict="insufficient_data",
            issues=["No valid raster files provided."]
        )

    ref_path = paths[0]
    with rasterio.open(ref_path) as ref_src:
        ref_crs = ref_src.crs
        ref_w, ref_h = ref_src.width, ref_src.height
        step = max(1, max(ref_w, ref_h) // config.sample_max_px)
        grid_shape = target_shape or (max(1, ref_h // step), max(1, ref_w // step))
        scale_x = ref_src.width / grid_shape[1]
        scale_y = ref_src.height / grid_shape[0]
        scale_affine = ref_src.transform.scale(scale_x, scale_y)
        ref_transform = ref_src.transform @ scale_affine if hasattr(ref_src.transform, "__matmul__") else ref_src.transform * scale_affine

    accumulated_valid_mask = np.ones(grid_shape, dtype=bool)
    per_raster_fractions: Dict[str, float] = {}
    issues: List[str] = []

    for p in paths:
        with rasterio.open(p) as src:
            # Create sample in native grid, accounting for nodata and clouds
            step_src = max(1, max(src.width, src.height) // config.sample_max_px)
            src_sample_shape = (max(1, src.height // step_src), max(1, src.width // step_src))
            arr_masked = src.read(1, out_shape=src_sample_shape, masked=True)

            valid_src = ~arr_masked.mask
            if arr_masked.data.dtype.kind == "f":
                valid_src = valid_src & np.isfinite(arr_masked.data)

            # Strip out clouds if detected
            cloud_mask, _, _ = _detect_cloud_mask(src, src_sample_shape, config)
            if cloud_mask is not None:
                valid_src = valid_src & (~cloud_mask)

            # Reproject valid_src onto the reference grid
            valid_on_ref = np.zeros(grid_shape, dtype=np.uint8)
            src_scale_x = src.width / src_sample_shape[1]
            src_scale_y = src.height / src_sample_shape[0]
            src_scale_affine = src.transform.scale(src_scale_x, src_scale_y)
            src_grid_transform = src.transform @ src_scale_affine if hasattr(src.transform, "__matmul__") else src.transform * src_scale_affine
            reproject(
                source=valid_src.astype(np.uint8),
                destination=valid_on_ref,
                src_transform=src_grid_transform,
                src_crs=src.crs,
                dst_transform=ref_transform,
                dst_crs=ref_crs,
                resampling=Resampling.nearest,
            )

            is_valid_bool = (valid_on_ref == 1)
            frac = float(is_valid_bool.mean())
            per_raster_fractions[p.name] = round(frac, 4)
            accumulated_valid_mask = accumulated_valid_mask & is_valid_bool

    total_px = grid_shape[0] * grid_shape[1]
    mutual_valid_px = int(accumulated_valid_mask.sum())
    mutual_valid_frac = round(float(mutual_valid_px / max(1, total_px)), 4)

    is_sufficient = mutual_valid_frac >= config.min_mutual_valid_fraction
    verdict = "valid" if is_sufficient else "insufficient_data"

    if not is_sufficient:
        issues.append(
            f"Common valid area across observations is only {mutual_valid_frac:.1%} "
            f"(minimum required: {config.min_mutual_valid_fraction:.1%}). "
            f"Sensor nodata or cloud contamination prevents reliable change detection."
        )

    return MutualValidMaskResult(
        raster_paths=[str(p) for p in paths],
        reference_path=str(ref_path),
        reference_crs=ref_crs.to_string() if ref_crs else "unknown",
        reference_shape=grid_shape,
        total_pixels=total_px,
        mutual_valid_pixels=mutual_valid_px,
        mutual_valid_fraction=mutual_valid_frac,
        is_sufficient=is_sufficient,
        verdict=verdict,
        issues=issues,
        per_raster_valid_fractions=per_raster_fractions,
        valid_intersection_mask=accumulated_valid_mask,
    )


def evaluate_quality_gate(
    file_paths: Sequence[Union[str, Path]],
    cfg: Optional[ValidationConfig] = None,
) -> QualityGateResult:
    """Preflight quality gate evaluating all input files before sub-agent execution."""
    config = cfg or get_validation_config()
    raster_paths = [Path(p) for p in file_paths if Path(p).suffix.lower() in (".tif", ".tiff")]

    if not raster_paths:
        return QualityGateResult(
            verdict="not_valid",
            is_approved=False,
            reason="No GeoTIFF raster files provided for analysis.",
            reports=[],
        )

    reports: List[RasterQualityReport] = []
    for rp in raster_paths:
        rep = inspect_raster_quality(rp, config)
        reports.append(rep)

    # 1. Check individual file quality
    unusable_reports = [r for r in reports if not r.is_usable]
    if unusable_reports:
        reasons = "; ".join(f"{Path(r.path).name}: {', '.join(r.issues)}" for r in unusable_reports)
        return QualityGateResult(
            verdict="insufficient_data",
            is_approved=False,
            reason=f"Input dataset quality check failed: {reasons}",
            reports=reports,
        )

    # 2. Check multi-date common valid overlap if multiple rasters are present
    mutual_result = None
    if len(raster_paths) > 1:
        mutual_result = compute_mutual_valid_mask(raster_paths, cfg=config)
        if not mutual_result.is_sufficient:
            return QualityGateResult(
                verdict="insufficient_data",
                is_approved=False,
                reason=f"Multi-temporal intersection failed: {'; '.join(mutual_result.issues)}",
                reports=reports,
                mutual_mask_result=mutual_result,
                area_verified_pct=round(mutual_result.mutual_valid_fraction * 100.0, 1),
            )

    area_pct = round((mutual_result.mutual_valid_fraction if mutual_result else reports[0].valid_pixels / max(1, reports[0].total_pixels)) * 100.0, 1)

    return QualityGateResult(
        verdict="valid",
        is_approved=True,
        reason="All input rasters meet data quality, cloud cover, and spatial coverage criteria.",
        reports=reports,
        mutual_mask_result=mutual_result,
        area_verified_pct=area_pct,
    )
