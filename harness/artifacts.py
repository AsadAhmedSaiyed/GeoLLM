"""Artifacts as first-class objects: path + type + metadata (never pixel data)."""
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import rasterio

TYPES = {".tif": "raster", ".tiff": "raster", ".geojson": "vector", ".gpkg": "vector", ".shp": "vector",
         ".png": "image", ".jpg": "image", ".json": "json", ".csv": "table", ".txt": "text", ".md": "text"}


@dataclass
class Artifact:
    name: str
    rel: str
    type: str
    source_task: str
    created: float
    meta: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


def _meta(path, kind):
    try:
        if kind == "raster":
            with rasterio.open(path) as s:
                return {"crs": s.crs.to_string() if s.crs else None, "shape": [s.height, s.width], "bands": s.count,
                        "resolution": list(s.res), "bounds": list(s.bounds), "dtype": s.dtypes[0]}
        if kind == "vector" and path.suffix.lower() == ".geojson":
            d = json.loads(path.read_text())
            feats = d.get("features", [])
            return {"features": len(feats), "geometry_types": sorted({f["geometry"]["type"] for f in feats if f.get("geometry")})}
        if kind == "image":
            from matplotlib import image as mpimg
            a = mpimg.imread(str(path))
            return {"shape": list(a.shape[:2])}
        if kind == "table":
            return {"bytes": path.stat().st_size}
    except Exception as e:
        return {"unreadable": str(e)}
    return {}


def collect(output_dir, task_id):
    """Describe every file in a task's output folder."""
    out_dir, arts = Path(output_dir), []
    for p in sorted(out_dir.rglob("*")):
        if p.is_file():
            kind = TYPES.get(p.suffix.lower(), "text")
            arts.append(Artifact(p.name, p.relative_to(out_dir).as_posix(), kind, task_id, time.time(), _meta(p, kind)))
    return arts