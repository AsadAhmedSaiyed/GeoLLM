"""
Deterministic validation of an LLM-generated geospatial plan.

The planner is intentionally modality-agnostic.

This module checks:
    dataset -> plan consistency
    temporal requirements
    raster alignment
    required plan structure

It must NOT force every problem into a fixed list of optical bands.

Legacy optical `required_roles` are still supported for compatibility,
but unknown/custom roles are not rejected merely because they are not
in the legacy optical role list. This allows SAR, DEM, custom raster
measurements, vectors, and other future modalities.
"""

import json
import re


PLAN_KEYS = (
    "meaning",
    "measures",
    "required_roles",
    "needs_two_dates",
    "preprocessing",
    "assumptions",
    "outputs",
)

# Legacy optical roles.
#
# These are retained only because existing plans/tests may still use them.
# They are NOT the complete set of valid geospatial measurements.
LEGACY_OPTICAL_ROLES = (
    "blue",
    "green",
    "red",
    "nir",
    "swir1",
    "swir2",
)

# Backwards-compatible alias for code that imports ROLES.
ROLES = LEGACY_OPTICAL_ROLES

def normalize_requirements(reqs):
    """Turn the planner's requirements into a list of {"text", "check"} dicts."""
    out = []
    for r in reqs or []:
        if isinstance(r, str):
            out.append({"text": r, "check": {}})
        elif isinstance(r, dict):
            out.append({"text": str(r.get("text", "")), "check": r.get("check") or {}})
    return out

def has_key(obj, key):
    """True if `key` appears anywhere in a nested result with a real (non-None) value."""
    if isinstance(obj, dict):
        if key in obj and obj[key] is not None:
            return True
        return any(has_key(v, key) for v in obj.values())
    if isinstance(obj, list):
        return any(has_key(v, key) for v in obj)
    return False


def parse_json(text):
    """Extract a JSON object from an LLM reply. Returns a dict, or None if none can be parsed."""
    if not text:
        return None

    # 1. A ```json fenced block.
    m = re.search(r"```json\s*\n(.*?)```", text, re.S)
    candidates = [m.group(1)] if m else []

    # 2. Any other fenced block.
    candidates += re.findall(r"```\s*\n(.*?)```", text, re.S)

    # 3. The outermost {...} in the raw text.
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])

    for block in candidates:
        try:
            value = json.loads(block.strip())
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(value, dict):
            return value

    return None

def parse_reply(text):
    """
    Extract a JSON plan and optional Python code from an LLM response.

    Returns:
        (plan_dict_or_none, python_code_or_none)
    """

    plan = None

    # JSON plan block.
    m = re.search(
        r"```json\s*\n(.*?)```",
        text or "",
        re.S,
    )

    if m:
        try:
            plan = json.loads(m.group(1))
        except json.JSONDecodeError:
            plan = None

    # Python code block.
    c = re.search(
        r"```python\s*\n(.*?)```",
        text or "",
        re.S,
    )

    if c:
        return plan, c.group(1).strip()

    # Fallback for an unlabeled code block.
    for block in re.findall(
        r"```\s*\n(.*?)```",
        text or "",
        re.S,
    ):
        block = block.strip()

        if not block:
            continue

        # JSON-only block.
        if block.startswith("{"):
            try:
                if plan is None:
                    plan = json.loads(block)
                continue
            except json.JSONDecodeError:
                pass

        return plan, block

    return plan, None


def _norm(value):
    """Normalize a label for case-insensitive matching."""

    if value is None:
        return ""

    return re.sub(
        r"[^a-z0-9]+",
        "",
        str(value).lower(),
    )


def _band_labels(raster_info):
    """Return all useful labels for the raster's bands."""

    labels = []

    for band in raster_info.get("bands", []):
        if not isinstance(band, dict):
            continue

        for key in (
            "label",
            "name",
            "description",
            "role",
        ):
            value = band.get(key)

            if value:
                labels.append(str(value))

    return labels


def _find_role_in_raster(raster_info, role):
    """
    Determine whether a requested role/measurement can be matched
    to a raster band.

    Returns:
        "found"
        "ambiguous"
        "missing"
        "unknown"
    """

    target = _norm(role)

    if not target:
        return "unknown"

    matches = []

    for index, band in enumerate(
        raster_info.get("bands", []),
        start=1,
    ):
        if not isinstance(band, dict):
            continue

        candidates = []

        for key in (
            "label",
            "name",
            "description",
            "role",
        ):
            value = band.get(key)

            if value:
                candidates.append(str(value))

        normalized = {
            _norm(value)
            for value in candidates
            if value
        }

        if target in normalized:
            matches.append(index)
            continue

        # Useful for common SAR naming such as:
        # VV, VH, "VV backscatter", "VH polarization".
        for value in normalized:
            if (
                target == value
                or target in value
                or value in target
            ):
                matches.append(index)
                break

    if len(matches) == 1:
        return "found"

    if len(matches) > 1:
        return "ambiguous"

    return "missing"


def _rasters(facts):
    """Return raster file facts."""

    files = facts.get("files", {})

    return {
        name: info
        for name, info in files.items()
        if info.get("kind") == "raster"
    }


def _has_explicit_generic_requirements(plan):
    """
    Check whether the planner used the newer generic requirement model.

    Examples:
        data_requirements
        required_data
        requirements

    These are intentionally treated as descriptive rather than tied to
    a fixed modality.
    """

    for key in (
        "data_requirements",
        "required_data",
        "requirements",
    ):
        value = plan.get(key)

        if value:
            return True

    return False


def _check_legacy_required_roles(plan, facts, overrides, issues):
    """
    Validate legacy `required_roles` without forcing optical-only behavior.

    Known optical roles retain the old deterministic checks.

    Unknown/custom roles are NOT rejected. They may represent:
        - SAR VV/VH
        - DEM measurements
        - custom sensor bands
        - application-specific measurements
        - future modalities

    The planner is responsible for describing those requirements.
    """

    rasters = _rasters(facts)

    required_roles = plan.get("required_roles") or []

    if not isinstance(required_roles, list):
        issues.append(
            (
                "fix",
                "'required_roles' must be a list when provided.",
            )
        )
        return

    for role in required_roles:

        if not isinstance(role, str) or not role.strip():
            issues.append(
                (
                    "fix",
                    "Each required role must be a non-empty string.",
                )
            )
            continue

        role = role.strip()

        # Explicit user overrides remain authoritative for legacy roles.
        if role in overrides:
            continue

        # IMPORTANT:
        # Do NOT reject arbitrary roles here.
        #
        # Previously this produced:
        #
        #   Unknown band role 'before_VV.tif'.
        #   Use only blue/green/red/nir/...
        #
        # That made the validator optical-only.
        if role not in LEGACY_OPTICAL_ROLES:
            continue

        # Legacy optical validation.
        for name, info in rasters.items():

            entry = (
                info
                .get("band_roles", {})
                .get("roles", {})
                .get(role)
            )

            if not entry:
                continue

            labels = [
                band.get("label") or "(unlabelled)"
                for band in info.get("bands", [])
                if isinstance(band, dict)
            ]

            status = entry.get("status")

            if status == "missing":
                issues.append(
                    (
                        "refuse",
                        (
                            f"'{name}' has no '{role}' band "
                            f"(its band labels: {labels}), "
                            f"which this analysis needs. "
                            f"Provide data with a '{role}' band, "
                            f"or if the bands are unlabelled, "
                            f"tell me which band number is '{role}'."
                        ),
                    )
                )

            elif status == "ambiguous":
                issues.append(
                    (
                        "clarify",
                        (
                            f"'{name}' has several possible "
                            f"'{role}' bands {entry.get('bands')}. "
                            f"Which one should I use?"
                        ),
                    )
                )


def _check_generic_requirements(plan, facts, issues):
    """
    Perform lightweight validation of generic data requirements.

    This does not assume optical/SAR/DEM/etc.

    It only checks requirements that explicitly identify a file and a
    measurement/role and can therefore be verified from dataset metadata.
    """

    rasters = _rasters(facts)

    requirements = None

    for key in (
        "data_requirements",
        "required_data",
        "requirements",
    ):
        value = plan.get(key)

        if isinstance(value, list):
            requirements = value
            break

    if not requirements:
        return

    for requirement in requirements:

        if not isinstance(requirement, dict):
            continue

        filename = (
            requirement.get("file")
            or requirement.get("filename")
            or requirement.get("source")
        )

        role = (
            requirement.get("role")
            or requirement.get("measurement")
            or requirement.get("band")
            or requirement.get("polarization")
        )

        # If the planner did not provide enough metadata to verify the
        # requirement deterministically, leave it to the task coder.
        if not filename or not role:
            continue

        if filename not in rasters:
            # Only raise this when the planner explicitly named a file.
            issues.append(
                (
                    "refuse",
                    (
                        f"The plan requires '{filename}', "
                        f"but that file was not provided."
                    ),
                )
            )
            continue

        status = _find_role_in_raster(
            rasters[filename],
            role,
        )

        if status == "missing":
            labels = _band_labels(rasters[filename])

            issues.append(
                (
                    "refuse",
                    (
                        f"The plan requires '{role}' from "
                        f"'{filename}', but that measurement could "
                        f"not be matched to the dataset bands "
                        f"{labels}."
                    ),
                )
            )

        elif status == "ambiguous":
            issues.append(
                (
                    "clarify",
                    (
                        f"'{filename}' contains multiple possible "
                        f"matches for '{role}'. Specify which band "
                        f"should be used."
                    ),
                )
            )


def _check_temporal_requirement(plan, facts, issues):
    """Validate requirements involving multiple acquisition dates."""

    rasters = _rasters(facts)

    if not plan.get("needs_two_dates"):
        return

    if len(rasters) < 2:
        issues.append(
            (
                "refuse",
                (
                    "This needs two images of the same area from "
                    "different dates; only one raster was provided."
                ),
            )
        )
        return

    dates = [
        date
        for date in facts.get("alignment", {})
        .get("dates", {})
        .values()
        if date
    ]

    if (
        len(dates) == len(rasters)
        and len(set(dates)) == 1
    ):
        issues.append(
            (
                "refuse",
                (
                    "The images have the same acquisition date, "
                    "so there is no change over time to measure."
                ),
            )
        )


def _check_alignment(plan, facts, issues):
    """
    If multiple rasters are on different grids, require explicit
    alignment/reprojection/resampling preprocessing.

    This is modality-independent.
    """

    rasters = _rasters(facts)

    if len(rasters) < 2:
        return

    alignment = facts.get("alignment", {})

    if alignment.get("aligned") is not False:
        return

    preprocessing = " ".join(
        str(step)
        for step in (
            plan.get("preprocessing") or []
        )
    ).lower()

    alignment_words = (
        "align",
        "reproject",
        "resample",
        "warp",
        "common grid",
        "same grid",
    )

    if not any(
        word in preprocessing
        for word in alignment_words
    ):
        differences = alignment.get("differences") or []

        issues.append(
            (
                "fix",
                (
                    "The rasters are not on the same grid "
                    f"({'; '.join(map(str, differences))}). "
                    "Add an alignment step to 'preprocessing' "
                    "(geollm_lib.align.align_to)."
                ),
            )
        )


def check_plan(plan, facts, overrides=None):
    """
    Validate an LLM-generated plan against deterministic dataset facts.

    Returns:
        list[(kind, message)]

    kind:
        refuse   -> data cannot support the requested computation
        clarify  -> user/LLM must resolve ambiguity
        fix      -> planner should correct the plan
    """

    if not isinstance(plan, dict):
        return [
            (
                "fix",
                (
                    "Start your reply with a ```json plan block "
                    "(keys: "
                    + ", ".join(PLAN_KEYS)
                    + "), then a ```python block."
                ),
            )
        ]

    issues = []
    overrides = overrides or {}

    # Required structural fields.
    missing = [
        key
        for key in PLAN_KEYS
        if key not in plan
    ]

    if missing:
        issues.append(
            (
                "fix",
                f"The plan is missing keys: {missing}",
            )
        )

    # Basic type checks.
    if "measures" in plan and not isinstance(
        plan.get("measures"),
        list,
    ):
        issues.append(
            (
                "fix",
                "'measures' must be a list.",
            )
        )

    if "preprocessing" in plan and not isinstance(
        plan.get("preprocessing"),
        list,
    ):
        issues.append(
            (
                "fix",
                "'preprocessing' must be a list.",
            )
        )

    if "outputs" in plan and not isinstance(
        plan.get("outputs"),
        list,
    ):
        issues.append(
            (
                "fix",
                "'outputs' must be a list.",
            )
        )

    # Legacy optical roles, but without optical-only rejection.
    _check_legacy_required_roles(
        plan,
        facts,
        overrides,
        issues,
    )

    # Generic modality-independent requirements.
    _check_generic_requirements(
        plan,
        facts,
        issues,
    )

    # Temporal checks.
    _check_temporal_requirement(
        plan,
        facts,
        issues,
    )

    # Spatial/grid checks.
    _check_alignment(
        plan,
        facts,
        issues,
    )

    return issues
