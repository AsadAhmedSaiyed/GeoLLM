"""CLI bridge for Pi agent STAC discovery & preview tools (`search_stac`, `propose_stac_scenes`)."""
import asyncio
import json
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.stac_service import (  # noqa: E402
    SAS_API_URL,
    STAC_API_URL,
    geocode_location,
    http_get_json,
    search_stac_items,
)


def _estimate_native_grid(bbox: list, collections: list) -> dict:
    """Estimate pixel width/height at native resolution for the given WGS84 bbox."""
    if not bbox or len(bbox) < 4:
        return {}
    w_lon, s_lat, e_lon, n_lat = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
    mid_lat_rad = math.radians((s_lat + n_lat) / 2.0)
    width_m = abs(e_lon - w_lon) * 111320.0 * max(0.1, math.cos(mid_lat_rad))
    height_m = abs(n_lat - s_lat) * 110574.0
    area_km2 = round((width_m * height_m) / 1e6, 2)

    is_30m = all(c in ("landsat-c2-l2", "cop-dem-glo-30", "nasadem", "alos-dem") for c in (collections or []))
    native_res_m = 30.0 if is_30m else 10.0
    est_w = max(1, int(round(width_m / native_res_m)))
    est_h = max(1, int(round(height_m / native_res_m)))
    total_px = est_w * est_h
    max_safe_px = 36_000_000
    return {
        "area_km2": area_km2,
        "native_resolution_m": native_res_m,
        "estimated_width_px": est_w,
        "estimated_height_px": est_h,
        "estimated_total_pixels": total_px,
        "within_memory_limit": total_px <= max_safe_px,
        "memory_note": (
            f"OK ({est_w}x{est_h} px at {int(native_res_m)}m native resolution fits safely in RAM)."
            if total_px <= max_safe_px
            else (
                f"WARNING: AOI is {est_w}x{est_h} px ({total_px:,} px) at {int(native_res_m)}m native resolution, "
                f"exceeding the {max_safe_px:,} px safe RAM cap. Narrow the bbox or use a 30m collection (landsat-c2-l2)."
            )
        ),
    }


async def _handle_search(payload: dict) -> dict:
    bbox = payload.get("bbox")
    location_name = (payload.get("location_name") or "").strip()
    geocoded_info = None

    if (not bbox or len(bbox) < 4) and location_name:
        geo = await geocode_location(location_name)
        if not geo.get("ok"):
            return {
                "ok": False,
                "error": (
                    f"Could not geocode '{location_name}': {geo.get('error')}. "
                    "Please provide an explicit `bbox: [min_lon, min_lat, max_lon, max_lat]`."
                ),
            }
        bbox = geo["bbox"]
        geocoded_info = geo

    if not bbox or len(bbox) < 4:
        return {
            "ok": False,
            "error": "Provide either `bbox: [min_lon, min_lat, max_lon, max_lat]` or `location_name`.",
        }

    collections = payload.get("collections") or ["sentinel-2-l2a"]
    start_date = payload.get("start_date") or "2024-01-01"
    end_date = payload.get("end_date") or "2024-12-31"
    max_cloud_cover = payload.get("max_cloud_cover")
    limit = payload.get("limit") or 12

    res = await search_stac_items(
        bbox=bbox,
        start_date=start_date,
        end_date=end_date,
        collections=collections,
        max_cloud_cover=max_cloud_cover,
        limit=limit,
    )
    res["bbox"] = bbox
    if geocoded_info:
        res["geocoded_location"] = geocoded_info
    res["native_grid_estimate"] = _estimate_native_grid(bbox, collections)
    return res


SCIENTIFIC_REQUIRED_ASSETS = {
    "sentinel-2-l2a": ["B02", "B03", "B04", "B08", "B11", "B12", "SCL"],
    "landsat-c2-l2": ["blue", "green", "red", "nir08", "swir16", "swir22", "qa_pixel"],
    "sentinel-1-rtc": ["vv", "vh"],
    "sentinel-1-grd": ["vv", "vh"],
    "cop-dem-glo-30": ["data"],
    "esa-worldcover": ["map"],
}


async def _handle_propose_preview(payload: dict) -> dict:
    run_dir_str = os.environ.get("GEOLLM_RUN_DIR")
    if not run_dir_str:
        return {"ok": False, "error": "GEOLLM_RUN_DIR is not set"}

    run_dir = Path(run_dir_str)
    bbox = payload.get("bbox")
    scenes = payload.get("scenes") or []
    explanation = payload.get("explanation") or ""
    location_name = payload.get("location_name") or ""

    if not bbox or len(bbox) < 4:
        return {"ok": False, "error": "`bbox` ([min_lon, min_lat, max_lon, max_lat]) is required."}
    if not scenes:
        return {"ok": False, "error": "At least one scene must be provided in `scenes`."}

    enriched_scenes = []
    collections_used = []
    for sc in scenes:
        col = sc.get("collection") or "sentinel-2-l2a"
        collections_used.append(col)
        item_id = sc.get("item_id") or sc.get("id")
        req_assets = list(sc.get("assets") or [])
        base_assets = SCIENTIFIC_REQUIRED_ASSETS.get(col, ["B04", "B03", "B02", "B08"])
        assets = []
        for a in req_assets + base_assets:
            if a and a not in assets:
                assets.append(a)

        thumb = sc.get("thumbnail")
        dt = sc.get("datetime")
        cloud = sc.get("cloud_cover")
        cov = sc.get("aoi_coverage_pct")
        nodata = sc.get("nodata_pct")
        item_assets = {}

        # Fetch & sign thumbnail/metadata if missing
        if item_id and (not thumb or dt is None or cov is None):
            try:
                item_data = await http_get_json(f"{STAC_API_URL}/collections/{col}/items/{item_id}", timeout=20.0)
                props = item_data.get("properties", {})
                item_assets = item_data.get("assets", {}) or {}
                if not dt:
                    dt = props.get("datetime") or props.get("start_datetime")
                if cloud is None:
                    cloud = props.get("eo:cloud_cover")
                if nodata is None and props.get("s2:nodata_pixel_percentage") is not None:
                    nodata = round(float(props["s2:nodata_pixel_percentage"]), 1)
                if cov is None:
                    geom = item_data.get("geometry")
                    if geom:
                        try:
                            from shapely.geometry import box as shapely_box, shape as shapely_shape
                            aoi_poly = shapely_box(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
                            feat_poly = shapely_shape(geom)
                            if not feat_poly.is_valid:
                                feat_poly = feat_poly.buffer(0)
                            if aoi_poly.area > 0:
                                cov = round(min(100.0, (aoi_poly.intersection(feat_poly).area / aoi_poly.area) * 100.0), 1)
                        except Exception:
                            pass
                if not thumb:
                    if "rendered_preview" in item_assets:
                        thumb = item_assets["rendered_preview"].get("href")
                    elif "thumbnail" in item_assets:
                        thumb = item_assets["thumbnail"].get("href")
            except Exception:
                pass

        if item_assets:
            filtered = [a for a in assets if a in item_assets]
            if filtered:
                assets = filtered

        if thumb and "blob.core.windows.net" in thumb and "sig=" not in thumb:
            try:
                sign_data = await http_get_json(f"{SAS_API_URL}/sign?href={thumb}", timeout=10.0)
                if sign_data.get("href"):
                    thumb = sign_data["href"]
            except Exception:
                pass

        enriched_scenes.append({
            "collection": col,
            "item_id": item_id,
            "label": sc.get("label") or f"{col} ({(dt or '')[:10]})",
            "datetime": dt or "Unknown date",
            "assets": assets,
            "thumbnail": thumb,
            "cloud_cover": round(float(cloud), 1) if cloud is not None else None,
            "aoi_coverage_pct": round(float(cov), 1) if cov is not None else None,
            "nodata_pct": nodata,
        })

    if not payload.get("allow_partial_coverage"):
        date_counts = {}
        for es in enriched_scenes:
            d_key = str(es.get("datetime") or "")[:10]
            date_counts[d_key] = date_counts.get(d_key, 0) + 1
        low_cov = [
            es for es in enriched_scenes
            if es.get("aoi_coverage_pct") is not None
            and float(es["aoi_coverage_pct"]) < 50.0
            and date_counts.get(str(es.get("datetime") or "")[:10], 1) == 1
        ]
        if low_cov:
            bad_desc = ", ".join(f"{x['item_id']} ({x['aoi_coverage_pct']}% AOI coverage)" for x in low_cov)
            return {
                "ok": False,
                "error": (
                    f"Insufficient AOI coverage in proposed scene(s): {bad_desc}. "
                    "A single scene covering less than 50% of the requested bbox will leave over half the map empty. "
                    "Please select a pass with higher `aoi_coverage_pct` (>= 75%), adjust the bbox to match the study target, "
                    "or include the adjacent tile from the same date."
                ),
            }

    grid_est = _estimate_native_grid(bbox, collections_used)
    if not grid_est.get("within_memory_limit", True):
        return {
            "ok": False,
            "error": grid_est.get("memory_note"),
            "native_grid_estimate": grid_est,
        }

    preview_doc = {
        "explanation": explanation,
        "location_name": location_name,
        "bbox": [round(float(x), 5) for x in bbox[:4]],
        "native_grid_estimate": grid_est,
        "scenes": enriched_scenes,
    }
    (run_dir / "stac_preview.json").write_text(json.dumps(preview_doc, indent=2), encoding="utf-8")
    return {
        "ok": True,
        "message": (
            "STAC satellite preview card submitted to user. "
            "Waiting for user approval or feedback. Do NOT call any further tools until the user responds."
        ),
        "preview": preview_doc,
    }


async def _amain():
    action = sys.argv[1] if len(sys.argv) > 1 else "search"
    raw = sys.stdin.read().strip()
    payload = json.loads(raw) if raw else {}
    if action == "search":
        res = await _handle_search(payload)
    elif action == "propose_preview":
        res = await _handle_propose_preview(payload)
    else:
        res = {"ok": False, "error": f"Unknown action: {action}"}
    sys.stdout.write(json.dumps(res, default=str) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(_amain())

