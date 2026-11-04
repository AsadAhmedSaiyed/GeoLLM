"""Configuration parameters and thresholds for the validation engine."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (ValueError, TypeError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (ValueError, TypeError):
        return default


@dataclass(frozen=True)
class ValidationConfig:
    """Immutable validation runtime configuration."""
    validation_mode: str = os.environ.get("GEOLLM_VALIDATION_MODE", "agentic")
    max_nodata_fraction: float = _env_float("GEOLLM_MAX_NODATA_FRACTION", 0.60)
    max_cloud_fraction: float = _env_float("GEOLLM_MAX_CLOUD_FRACTION", 0.70)
    min_mutual_valid_fraction: float = _env_float("GEOLLM_MIN_MUTUAL_VALID_FRACTION", 0.15)
    sample_max_px: int = _env_int("GEOLLM_SAMPLE_MAX_PX", 2048)
    crop_size_px: int = _env_int("GEOLLM_CROP_SIZE_PX", 512)
    step_budget: int = _env_int("GEOLLM_VALIDATION_STEP_BUDGET", 12)
    cost_limit_usd: float = _env_float("GEOLLM_VALIDATION_COST_LIMIT", 0.20)
    # Spectral heuristic thresholds for separating clouds from high-albedo salt/snow
    cloud_optical_min: float = _env_float("GEOLLM_CLOUD_OPTICAL_MIN", 0.35)
    cloud_swir_min: float = _env_float("GEOLLM_CLOUD_SWIR_MIN", 0.20)
    salt_flat_swir_max: float = _env_float("GEOLLM_SALT_SWIR_MAX", 0.15)


def get_validation_config() -> ValidationConfig:
    """Returns an instance of ValidationConfig with environment overrides applied."""
    return ValidationConfig()

