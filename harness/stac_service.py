"""
Generic, Query-Agnostic STAC Service for Microsoft Planetary Computer.
Supports all remote sensing modalities:
- Optical Multispectral (Sentinel-2 L2A, Landsat 8/9 C2L2, NAIP, MODIS)
- Synthetic Aperture Radar (Sentinel-1 RTC, Sentinel-1 GRD, ALOS PALSAR)
- Hyperspectral (NASA EMIT L2A Reflectance with nanometer wavelengths)
- Digital Elevation Models (Copernicus DEM GLO-30, NASADEM)
- Land Cover (ESA WorldCover, Dynamic World, io-lulc)
"""
import os
import re
import json
import logging
import asyncio
import time
import urllib.request
import urllib.error
from datetime import date
from pathlib import Path
from typing import List, Dict, Any, Optional

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

logger = logging.getLogger("geollm.stac")

STAC_API_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
SAS_API_URL = "https://planetarycomputer.microsoft.com/api/sas/v1"

ACTIVE_DOWNLOADS: Dict[str, Dict[str, Any]] = {}
DOWNLOAD_TASKS: Dict[str, asyncio.Task] = {}
CANCELLATION_FLAGS: Dict[str, bool] = {}

def register_download_task(stage_id: str, task: asyncio.Task):
    """Register active asyncio.Task for cancellation handling."""
    DOWNLOAD_TASKS[stage_id] = task

def cancel_stac_download(stage_id: str) -> bool:
    """Cancels an in-progress STAC download, deletes partial files, and updates status."""
    CANCELLATION_FLAGS[stage_id] = True
    task = DOWNLOAD_TASKS.get(stage_id)
    if task and not task.done():
        task.cancel()

    if stage_id in ACTIVE_DOWNLOADS:
        dl = ACTIVE_DOWNLOADS[stage_id]
        dl["status"] = "cancelled"
        dl["error"] = "Cancelled by user"
        dl["updated_at"] = time.time()
        dest_path_str = dl.get("path")
        if dest_path_str:
            try:
                p = Path(dest_path_str)
                if p.exists():
                    p.unlink(missing_ok=True)
            except Exception:
                pass
    return True

def get_active_downloads() -> Dict[str, Dict[str, Any]]:
    now = time.time()
    # Prune finished items older than 15 minutes
    to_delete = [k for k, v in ACTIVE_DOWNLOADS.items() if now - v.get("updated_at", now) > 900]
    for k in to_delete:
        ACTIVE_DOWNLOADS.pop(k, None)
    return ACTIVE_DOWNLOADS

def _sync_get_json(url: str, timeout: float = 30.0) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "GeoLLM/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))

def _sync_post_json(url: str, payload: dict, timeout: float = 30.0) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": "GeoLLM/1.0", "Content-Type": "application/json", "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))

def _sync_download(url: str, dest_path: Path, timeout: float = 300.0, progress_callback=None, cancel_check=None):
    req = urllib.request.Request(url, headers={"User-Agent": "GeoLLM/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response, open(dest_path, "wb") as out_f:
        cl = response.headers.get("Content-Length")
        total = int(cl) if cl and cl.isdigit() else None
        downloaded = 0
        last_cb = 0.0
        while True:
            if cancel_check and cancel_check():
                raise asyncio.CancelledError("Download cancelled by user")
            chunk = response.read(65536)
            if not chunk:
                break
            out_f.write(chunk)
            downloaded += len(chunk)
            now = time.time()
            if progress_callback and (now - last_cb > 0.3 or (total and downloaded >= total)):
                progress_callback(downloaded, total)
                last_cb = now
        if progress_callback:
            progress_callback(downloaded, total or downloaded)

async def http_get_json(url: str, timeout: float = 30.0) -> Dict[str, Any]:
    if HAS_HTTPX:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
    return await asyncio.to_thread(_sync_get_json, url, timeout)

async def http_post_json(url: str, payload: dict, timeout: float = 30.0) -> Dict[str, Any]:
    if HAS_HTTPX:
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                err_body = e.response.text
                logger.error(f"HTTP {e.response.status_code} from {url}: {err_body}")
                raise RuntimeError(f"Planetary Computer error ({e.response.status_code}): {err_body}") from e
    return await asyncio.to_thread(_sync_post_json, url, payload, timeout)

async def http_download_file(url: str, dest_path: Path, timeout: float = 300.0, progress_callback=None, cancel_check=None):
    if HAS_HTTPX:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("GET", url) as stream_resp:
                stream_resp.raise_for_status()
                cl = stream_resp.headers.get("content-length")
                total = int(cl) if cl and cl.isdigit() else None
                downloaded = 0
                last_cb = 0.0
                with open(dest_path, "wb") as f:
                    async for chunk in stream_resp.aiter_bytes(chunk_size=65536):
                        if cancel_check and cancel_check():
                            raise asyncio.CancelledError("Download cancelled by user")
                        f.write(chunk)
                        downloaded += len(chunk)
                        now = time.time()
                        if progress_callback and (now - last_cb > 0.3 or (total and downloaded >= total)):
                            progress_callback(downloaded, total)
                            last_cb = now
                if progress_callback:
                    progress_callback(downloaded, total or downloaded)
                return
    await asyncio.to_thread(_sync_download, url, dest_path, timeout, progress_callback, cancel_check)


# Curated catalog categories for UI discovery (dynamic query targets)
COLLECTION_METADATA = {
    "sentinel-2-l2a": {
        "title": "Sentinel-2 Level-2A (Optical)",
        "modality": "optical",
        "description": "Global 10-60m multispectral optical imagery (12 bands: RGB, RedEdge, NIR, SWIR).",
        "recommended_assets": ["visual", "B02", "B03", "B04", "B08", "B11", "B12"],
    },
    "sentinel-1-rtc": {
        "title": "Sentinel-1 RTC (Radar / SAR)",
        "modality": "sar",
        "description": "Radiometrically terrain-corrected 10-20m SAR backscatter (VV, VH polarizations).",
        "recommended_assets": ["vv", "vh"],
    },
    "sentinel-1-grd": {
        "title": "Sentinel-1 GRD (Radar / SAR)",
        "modality": "sar",
        "description": "Ground Range Detected SAR amplitude imagery (VV, VH polarizations).",
        "recommended_assets": ["vv", "vh"],
    },
    "landsat-c2-l2": {
        "title": "Landsat 8/9 Collection 2 Level-2",
        "modality": "optical",
        "description": "Global 30m multispectral surface reflectance and thermal imagery.",
        "recommended_assets": ["red", "green", "blue", "nir08", "swir16", "swir22", "thermal"],
    },
    "emit-l2a-rfl": {
        "title": "NASA EMIT Surface Reflectance (Hyperspectral)",
        "modality": "hyperspectral",
        "description": "285 contiguous spectral bands (381 to 2493 nm) from the ISS imaging spectrometer.",
        "recommended_assets": ["reflectance"],
    },
    "cop-dem-glo-30": {
        "title": "Copernicus DEM GLO-30 (Elevation)",
        "modality": "dem",
        "description": "High-accuracy 30m global digital surface elevation model.",
        "recommended_assets": ["data"],
    },
    "esa-worldcover": {
        "title": "ESA WorldCover 10m (Land Cover)",
        "modality": "landcover",
        "description": "Global 10m land cover map based on Sentinel-1 and Sentinel-2 data.",
        "recommended_assets": ["map"],
    },
}


def get_curated_collections() -> List[Dict[str, Any]]:
    """Returns dynamic discovery list of supported STAC collections."""
    out = []
    for cid, meta in COLLECTION_METADATA.items():
        out.append({
            "id": cid,
            "title": meta["title"],
            "modality": meta["modality"],
            "description": meta["description"],
            "recommended_assets": meta["recommended_assets"],
        })
    return out


def normalize_stac_date(val: Any, default: str) -> str:
    """
    Normalizes any date string (YYYY-MM-DD, DD-MM-YYYY, DD/MM/YYYY, etc.)
    into standard ISO-8601 'YYYY-MM-DD' for STAC API compliance.
    """
    if not val:
        return default
    s = str(val).strip()

    # Match YYYY-MM-DD, YYYY/MM/DD, YYYY.MM.DD
    m_iso = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m_iso:
        y, m, d = int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3))
        try:
            return date(y, m, d).strftime("%Y-%m-%d")
        except ValueError:
            pass

    # Match DD-MM-YYYY, DD/MM/YYYY, MM-DD-YYYY, MM/DD/YYYY
    m_dmy = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", s)
    if m_dmy:
        p1, p2, y = int(m_dmy.group(1)), int(m_dmy.group(2)), int(m_dmy.group(3))
        if p1 > 12 >= p2:
            d, m = p1, p2
        elif p2 > 12 >= p1:
            d, m = p2, p1
        else:
            d, m = p1, p2
        try:
            return date(y, m, d).strftime("%Y-%m-%d")
        except ValueError:
            pass

    # Fallback to python-dateutil if installed
    try:
        from dateutil import parser
        dt = parser.parse(s, dayfirst=True)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        pass

    return default


async def search_stac_items(
    bbox: List[float],
    start_date: str,
    end_date: str,
    collections: Optional[List[str]] = None,
    max_cloud_cover: Optional[float] = None,
    limit: int = 12,
) -> Dict[str, Any]:
    """
    Search Planetary Computer STAC API across any BBOX and temporal range.
    BBOX format: [min_lon, min_lat, max_lon, max_lat]
    Dates: ISO format YYYY-MM-DD
    """
    # 1. Sanitize & Normalize BBox [min_lon, min_lat, max_lon, max_lat]
    if not bbox or len(bbox) != 4:
        bbox = [55.15, 25.05, 55.45, 25.35]
    p1_x, p1_y, p2_x, p2_y = [float(x) for x in bbox]
    min_lon = max(-180.0, min(180.0, min(p1_x, p2_x)))
    max_lon = max(-180.0, min(180.0, max(p1_x, p2_x)))
    min_lat = max(-90.0, min(90.0, min(p1_y, p2_y)))
    max_lat = max(-90.0, min(90.0, max(p1_y, p2_y)))
    if min_lon == max_lon:
        min_lon -= 0.01; max_lon += 0.01
    if min_lat == max_lat:
        min_lat -= 0.01; max_lat += 0.01
    clean_bbox = [round(min_lon, 5), round(min_lat, 5), round(max_lon, 5), round(max_lat, 5)]

    # 2. Sanitize & Normalize Dates (handles DD-MM-YYYY, DD/MM/YYYY, YYYY-MM-DD)
    s_clean = normalize_stac_date(start_date, '2024-04-10')
    e_clean = normalize_stac_date(end_date, '2024-05-20')
    if s_clean > e_clean:
        s_clean, e_clean = e_clean, s_clean
    datetime_param = f"{s_clean}T00:00:00Z/{e_clean}T23:59:59Z"

    # 3. Sanitize Collections & Limit
    if not collections:
        collections = ["sentinel-2-l2a", "sentinel-1-rtc"]
    clean_collections = [str(c).strip() for c in collections if c]
    clean_limit = max(1, min(100, int(limit or 12)))

    search_payload: Dict[str, Any] = {
        "bbox": clean_bbox,
        "datetime": datetime_param,
        "collections": clean_collections,
        "limit": clean_limit,
    }

    # 4. Optional Cloud Cover Filter (only if < 100% and optical collection queried)
    if max_cloud_cover is not None:
        try:
            cloud_val = float(max_cloud_cover)
            if 0.0 <= cloud_val < 100.0:
                if any(c in ["sentinel-2-l2a", "landsat-c2-l2"] for c in clean_collections):
                    search_payload["query"] = {"eo:cloud_cover": {"lte": cloud_val}}
        except (ValueError, TypeError):
            pass

    try:
        data = await http_post_json(f"{STAC_API_URL}/search", search_payload, timeout=30.0)
    except Exception as e:
        logger.error(f"STAC search error: {str(e)}")
        return {"ok": False, "error": f"STAC API query error: {str(e)}", "features": []}

    features = data.get("features", [])

    # Process and normalize items for UI consumption
    normalized_items = []
    for feat in features:
        props = feat.get("properties", {})
        assets = feat.get("assets", {})
        col = feat.get("collection", "")

        # Extract best thumbnail
        thumb_url = None
        if "thumbnail" in assets:
            thumb_url = assets["thumbnail"].get("href")
        elif "rendered_preview" in assets:
            thumb_url = assets["rendered_preview"].get("href")

        # Sign thumbnail if available
        if thumb_url and "blob.core.windows.net" in thumb_url:
            try:
                sign_data = await http_get_json(f"{SAS_API_URL}/sign?href={thumb_url}", timeout=10.0)
                if sign_data.get("msft:expiry") and sign_data.get("href"):
                    thumb_url = sign_data.get("href")
            except Exception:
                pass

        # Filter relevant downloadable assets
        asset_summary = []
        for a_key, a_val in assets.items():
            roles = a_val.get("roles", [])
            a_type = a_val.get("type", "")
            if a_key in ["thumbnail", "rendered_preview"]:
                continue
            if "data" in roles or "overview" in roles or "image/tiff" in a_type or a_key in ["vv", "vh", "visual", "B02", "B03", "B04", "B08", "B11", "reflectance", "data"]:
                asset_summary.append({
                    "key": a_key,
                    "title": a_val.get("title") or a_key,
                    "type": a_type,
                    "description": a_val.get("description", ""),
                })

        normalized_items.append({
            "id": feat.get("id"),
            "collection": col,
            "datetime": props.get("datetime") or props.get("start_datetime"),
            "cloud_cover": props.get("eo:cloud_cover"),
            "platform": props.get("platform"),
            "bbox": feat.get("bbox"),
            "thumbnail": thumb_url,
            "assets": asset_summary,
        })

    return {
        "ok": True,
        "count": len(normalized_items),
        "items": normalized_items,
    }


async def stage_stac_asset(
    collection: str,
    item_id: str,
    asset_key: str,
    output_dir: Path,
    custom_filename: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Signs the STAC asset URL using Microsoft Planetary Computer SAS API,
    downloads the GeoTIFF, and stages it into output_dir (e.g. data/) with live progress tracking.
    """
    stage_id = f"{item_id}_{asset_key}"
    start_t = time.time()
    ACTIVE_DOWNLOADS[stage_id] = {
        "stage_id": stage_id,
        "collection": collection,
        "item_id": item_id,
        "asset_key": asset_key,
        "filename": custom_filename or f"{collection}_{asset_key}.tif",
        "status": "fetching_metadata",
        "downloaded_bytes": 0,
        "total_bytes": 0,
        "percent": 0.0,
        "downloaded_mb": 0.0,
        "total_mb": 0.0,
        "speed_mbps": 0.0,
        "error": None,
        "updated_at": time.time(),
    }

    try:
        item_data = await http_get_json(f"{STAC_API_URL}/collections/{collection}/items/{item_id}", timeout=60.0)
    except Exception as e:
        err = f"Failed to retrieve STAC item {item_id}: {str(e)}"
        ACTIVE_DOWNLOADS[stage_id].update({"status": "failed", "error": err, "updated_at": time.time()})
        return {"ok": False, "error": err}

    assets = item_data.get("assets", {})
    if asset_key not in assets:
        err = f"Asset {asset_key} not found in item {item_id}"
        ACTIVE_DOWNLOADS[stage_id].update({"status": "failed", "error": err, "updated_at": time.time()})
        return {"ok": False, "error": err}

    raw_href = assets[asset_key]["href"]

    # 2. Sign URL with Planetary Computer SAS Token
    try:
        sign_data = await http_get_json(f"{SAS_API_URL}/sign?href={raw_href}", timeout=30.0)
        signed_href = sign_data.get("href", raw_href)
    except Exception:
        signed_href = raw_href

    # 3. Download asset to output_dir
    ext = Path(raw_href.split("?")[0]).suffix or ".tif"
    if custom_filename:
        filename = custom_filename if custom_filename.endswith(ext) else f"{custom_filename}{ext}"
    else:
        dt_str = (item_data.get("properties", {}).get("datetime") or "scene")[:10]
        filename = f"{collection}_{dt_str}_{asset_key}{ext}"

    dest_path = output_dir / filename
    CANCELLATION_FLAGS[stage_id] = False
    ACTIVE_DOWNLOADS[stage_id].update({
        "filename": filename,
        "path": str(dest_path),
        "status": "downloading",
        "updated_at": time.time(),
    })

    def on_progress(downloaded: int, total: Optional[int]):
        now = time.time()
        elapsed = max(now - start_t, 0.1)
        speed = round((downloaded / (1024 * 1024)) / elapsed, 2)
        pct = round((downloaded / total * 100), 1) if total and total > 0 else 0.0
        ACTIVE_DOWNLOADS[stage_id].update({
            "status": "downloading",
            "downloaded_bytes": downloaded,
            "total_bytes": total or 0,
            "percent": pct,
            "downloaded_mb": round(downloaded / (1024 * 1024), 2),
            "total_mb": round(total / (1024 * 1024), 2) if total else 0.0,
            "speed_mbps": speed,
            "updated_at": now,
        })

    def is_cancelled() -> bool:
        return CANCELLATION_FLAGS.get(stage_id, False)

    try:
        if is_cancelled():
            raise asyncio.CancelledError("Download cancelled by user")
        await http_download_file(signed_href, dest_path, timeout=300.0, progress_callback=on_progress, cancel_check=is_cancelled)
        if is_cancelled():
            raise asyncio.CancelledError("Download cancelled by user")

        size_mb = round(dest_path.stat().st_size / (1024 * 1024), 2)
        ACTIVE_DOWNLOADS[stage_id].update({
            "status": "completed",
            "percent": 100.0,
            "downloaded_mb": size_mb,
            "total_mb": size_mb,
            "filename": filename,
            "path": str(dest_path),
            "updated_at": time.time(),
        })
        return {
            "ok": True,
            "filename": filename,
            "path": str(dest_path),
            "size_mb": size_mb,
            "collection": collection,
            "item_id": item_id,
            "asset_key": asset_key,
        }
    except asyncio.CancelledError:
        if dest_path.exists():
            dest_path.unlink(missing_ok=True)
        ACTIVE_DOWNLOADS[stage_id].update({
            "status": "cancelled",
            "error": "Cancelled by user",
            "updated_at": time.time(),
        })
        return {"ok": False, "cancelled": True, "error": "Cancelled by user"}
    except Exception as e:
        if dest_path.exists():
            dest_path.unlink(missing_ok=True)
        err = f"Download exception: {str(e)}"
        ACTIVE_DOWNLOADS[stage_id].update({
            "status": "failed",
            "error": err,
            "updated_at": time.time(),
        })
        return {"ok": False, "error": err}


