"""Automatic container resource sizing and host capacity helpers.

Inspects input file sizes, raster/LiDAR headers, and query complexity in <5 ms
to pick an appropriate (Small / Medium / Large) CPU & RAM profile, and provides
an OOM retry escalation helper.
"""
from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


@dataclass(frozen=True)
class ResourceProfile:
    tier: str          # "small" | "medium" | "large"
    memory: str        # e.g. "4g", "8g", "16g"
    memory_gb: float
    cpus: float
    reason: str


def get_host_ram_gb() -> float:
    """Return total physical host RAM in GB without external dependencies."""
    try:
        if sys.platform == "win32":
            class _MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = _MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return max(4.0, round(stat.ullTotalPhys / (1024 ** 3), 1))
        else:
            with open("/proc/meminfo", "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        return max(4.0, round(kb / (1024 ** 2), 1))
    except Exception:
        pass
    return 16.0


def get_host_budget_gb() -> float:
    """Safe total RAM budget across all concurrent containers (~75% of host RAM)."""
    env_override = os.environ.get("GEOLLM_TOTAL_RAM_BUDGET_GB")
    if env_override:
        try:
            return max(4.0, float(env_override))
        except ValueError:
            pass
    host_gb = get_host_ram_gb()
    return max(8.0, round(host_gb * 0.75, 1))


def parse_memory_gb(mem: str) -> float:
    s = str(mem or "8g").strip().lower()
    try:
        if s.endswith("g"):
            return float(s[:-1])
        if s.endswith("m"):
            return float(s[:-1]) / 1024.0
        return float(s)
    except ValueError:
        return 8.0


def _inspect_file_footprint(files: Iterable[str]) -> tuple[float, float, bool, int]:
    """Return (disk_mb, estimated_uncompressed_mb, has_lidar, file_count)."""
    disk_bytes = 0
    uncompressed_mb = 0.0
    has_lidar = False
    count = 0

    for raw in files:
        if not raw:
            continue
        p = Path(raw)
        if not p.is_file():
            continue
        count += 1
        try:
            sz = p.stat().st_size
            disk_bytes += sz
        except OSError:
            continue

        ext = p.suffix.lower()
        if ext in (".las", ".laz", ".xyz"):
            has_lidar = True
            uncompressed_mb += (sz / 1e6) * (6.0 if ext == ".laz" else 1.5)
        elif ext in (".tif", ".tiff"):
            # Fast header-only read when rasterio is available
            est_done = False
            try:
                import rasterio
                with rasterio.open(p) as src:
                    bpp = 4
                    if src.dtypes:
                        dt = str(src.dtypes[0]).lower()
                        if "8" in dt:
                            bpp = 1
                        elif "16" in dt:
                            bpp = 2
                        elif "64" in dt:
                            bpp = 8
                    uncompressed_mb += (src.width * src.height * max(1, src.count) * bpp) / 1e6
                    est_done = True
            except Exception:
                pass
            if not est_done:
                uncompressed_mb += (sz / 1e6) * 4.0
        else:
            uncompressed_mb += sz / 1e6

    return disk_bytes / 1e6, uncompressed_mb, has_lidar, count


_HEAVY_KEYWORDS = (
    "lidar", "point cloud", "pointcloud", "canopy", "3d", "terrain",
    "flow accumulation", "drainage", "watershed", "twi", "sar", "radar",
    "backscatter", "animation", "gif", "random forest", "classify", "clustering",
)


def estimate_job_resources(
    question: str = "",
    files: Optional[Iterable[str]] = None,
    default_memory: str = "8g",
    default_cpus: float = 4.0,
) -> ResourceProfile:
    """Pick Small (4g/2c), Medium (8g/4c), or Large (16g/6-8c) clamped to host hardware."""
    host_cpus = float(os.cpu_count() or 4)
    budget_gb = get_host_budget_gb()
    file_list = list(files or [])
    disk_mb, uncomp_mb, has_lidar, n_files = _inspect_file_footprint(file_list)

    q_low = (question or "").lower()
    is_heavy_query = any(kw in q_low for kw in _HEAVY_KEYWORDS)

    # Tier classification
    if has_lidar or disk_mb > 500.0 or uncomp_mb > 1500.0:
        tier = "large"
        target_gb = min(16.0, budget_gb)
        target_cpus = min(max(4.0, default_cpus), max(2.0, host_cpus - 1.0), 8.0)
        reason = f"large workload ({disk_mb:.0f} MB on disk, ~{uncomp_mb:.0f} MB unpacked" + (", LiDAR)" if has_lidar else ")")
    elif disk_mb < 100.0 and uncomp_mb < 250.0 and n_files <= 4 and not is_heavy_query:
        tier = "small"
        target_gb = min(4.0, budget_gb)
        target_cpus = min(2.0, host_cpus)
        reason = f"lightweight workload ({n_files} file(s), {disk_mb:.1f} MB)"
    else:
        tier = "medium"
        base_gb = parse_memory_gb(default_memory)
        target_gb = min(max(8.0, base_gb), budget_gb)
        target_cpus = min(max(4.0, default_cpus), host_cpus)
        reason = f"standard workload ({n_files} file(s), {disk_mb:.1f} MB" + (", multi-step/heavy op)" if is_heavy_query else ")")

    mem_int = max(2, int(round(target_gb)))
    return ResourceProfile(
        tier=tier,
        memory=f"{mem_int}g",
        memory_gb=float(mem_int),
        cpus=round(float(target_cpus), 1),
        reason=reason,
    )


def next_memory_tier(current_memory: str) -> Optional[str]:
    """Double RAM for OOM retry (4g -> 8g -> 16g -> 24g) capped at host budget."""
    cur_gb = parse_memory_gb(current_memory)
    budget_gb = get_host_budget_gb()
    next_gb = min(budget_gb, cur_gb * 2.0)
    if next_gb <= cur_gb + 0.5:
        return None
    return f"{int(round(next_gb))}g"
