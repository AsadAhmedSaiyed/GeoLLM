"""Infer semantic band roles from a raster's own labels. Never guesses."""
import re

ROLES = ("blue", "green", "red", "nir", "swir1", "swir2")
NAME_TO_ROLE = {
    "blue": "blue", "green": "green", "red": "red", "nir": "nir", "nir08": "nir",
    "swir1": "swir1", "swir16": "swir1", "swir2": "swir2", "swir22": "swir2",
}
# Band codes (B04, B8...) only mean something once the sensor is known.
SENSOR_CODES = {
    "sentinel2": {"B2": "blue", "B3": "green", "B4": "red", "B8": "nir", "B11": "swir1", "B12": "swir2"},
    "landsat": {"B2": "blue", "B3": "green", "B4": "red", "B5": "nir", "B6": "swir1", "B7": "swir2"},
}


class BandError(Exception):
    """A required band is missing or ambiguous. This is a data limitation: never substitute another band."""


def detect_sensor(tags):
    text = " ".join(str(v) for v in (tags or {}).values()).lower()
    if "sentinel" in text:
        return "sentinel2"
    if "landsat" in text:
        return "landsat"
    return None


def _code(label):
    m = re.fullmatch(r"b0*(\d+)(a?)", label)
    return f"B{m.group(1)}{m.group(2).upper()}" if m else None


def label_role(label, sensor=None):
    """Role a band label stands for, or None if it can't be determined."""
    if not label:
        return None
    text = str(label).strip().lower()
    if text in NAME_TO_ROLE:
        return NAME_TO_ROLE[text]
    code = _code(text)
    if code and sensor:
        return SENSOR_CODES[sensor].get(code)
    return None


def infer_roles(labels, tags=None):
    """labels: per-band labels (None allowed). Returns status found/ambiguous/missing per role."""
    sensor = detect_sensor(tags)
    found = {r: [] for r in ROLES}
    for i, lab in enumerate(labels, start=1):
        role = label_role(lab, sensor)
        if role:
            found[role].append(i)
    roles = {}
    for r, bands in found.items():
        status = "found" if len(bands) == 1 else ("ambiguous" if bands else "missing")
        roles[r] = {"status": status, "bands": bands}
    return {"sensor": sensor, "labelled": any(labels), "roles": roles}