# GeoLLM — Time Series & Classification Implementation Plan

> **STATUS: PLAN ONLY — no source code, config, Docker, library, prompt, or
> frontend file has been created, edited, moved, or deleted.**
>
> File: `docs/plans/timeseries_classification_plan.md`
> Written: 2026-10-27 — READ-ONLY inventory, then design.

---

## STEP 1 — INVENTORY

All claims below were verified by opening the cited file and line.

### 1.1 `lib/geollm_lib/` — Every Public Function

| Helper | File | Signature | What it does | Reusable: time series? | Reusable: classification? |
|---|---|---|---|---|---|
| `acquisition_date` | `temporal.py:13` | `(path) → datetime\|None` | Reads TIFF tags for date | **YES** — core date parser | No |
| `order_by_date` | `temporal.py:27` | `(paths) → list[(path,dt)]` | Sorts files by acquisition date | **YES** — sort N scenes | No |
| `index_stack` | `temporal.py:36` | `(paths, name) → (T×H×W ndarray, dates)` | Stacks a named spectral index over ordered scenes; all T loaded at once | **PARTIAL** — must wrap with chunked loader | No |
| `trend_per_year` | `temporal.py:51` | `(stack, dates) → float32 H×W` | Per-pixel OLS slope | **YES** — one of three trend methods | No |
| `anomaly_zscore` | `temporal.py:68` | `(stack) → float32 H×W` | Z-score of last date vs. earlier mean/std | **PARTIAL** — static z-score only; no seasonal baseline | No |
| `change_magnitude` | `temporal.py:78` | `(a, b) → float32` | `b − a` | **PARTIAL** — 2-date only | No |
| `index_difference` | `change.py:18` | `(before_src, after_src, name) → (b, a, diff)` | Index diff between two dates | No | No |
| `significant_change` | `change.py:25` | `(diff, direction, n_std, abs_threshold) → (mask, cutoff)` | Threshold a difference raster | No | No |
| `INDEX_DEFS` | `indices.py:32` | dict of 8 spectral indices | Index definitions | No | No |
| `compute_index` | `indices.py:48` | `(name, src, bands) → float32` | Computes one named index from open raster | **YES** — inside per-scene loop | No |
| `describe_indices` | `indices.py:44` | `() → dict` | Returns index descriptions | No | No |
| `same_grid` | `align.py:20` | `(a, b) → bool` | CRS+shape+transform match | **YES** — pre-stack check | **YES** — label vs. image check |
| `align_to` | `align.py:26` | `(ref, other_path, out_path, resampling) → str` | Warp other onto ref grid | **YES** — align multi-date scenes | **YES** — align label raster |
| `gdal_info` | `align.py:68` | `(path) → dict` | `gdalinfo -json` wrapper | **YES** | **YES** |
| `gdal_warp` | `align.py:73` | `(sources, dst_path, crs, resolution, resampling) → str` | gdalwarp wrapper | **YES** | **YES** |
| `gdal_mosaic` | `align.py:94` | `(sources, dst_path, resampling) → str` | gdal_warp alias for mosaic | No | No |
| `valid_mask` | `masks.py:6` | `(*arrays) → bool ndarray` | Finite pixels across arrays | **YES** | **YES** |
| `select_extreme` | `masks.py:10` | `(arr, fraction, keep) → (mask, cutoff)` | Top/bottom fraction | No | No |
| `threshold_mask` | `masks.py:25` | `(arr, value, keep) → bool ndarray` | Value threshold | **YES** — anomaly masking | No |
| `combine` | `masks.py:32` | `(masks, op) → bool ndarray` | Boolean mask combination | **YES** | **YES** |
| `area_stats` | `masks.py:47` | `(mask, src, valid) → dict` | Pixel count, %, ha | **YES** — per-date water/crop area | No |
| `filter_small` | `masks.py:67` | `(mask, min_pixels) → bool ndarray` | Remove small patches | No | No |
| `region_summary` | `masks.py:78` | `(mask, top) → dict` | Connected region stats | No | No |
| `quadrant_summary` | `masks.py:86` | `(mask) → dict` | Share per quadrant | No | No |
| `distance_to_mask` | `masks.py:94` | `(mask, src) → float32` | Distance transform | No | No |
| `label_regions` | `masks.py:100` | `(mask) → (label_arr, n)` | Connected-component labels | No | **YES** — post-processing |
| `zonal_stats` | `vector.py:48` | `(arr, zones, src, max_zones) → list[dict]` | Mean/min/max per polygon | **YES** — area-average series | No |
| `rasterize_vector` | `vector.py:39` | `(gdf, src) → bool ndarray` | Vector → raster mask | No | **YES** — rasterize label polygons |
| `read_vector` | `vector.py:35` | `(path) → GeoDataFrame` | Read GeoJSON/GPKG | No | **YES** — read training labels |
| `mask_to_geojson` | `vector.py:17` | `(mask, src, path, min_pixels, max_features) → int` | Polygonize boolean mask | No | **YES** — class polygon export |
| `spatial_join` | `vector.py:97` | `(left, right, how, predicate) → GDF` | Spatial join | No | **YES** |
| `buffer_vector` | `vector.py:73` | `(gdf, distance_m) → GDF` | Buffer geometries | No | **YES** — exclusion zone for spatial split |
| `write_geojson` | `vector.py:68` | `(gdf, path) → None` | Save to WGS84 GeoJSON | No | **YES** |
| `area_hectares` | `vector.py:109` | `(gdf) → float` | Total area in ha | No | No |
| `raster_stats` | `stats.py:4` | `(arr) → dict` | Percentile stats of 2D array | **YES** — per-date summary | No |
| `save_map` | `viz.py:9` | `(arr, path, title, cmap, vmin, vmax) → None` | Continuous map + colorbar | **YES** — trend map, anomaly map | **YES** — confidence map |
| `save_mask_map` | `viz.py:20` | `(mask, path, title, background, color, label) → None` | Boolean mask map | **YES** — change-point/anomaly map | No |
| `save_class_map` | `viz.py:36` | `(classes, path, title, labels) → None` | Integer class raster map; 5-colour hardcoded palette | No | **PARTIAL** — palette only 5 colours |
| `read_band` | `io.py:12` | `(src, index) → float32` | Read one raster band | **YES** | **YES** |
| `read_role` | `io.py:60` | `(src, role) → float32` | Read band by semantic role | **YES** | **YES** |
| `write_raster` | `io.py:64` | `(path, arr, src, nodata) → None` | Save 2D array as GeoTIFF | **YES** | **YES** |
| `band_for` | `io.py:41` | `(src, role) → int` | Band number from role name | **YES** | **YES** |
| `inspect_geotiff` | `metadata.py:34` | `(path) → dict` | Full raster metadata dict | **YES** | **YES** |
| `inspect_dataset` | `metadata.py:102` | `(paths) → dict` | Multi-file metadata + alignment | **YES** | **YES** |
| `backscatter_db` | `sar.py:25` | `(src, pol) → float32` | SAR backscatter in dB | **YES** — SAR time series | No |
| `speckle_filter` | `sar.py:34` | `(arr, size) → float32` | Boxcar speckle filter | **YES** — pre-processing | No |
| `db_change` | `sar.py:50` | `(before_db, after_db) → float32` | dB difference | No | No |
| `flood_candidate_mask` | `sar.py:55` | `(before_db, after_db, drop_db, max_after_db) → (mask, cutoffs)` | SAR flood screen | No | No |
| `band_wavelengths` | `hyperspectral.py:27` | `(src) → (wl_nm, unit_source)` | Wavelengths from metadata | No | **YES** — hyperspectral features |
| `spectral_signature` | `hyperspectral.py:83` | `(src, mask) → (wl, means)` | Mean spectrum per mask | No | **YES** — feature extraction |
| `spectral_angle` | `hyperspectral.py:95` | `(src, reference, max_values) → float32` | SAM angle | No | **YES** — similarity feature |
| `save_result` | `result.py:14` | `(data) → None` | Write result.json | **YES** | **YES** |
| `output_path` | `result.py:20` | `(name) → str` | Output file path | **YES** | **YES** |
| `input_path` | `result.py:26` | `(name) → str` | Input file path | **YES** | **YES** |
| `prior_path` | `result.py:31` | `(task_id, name) → str` | Prior task output path | **YES** | **YES** |

### 1.2 Harness Layer

| Component | File | Key details |
|---|---|---|
| `Config` dataclass | `pi_config.py:13` | Frozen; `sandbox_timeout_s=180`, `sandbox_memory="4g"`, `max_tool_calls=8`, `sandbox_cpus=4.0` |
| `load_config()` | `pi_config.py:38` | All keys from env-vars via `_f(name, default)` pattern |
| `solve()` | `pi_harness.py:88` | Top-level driver; calls `inspect_dataset`, `_build_prompt`, `PiRPC` |
| `_build_prompt()` | `pi_harness.py:43` | `Template(pi_prompt.md).substitute(...)` — inserts `api_overview`, `knowledge`, `facts`, `question` |
| `TaskManager` | `orchestrator.py:1` | Max 3 concurrent slots; SSE event fan-out; `TaskState` dataclass |
| `run_code()` | `executor.py:43` | One Docker container per call; `timeout`, `memory`, `cpus` from caller |
| `main()` in docker_runner | `docker_runner.py:222` | Preflight AST → `run_code` → `_validate` → JSON to stdout |
| `_validate()` | `docker_runner.py:70` | Exit-code + result.json summary + artifact presence checks |
| `validate()` | `validator.py:39` | AST policy; `ALLOWED_IMPORTS` at line 4; `BANNED_CALLS` at line 7 |
| `ALLOWED_IMPORTS` | `validator.py:4` | `{"numpy","scipy","pandas","rasterio","geopandas","shapely","matplotlib","geollm_lib","json","math","pathlib","datetime","collections","itertools","statistics","warnings","typing","functools","re"}` |
| `check_outputs()` | `numerical_check.py:79` | Raster/mask/PNG/GeoJSON checks; `BOUNDED` at line 9, `LOOSE` at line 10 |
| `check_result()` | `result_check.py:20` | Structural checks on result.json; `FILE_EXT`, `RELATIVE` at lines 5-6 |
| `check_images()` | `visual_check.py:8` | LLM vision of up to 3 PNGs |
| `check_requirements()` | `final_check.py:10` | Requirement satisfaction check |
| `signatures()` | `api_doc.py:39` | AST-derived API; `MODULES` tuple at line 7 = `("io","bands","indices","masks","vector","align","change","viz","stats","result","sar","hyperspectral","temporal")` |
| `lookup_docs()` | `doc_lookup.py:40` | Context7 fetch; `DOCKER_INSTALLED_PACKAGES` dict at lines 18-31 |
| `KNOWLEDGE` | `prompts.py:1` | Domain-knowledge block injected into planner |
| `PLANNER` | `prompts.py:99` | Planner system prompt |
| `CODER` | `prompts.py:271` | Coder system prompt; allowed imports listed at line 343 |

### 1.3 Docker Sandbox — Exact Package Inventory

Source: `docker/Dockerfile` (9 lines, opened and read in full).

```
FROM python:3.11-slim
RUN apt-get install gdal-bin        # CLI only — no Python osgeo module
RUN pip install numpy scipy pandas rasterio geopandas shapely pyogrio matplotlib
```

Cross-checked against `doc_lookup.py:18-31` (`DOCKER_INSTALLED_PACKAGES`):

| Package | Installed | Version |
|---|---|---|
| numpy | **YES** | 2.4.6 |
| scipy | **YES** | 1.17.1 |
| pandas | **YES** | 3.0.6 |
| rasterio | **YES** | 1.4.4 |
| geopandas | **YES** | 1.2.0 |
| shapely | **YES** | 2.2.0 |
| pyogrio | **YES** | 0.13.0 |
| pyproj | **YES** | 3.7.2 (geopandas dep) |
| matplotlib | **YES** | 3.11.2 |
| pillow | **YES** | 12.3.0 |
| affine | **YES** | 3.0.1 |
| contourpy | **YES** | 1.3.3 |
| **scikit-learn** | **NO** | blocked by `doc_lookup.py:52-58` |
| **statsmodels** | **NO** | not in Dockerfile or whitelist |
| **pymannkendall** | **NO** | not in Dockerfile or whitelist |
| **ruptures** | **NO** | not in Dockerfile or whitelist |
| **seaborn** | **NO** | not in Dockerfile or whitelist |
| torch / tensorflow / cv2 | **NO** | not installed |
| Python gdal (osgeo) | **NO** | only CLI gdal-bin |

**Network:** `network_mode="none"` confirmed at `executor.py:88`. Runtime `pip install` is impossible.

**Consequence:** Any new capability must be implemented using only the installed stack:
- `scikit-learn` models → Phase 3 requires a new Docker image (no network, so must be in the image)
- Mann-Kendall trend test → implemented from scratch using `scipy.stats.kendalltau` (installed)
- Sen's slope → implemented as numpy median of pairwise slopes
- Change-point detection → CUSUM via numpy; Pettitt via scipy.stats
- All of these are possible without any new package in Phases 1 and 2.

### 1.4 Config Mechanism

Single location: **`harness/pi_config.py`**. All values are read from environment variables via `_f(name, default)` at line 9. No `.env` file loader, no YAML parser, no second config file found in any harness file. `Config` is a frozen dataclass (line 13). The existing mechanism is the one to reuse.

### 1.5 API Registration (confirmed by running `signatures()`)

Confirmed registered modules: `['align', 'bands', 'change', 'hyperspectral', 'indices', 'io', 'masks', 'result', 'sar', 'stats', 'temporal', 'vector', 'viz']`

Source: `harness/api_doc.py:7`, `MODULES` tuple. New modules must be added to this tuple for the agent to see them via API lookup.

---

## STEP 2 — NO-DUPLICATION CHECK

### Time Series

| Capability | Status | Evidence |
|---|---|---|
| Load many dates | **PARTIAL** | `order_by_date` + `index_stack` at `temporal.py:27,36`; loads all T at once — chunked version missing |
| Date parsing/ordering | **EXISTS** | `temporal.py:13,27` |
| Regular resampling to fixed grid | **MISSING** | Nowhere in codebase |
| Gap filling (interpolation) | **MISSING** | Nowhere in codebase |
| Harmonic/seasonal decomposition | **MISSING** | Nowhere in codebase |
| Seasonal baseline (same period across years) | **MISSING** | `anomaly_zscore` at `temporal.py:68` groups all prior dates flat, not by calendar period |
| Non-parametric trend test (Mann-Kendall, Sen's slope) | **MISSING** | Nowhere; only OLS at `temporal.py:51` |
| OLS trend per pixel | **EXISTS** | `temporal.py:51` |
| Z-score anomaly (static baseline) | **EXISTS** | `temporal.py:68` |
| Change-point detection | **MISSING** | Nowhere in codebase |
| Forecasting/extrapolation | **MISSING** | Nowhere in codebase |
| Per-pixel vectorized operations | **PARTIAL** | `trend_per_year` uses broadcasting; no generic wrapper |
| Chunked/memory-safe processing | **MISSING** | `index_stack` loads all T into RAM |
| Zonal/area-average series (scalar per zone, per date) | **PARTIAL** | `zonal_stats` at `vector.py:48` handles one raster at a time; no temporal loop |
| Multi-variable/lag features | **MISSING** | Nowhere in codebase |

### Classification

| Capability | Status | Evidence |
|---|---|---|
| Feature building (band stack → X matrix) | **MISSING** | Nowhere |
| Sampling raster at points | **MISSING** | `zonal_stats` at `vector.py:48` does polygon means, not point samples |
| Sampling raster at polygons (flat arrays) | **PARTIAL** | `zonal_stats` returns summary stats, not flat pixel arrays; `rasterize_vector` at `vector.py:39` exists |
| Label reading from vector column | **MISSING** | No label-column API anywhere |
| Class-name handling (int → str map) | **MISSING** | `save_class_map` takes labels dict but no builder/validator |
| Spatial train/test split | **MISSING** | Nowhere |
| Model fitting | **MISSING** | scikit-learn not installed; scipy kmeans2 available but no wrapper |
| Confusion matrix, precision/recall/F1 | **MISSING** | No sklearn; no custom implementation |
| Class map prediction in chunks | **MISSING** | Nowhere |
| Confidence/probability map | **MISSING** | Nowhere |
| Unknown-class handling | **MISSING** | Nowhere |
| Saving model + metadata | **MISSING** | Nowhere |

### Visualization

| Capability | Status | Evidence |
|---|---|---|
| Continuous map (colorbar) | **EXISTS** | `viz.py:9` `save_map` |
| Boolean mask map | **EXISTS** | `viz.py:20` `save_mask_map` |
| Class map (N classes) | **PARTIAL** | `viz.py:36` `save_class_map` — 5-colour palette hardcoded at line 38 |
| Time series line plot | **MISSING** | Nowhere |
| Decomposition panel | **MISSING** | Nowhere |
| Seasonal plot | **MISSING** | Nowhere |
| Anomaly band plot | **MISSING** | Nowhere |
| Change-point plot | **MISSING** | Nowhere |
| Forecast plot | **MISSING** | Nowhere |
| Trend map | **PARTIAL** | `save_map` can render slope array; no title/unit helper |
| Confusion matrix heatmap | **MISSING** | Nowhere |
| Feature importance chart | **MISSING** | Nowhere |
| Confidence map | **MISSING** | Nowhere |
| Class legend for N > 5 classes | **MISSING** | `save_class_map` cycles palette of 5 |

### Validation

| Capability | Status | Evidence |
|---|---|---|
| Multi-class raster (>2 unique values) | **MISSING** | `numerical_check.py:100` accepts only `{0,1,255}` as mask; other integer rasters treated as continuous float |
| Baseline present check | **MISSING** | Nowhere |
| Confusion matrix in result.json | **MISSING** | Nowhere |
| Direction-vs-sign consistency (shrinking = negative slope) | **MISSING** | Nowhere |
| Units present check | **MISSING** | Nowhere |

---

## STEP 3 — HARDCODING AUDIT (report only — do NOT fix)

| Hardcoded value | Location | Effect on new features | Workaround without touching existing code |
|---|---|---|---|
| `BOUNDED = ("ndvi","ndmi","nbr","ndwi","mndwi","ndbi")` | `numerical_check.py:9` | Substring match on filename; trend or anomaly TIFFs with these strings get [-1,1] range check — will falsely flag slope rasters | Name new outputs without those substrings: `trend_slope.tif`, not `ndvi_slope.tif` |
| `LOOSE = ("evi","savi")` | `numerical_check.py:10` | Same substring plausibility check | Same naming strategy |
| `{0, 1, 255}` mask detection | `numerical_check.py:100` | Multi-class integer rasters bypass mask branch, treated as float | New validator function in new file `ts_validator.py`; existing `check_outputs` untouched |
| 5-colour palette `["#1a9850","#d73027","#4575b4","#fdae61","#762a83"]` | `viz.py:38` | Only 5 classes supported; 6th wraps silently | New `save_classmap_n()` in new `viz_ts.py`; does NOT call `save_class_map`; generates HSV palette for N |
| `sandbox_timeout_s=180` | `pi_config.py:47` | Long TS jobs time out | New env-var `GEOLLM_TS_SANDBOX_TIMEOUT_S`; additive new field in Config |
| `sandbox_memory="4g"` | `pi_config.py:48` | Large stacks OOM | New env-var `GEOLLM_TS_SANDBOX_MEMORY`; additive new field |
| `MODULES = (...)` | `api_doc.py:7` | New modules invisible to agent | **Unavoidable edit**: append new names to tuple. Existing modules unchanged |
| `DOCKER_INSTALLED_PACKAGES` dict | `doc_lookup.py:18` | New packages blocked by whitelist | **Deferred to Phase 3** after Docker rebuild: add entries. Existing entries unchanged |
| `OK_PREFIXES = ("/workspace", "/tmp")` | `validator.py:10` | Fine; new modules write to `/workspace/output` | No action needed |
| `atol=1e-6` grid check | `temporal.py:44` | Strict; misaligned scenes raise error | New `load_series` calls `align_to` first if `same_grid` fails |
| `max_zones=500` | `vector.py:52` | Limits zonal stats to 500 zones | New `zonal_series` passes caller-supplied limit |

---

## STEP 4 — THE PLAN

---

### A. Summary

Two additive feature sets — **time series analysis** and **classification** — are implemented using only new Python files in `lib/geollm_lib/` and a new prompt-addition file. The only edits to existing files are: (1) appending module names to the `MODULES` tuple in `api_doc.py` (2 lines added, nothing removed or changed); (2) appending two env-var config fields to `pi_config.py` (4 lines added); (3) a 5-line conditional injection in `pi_harness.py`; and (4) a 3-line append call in `docker_runner.py`. All changes are additive and backward-compatible. Existing queries, prompts, outputs, and SSE events are unchanged. The plan is four independently shippable and revertible phases. scikit-learn (Phase 3) requires a new Docker image tag that coexists with the original image.

**What stays byte-for-byte unchanged:** all existing `geollm_lib` function signatures and outputs; `harness/prompts.py`; `harness/pi_prompt.md`; `harness/docker_runner.py` logic (append only); `harness/executor.py`; `harness/validator.py`; `harness/numerical_check.py`; `harness/result_check.py`; `harness/visual_check.py`; `harness/final_check.py`; `docker/Dockerfile`; all frontend files; all existing Config fields.

---

### B. Architecture

```
lib/geollm_lib/
  series.py         NEW — time-series helpers (chunked loader, gap fill, trend,
                         anomaly, zonal series, change-point)
  classify.py       NEW — classification helpers (feature build, sample at
                         points/polygons, spatial split, cluster, metrics)
  viz_ts.py         NEW — new chart types (line plot, decomposition, anomaly
                         band, confusion matrix, classmap N colours, confidence)

harness/
  prompts_ts.py     NEW — TS_KNOWLEDGE and CLS_KNOWLEDGE blocks; injected only
                         when ≥3 temporal scenes or label vector is detected
  ts_validator.py   NEW — additional output checks; appended after existing
                         check_outputs; never alters existing check results
  api_doc.py        EDIT — append "series", "classify", "viz_ts" to MODULES tuple
                         (line 7); existing entries unchanged
  doc_lookup.py     EDIT — add scikit-learn, statsmodels after Phase 3 Docker
                         rebuild; existing entries unchanged
  pi_config.py      EDIT — add 4 additive env-var fields; existing fields
                         unchanged
  pi_harness.py     EDIT — 5-line conditional injection of TS/CLS knowledge;
                         existing prompt path untouched if condition false
  docker_runner.py  EDIT — 3-line append of ts_validator call after _validate();
                         existing _validate() untouched

docker/
  Dockerfile.ts     NEW — extends geollm-runtime; adds scikit-learn, statsmodels
                         (Phase 3 only; original Dockerfile unchanged)
```

#### Unavoidable edits — full backward-compatibility guarantees

| File | Exact change | Guarantee |
|---|---|---|
| `harness/api_doc.py:7` | Append `"series"`, `"classify"`, `"viz_ts"` to `MODULES` tuple | `signatures()` for all 13 existing modules returns same dict; `lru_cache` cleared by process restart |
| `harness/pi_config.py` | Add 4 fields `ts_sandbox_timeout_s`, `ts_sandbox_memory`, `ts_chunk_rows`, `cls_test_size`; each reads a new env-var defaulting to the same value as the existing field | All existing code reads `cfg.sandbox_timeout_s` — same value; new fields invisible to old code |
| `harness/pi_harness.py:43` | In `_build_prompt()`, after existing substitutions, append TS/CLS knowledge strings only when `len(facts["alignment"]["dates"]) >= 3` or vector labels detected; otherwise append empty string | Existing single-date and 2-date queries: condition is false, empty string appended, prompt identical |
| `harness/docker_runner.py:281` | After `errors, warnings, artifacts = _validate(...)`, append: `if ts_validator.is_ts_result(result): errors += ts_validator.check_ts_outputs(result, artifacts)` | `_validate()` untouched; `is_ts_result()` returns False for existing tasks (no 'trend'/'confusion_matrix' keys); no new issues added |

---

### C. Function List (Signatures Only)

Every value must flow: **argument → data/metadata → user query → config**.  
No body may contain a hardcoded threshold, CRS, colour, path, or numeric constant.  
Every function returns a `params_used` dict.

---

#### `lib/geollm_lib/series.py`

```python
def load_series(
    paths: list[str],
    reader: callable,
    # fn(path, src) → float32 ndarray; caller decides what to read; no hardcoded index
    chunk_rows: int,
    # from config GEOLLM_TS_CHUNK_ROWS; must be passed by caller; raises if None
    nodata: float | None,
    # from inspect_geotiff metadata; None means treat 0 or NaN per dtype
    align_resampling: str,
    # "bilinear"|"nearest"; from user query or config; raises if missing
) -> tuple[np.ndarray, list[datetime.datetime], dict]:
    """
    Memory-safe temporal stack loader.
    Reads scenes one at a time; calls align_to (align.py:26) if same_grid fails.
    Returns (stack T×H×W float32, sorted_dates, params_used).
    Raises ValueError with alignment hint if any scene has no CRS.

    Checked against: index_stack (temporal.py:36); not duplicate because
    index_stack requires a named spectral index and loads all T simultaneously;
    this function accepts any caller-supplied reader and processes in chunk_rows rows.
    """

def resample_series(
    dates: list[datetime.datetime],
    values: np.ndarray,         # shape (T,) or (T,H,W)
    freq: str,
    # pandas offset alias e.g. "MS","W","QS"; from user query; raises if None
    method: str,
    # "linear"|"nearest"|"forward"; from user query
) -> tuple[list[datetime.datetime], np.ndarray, dict]:
    """
    Resamples an irregular time series to a regular grid using pandas Series.
    Returns (new_dates, resampled_values, params_used).
    Raises ValueError if freq is not a valid pandas offset alias.
    Checked against: no resampling exists anywhere in the codebase.
    """

def fill_gaps(
    dates: list[datetime.datetime],
    values: np.ndarray,         # (T,) or (T,H,W); NaN = missing observation
    method: str,
    # "linear"|"spline"; from user query
    max_gap_days: int,
    # from config GEOLLM_TS_MAX_GAP_DAYS; raises if None; caller must pass
) -> tuple[np.ndarray, dict]:
    """
    Fills NaN gaps by interpolation along the time axis.
    Gaps wider than max_gap_days remain NaN.
    Returns (filled_values, params_used).
    Checked against: no gap-fill logic exists anywhere in the codebase.
    """

def seasonal_baseline(
    stack: np.ndarray,          # (T,H,W) or (T,) scalar
    dates: list[datetime.datetime],
    period: str,
    # "month"|"doy"|"week"; from user query; raises if None (never inferred)
    stat: str,
    # "mean"|"median"; from user query
) -> tuple[np.ndarray, np.ndarray, dict]:
    """
    Computes a per-period climatological baseline and its standard deviation.
    Returns (baseline_same_shape_as_stack, std_same_shape, params_used).
    Example: period="month" → January mean over all years, Feb mean over all years, etc.

    Checked against: anomaly_zscore (temporal.py:68) computes a flat z-score
    for the last time step against all prior dates with no period grouping;
    not duplicate because this function groups by calendar period.
    """

def anomaly_from_baseline(
    stack: np.ndarray,          # (T,H,W)
    baseline: np.ndarray,       # same shape; from seasonal_baseline
    baseline_std: np.ndarray,   # same shape; from seasonal_baseline
    method: str,
    # "zscore"|"absolute"|"percent"; from user query
) -> tuple[np.ndarray, dict]:
    """
    Computes per-pixel anomaly for each time step relative to its seasonal baseline.
    Returns (anomaly_stack same shape as stack, params_used).

    Checked against: anomaly_zscore (temporal.py:68) only covers the last time step
    against a static non-seasonal baseline; not duplicate because this function
    processes all time steps against their matching seasonal baseline.
    """

def trend_test(
    dates: list[datetime.datetime],
    values: np.ndarray,         # (T,) — scalar series (zonal mean or single pixel)
    method: str,
    # "ols"|"mannkendall"|"sens"; from user query; raises if None
    min_samples: int,
    # from config GEOLLM_TS_MIN_TREND_SAMPLES; raises if fewer valid samples
) -> dict:
    """
    Tests for monotonic trend in a 1D scalar series.
    'ols': numpy polyfit (always available).
    'mannkendall': scipy.stats.kendalltau on rank-paired (xi,xj) where i<j
                   (does not require pymannkendall).
    'sens': numpy median of pairwise ((xj-xi)/(tj-ti)) differences.
    Returns: {trend, slope_per_year, p_value, tau, n_samples, method_used, params_used}.
    Raises ValueError if n_valid < min_samples.

    Checked against: trend_per_year (temporal.py:51) is OLS only for 2D pixel arrays;
    not duplicate because this operates on 1D scalar series and supports three methods
    with significance testing.
    """

def pixel_trend_map(
    stack: np.ndarray,          # (T,H,W)
    dates: list[datetime.datetime],
    method: str,
    # "ols" only for 2D (mannkendall per-pixel is prohibitively slow)
    min_valid: int,
    # from config GEOLLM_TS_MIN_TREND_SAMPLES; raises if None
) -> tuple[np.ndarray, np.ndarray, dict]:
    """
    Per-pixel OLS trend. Returns (slope_H×W, pvalue_H×W, params_used).
    Reuses trend_per_year (temporal.py:51) for the slope; adds p-value via
    t-distribution from scipy.stats.

    Checked against: trend_per_year (temporal.py:51); not duplicate because
    this adds p-value computation and min_valid masking as separate outputs.
    """

def change_point_1d(
    dates: list[datetime.datetime],
    values: np.ndarray,         # (T,) scalar
    method: str,
    # "cusum"|"pettitt"; from user query; raises if None
    sensitivity: float,
    # from user query or config GEOLLM_TS_CP_SENSITIVITY; raises if None
) -> dict:
    """
    Detects change points in a 1D scalar series using numpy/scipy only
    (does not require ruptures).
    'cusum': cumulative sum of deviations from mean; threshold = sensitivity * std.
    'pettitt': Mann-Whitney U statistic over all split points via scipy.stats.
    Returns: {change_point_index, change_point_date, statistic, method_used, params_used}.
    Returns {change_point_index: None} if no significant change point found.
    Checked against: no change-point detection exists anywhere in the codebase.
    """

def zonal_series(
    paths: list[str],
    reader: callable,
    # fn(path, src) → float32 ndarray; same contract as load_series
    zones: object,
    # GeoDataFrame; from read_vector (vector.py:35)
    stat: str,
    # "mean"|"median"|"sum"; from user query; raises if None
    chunk_rows: int,
    # from config; used only if reader loads in chunks
    max_zones: int,
    # from config GEOLLM_TS_MAX_ZONES or caller; forwards to zonal_stats
) -> tuple[dict, list[datetime.datetime], dict]:
    """
    Builds {zone_id: [value_t0, value_t1, ...]} by calling order_by_date,
    then reader + zonal_stats (vector.py:48) once per scene.
    Returns (zone_values_dict, sorted_dates, params_used).
    Reuses: order_by_date (temporal.py:27), zonal_stats (vector.py:48).

    Checked against: zonal_stats operates on a single raster, not a temporal loop;
    not duplicate because this function loops over ordered scenes.
    """
```

---

#### `lib/geollm_lib/classify.py`

```python
def sample_raster_at_points(
    src,
    # open rasterio dataset
    gdf,
    # GeoDataFrame with Point geometries; from read_vector (vector.py:35)
    band_indices: list[int],
    # 1-based; from inspect_geotiff metadata or user override; raises if empty
    label_col: str,
    # column name in gdf; from user query; raises if column absent
    nodata: float | None,
    # from metadata
) -> tuple[np.ndarray, np.ndarray, dict]:
    """
    Extracts band values at each point.
    Returns (X ndarray N×B float32, y ndarray N int64, params_used).
    Raises ValueError if label_col missing, if gdf has no points in raster extent,
    or if any band_index is out of range.

    Checked against: zonal_stats (vector.py:48) returns summary dicts for polygon zones;
    not duplicate because this returns flat arrays at point locations for ML input.
    """

def sample_raster_at_polygons(
    src,
    # open rasterio dataset
    gdf,
    # GeoDataFrame with Polygon geometries
    band_indices: list[int],
    # 1-based; raises if empty
    label_col: str,
    # from user query; raises if absent
    stat: str,
    # "mean"|"median"; from user query
    nodata: float | None,
) -> tuple[np.ndarray, np.ndarray, dict]:
    """
    Returns (X N×B, y N int64, params_used) using per-polygon rasterization.
    Reuses: rasterize_vector (vector.py:39) per polygon.

    Checked against: zonal_stats (vector.py:48) returns dicts; not duplicate because
    this returns flat arrays shaped for ML input.
    """

def build_feature_stack(
    src,
    # open rasterio dataset
    band_indices: list[int],
    # 1-based; raises if empty
    extra_arrays: list[np.ndarray] | None,
    # caller-computed (e.g., NDVI); must match src spatial shape
    nodata: float | None,
) -> tuple[np.ndarray, np.ndarray, dict]:
    """
    Builds (X ndarray H*W × n_features float32, valid_mask H×W bool, params_used).
    Caller uses X[valid_mask.ravel()] for prediction.
    Checked against: no feature matrix builder exists in codebase.
    """

def spatial_train_test_split(
    X: np.ndarray,              # (N, B) features
    y: np.ndarray,              # (N,) int labels
    gdf,
    # GeoDataFrame with same row order as X, y
    test_size: float,
    # from config GEOLLM_CLS_TEST_SIZE; raises if None
    method: str,
    # "spatial_block"|"random"; from user query; raises if None
    buffer_m: float,
    # metres; from config GEOLLM_CLS_BUFFER_M; required for spatial_block
    seed: int,
    # from config GEOLLM_CLS_SEED; raises if None
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict]:
    """
    Returns (X_train, X_test, y_train, y_test, params_used).
    'spatial_block': divides extent into grid blocks; no test point is within
                     buffer_m of any training point (uses buffer_vector at vector.py:73).
    'random': numpy rng split.
    Raises ValueError if any class has fewer than 2 samples after split.
    Checked against: no train/test split exists in codebase.
    """

def fit_classifier(
    X_train: np.ndarray,
    y_train: np.ndarray,
    model: str,
    # "random_forest"|"gradient_boosting"|"kmeans"; from user query; raises if None
    model_params: dict,
    # all optional; from user query or {}; no body defaults
    seed: int,
    # from config; passed to model constructor
) -> tuple[object, dict]:
    """
    Fits a classifier. Returns (fitted_model, params_used).
    'kmeans': scipy.cluster.vq.kmeans2 — always available (Phase 1/2).
    'random_forest': sklearn.ensemble.RandomForestClassifier — requires Phase 3 image.
    'gradient_boosting': sklearn.ensemble.GradientBoostingClassifier — Phase 3.
    Raises ImportError with clear message and kmeans fallback suggestion if sklearn absent.
    Checked against: no model fitting exists in codebase.
    """

def predict_in_chunks(
    model,
    # fitted classifier with .predict() method
    src,
    # open rasterio dataset
    band_indices: list[int],
    # raises if empty
    extra_arrays: list[np.ndarray] | None,
    chunk_rows: int,
    # from config; raises if None
    nodata: float | None,
    class_map: dict,
    # {int: str}; from user query; raises if None
    compute_confidence: bool,
    # from user query; requires model.predict_proba
) -> tuple[np.ndarray, np.ndarray | None, dict]:
    """
    Runs prediction in row chunks to stay within memory budget.
    Returns (class_raster H×W int16, confidence_raster H×W float32 | None, params_used).
    Unknown pixels (nodata or outside extent) receive value 0.
    Reuses: build_feature_stack per chunk.
    Checked against: no chunk prediction exists in codebase.
    """

def classification_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    class_map: dict,
    # {int: str}; raises if None or incomplete
) -> dict:
    """
    Computes confusion matrix (numpy), overall accuracy, per-class precision/recall/F1.
    All implemented with numpy — no sklearn required.
    Returns: {overall_accuracy, confusion_matrix (2D list), per_class (dict), params_used}.
    Checked against: no metrics implementation exists in codebase.
    """

def save_model_metadata(
    model,
    # sklearn: serialized with pickle (stdlib); kmeans: numpy .npy centroid array
    class_map: dict,
    # {int: str}
    band_indices: list[int],
    params_used: dict,
    out_dir: str,
    # from output_path (result.py:20)
) -> dict:
    """
    Saves model artifact and a JSON sidecar {class_map, band_indices, params_used}.
    Returns {model_file, metadata_file}.
    Checked against: no model persistence exists in codebase.
    """
```

---

#### `lib/geollm_lib/viz_ts.py`

```python
def save_timeseries_plot(
    dates: list[datetime.datetime],
    values: np.ndarray,         # (T,) scalar or (T, n_series) multi-zone
    path: str,
    title: str,
    # from task description; raises if None
    ylabel: str,
    # from unit metadata or user query; raises if None (units must be known)
    series_labels: list[str] | None,
    # zone names or None for single series; auto-numbered if None and multi-series
    trend: dict | None,
    # output of trend_test; trend line drawn if provided
    anomaly_threshold: float | None,
    # horizontal band drawn if provided; from user query or None
    figsize: tuple,
    # from config GEOLLM_VIZ_FIGSIZE default (8,4); caller passes
    palette: list[str] | None,
    # from caller; auto-generated if None; no hardcoded colours
) -> None:
    """
    Line plot with date axis, optional trend line, optional anomaly band.
    All styling from parameters.
    Checked against: viz.py has no line plot; not duplicate.
    """

def save_decomposition_plot(
    dates: list[datetime.datetime],
    observed: np.ndarray,       # (T,)
    trend_component: np.ndarray,
    seasonal_component: np.ndarray,
    residual: np.ndarray,
    path: str,
    title: str,
    ylabel: str,
    # raises if None
    figsize: tuple,
) -> None:
    """
    4-panel decomposition plot. All labels from parameters.
    Checked against: no decomposition plot exists.
    """

def save_changepoint_plot(
    dates: list[datetime.datetime],
    values: np.ndarray,         # (T,)
    change_point_date,
    # datetime or None
    path: str,
    title: str,
    ylabel: str,
    figsize: tuple,
) -> None:
    """
    Line plot with vertical line at change point if detected.
    Checked against: no change-point plot exists.
    """

def save_confusion_matrix(
    cm: np.ndarray,             # square int array from classification_metrics
    class_names: list[str],
    # from class_map; raises if None
    path: str,
    title: str,
    normalize: bool,
    # from user query; normalizes rows if True
    figsize: tuple,
) -> None:
    """
    Confusion matrix heatmap using matplotlib imshow; no seaborn required.
    Checked against: no confusion matrix plot exists.
    """

def save_classmap_n(
    classes: np.ndarray,        # int H×W
    path: str,
    title: str,
    class_map: dict,
    # {int: str}; raises if None
    palette: list[str] | None,
    # caller supplies or None → HSV-spaced colours for len(class_map) classes
    background: np.ndarray | None,
    figsize: tuple,
) -> None:
    """
    Class map with auto-generated palette for N classes of any size.
    Does NOT call save_class_map (viz.py:36) to avoid its hardcoded 5-colour palette.

    Checked against: save_class_map (viz.py:36) has 5-colour hardcoded list at line 38;
    not duplicate because this generates HSV palette for arbitrary N and accepts
    caller-supplied palette.
    """

def save_confidence_map(
    confidence: np.ndarray,     # float32 H×W in [0,1]
    path: str,
    title: str,
    cmap: str,
    # from user query or config GEOLLM_VIZ_CONFIDENCE_CMAP; raises if None
    vmin: float,
    # from user query; default 0.0 passed by caller
    vmax: float,
    # from user query; default 1.0 passed by caller
) -> None:
    """
    Reuses save_map (viz.py:9) with confidence-specific arguments passed explicitly.
    """
```

---

### D. Config Design

**Single location: `harness/pi_config.py`.**  
Reuse the existing `_f(name, default)` env-var pattern. Add four additive fields:

```python
# Additive fields — all existing fields unchanged
ts_sandbox_timeout_s: int     # GEOLLM_TS_SANDBOX_TIMEOUT_S  default=sandbox_timeout_s
ts_sandbox_memory:    str     # GEOLLM_TS_SANDBOX_MEMORY      default=sandbox_memory
ts_chunk_rows:        int     # GEOLLM_TS_CHUNK_ROWS           default=256
cls_test_size:        float   # GEOLLM_CLS_TEST_SIZE           default=0.30
```

Additional per-function env-vars (read inside functions, not in `Config`, because they are narrow concerns):

| Env-var | Used by | Purpose |
|---|---|---|
| `GEOLLM_TS_MAX_GAP_DAYS` | `fill_gaps` | Max gap before leaving NaN |
| `GEOLLM_TS_MIN_TREND_SAMPLES` | `trend_test`, `pixel_trend_map` | Min valid samples |
| `GEOLLM_TS_MAX_ZONES` | `zonal_series` | Max zones forwarded to `zonal_stats` |
| `GEOLLM_TS_CP_SENSITIVITY` | `change_point_1d` | Default sensitivity if not in query |
| `GEOLLM_CLS_BUFFER_M` | `spatial_train_test_split` | Exclusion buffer (metres) |
| `GEOLLM_CLS_SEED` | `fit_classifier`, `spatial_train_test_split` | Random seed |
| `GEOLLM_VIZ_FIGSIZE` | all viz_ts functions | Default figure size tuple |
| `GEOLLM_VIZ_CONFIDENCE_CMAP` | `save_confidence_map` | Default colormap name |

**All these values raise if not provided and cannot be inferred.**  
No function body contains a numeric literal for any of these.

**Per-task override:** follows the existing pattern at `pi_harness.py:95`:
```python
if max_turns:
    cfg = replace(cfg, max_tool_calls=int(max_turns))
```
For TS tasks: `cfg = replace(cfg, ts_sandbox_timeout_s=..., ts_chunk_rows=...)`.  
The existing `overrides` dict argument to `solve()` is the vehicle.

---

### E. Prompt/Playbook Additions

#### New file: `harness/prompts_ts.py`

Two new string constants: `TS_KNOWLEDGE` and `CLS_KNOWLEDGE`.

#### Injection logic in `pi_harness._build_prompt()` (5 additive lines)

```python
from harness.prompts_ts import TS_KNOWLEDGE, CLS_KNOWLEDGE

ts_block = ""
cls_block = ""
n_dates = len([d for d in facts.get("alignment", {}).get("dates", {}).values() if d])
has_labels = any(
    f.get("kind") == "vector" and f.get("columns")
    for f in facts.get("files", {}).values()
)
if n_dates >= 3:
    ts_block = TS_KNOWLEDGE
if has_labels:
    cls_block = CLS_KNOWLEDGE

return Template(PROMPT_FILE.read_text()).substitute(
    ...,
    ts_knowledge=ts_block,    # new template variable; default empty string
    cls_knowledge=cls_block,  # new template variable; default empty string
)
```

The `pi_prompt.md` template receives two new variables that default to empty strings. **If both conditions are false (any existing single-date or two-date query), both are empty and the prompt is identical to today's.**

#### `TS_KNOWLEDGE` block key rules (paraphrase — no magic numbers)

```
TIME-SERIES GUIDANCE

When 3 or more temporal scenes are supplied:

1. Interpret the question first. Map layman wording to a method:
   "has X been growing/shrinking/changing over time" → trend
   "is this month/period unusual compared to normal" → anomaly
   "when did X suddenly change" → change-point
   "what is the seasonal pattern of X" → decomposition
   
2. Before any computation, call propose_plan() with a parameters_interpreted block:
   {query_type, variable_name, dates_found, n_dates, method_chosen, output_unit,
    chunk_rows_env, seasonal_matching, area_crs_from_metadata}
   Do NOT start computation until the user approves.

3. Memory budget: use load_series with the chunk_rows value from
   GEOLLM_TS_CHUNK_ROWS. Never load all T scenes at once without chunking.

4. Seasonal matching: when comparing values across years, use seasonal_baseline
   with the period derived from the user query. Do not assume monthly or annual.

5. Mann-Kendall and Sen's slope are available in series.trend_test without
   pymannkendall (implemented using scipy.stats.kendalltau).

6. Area calculations must use a projected metric CRS. Read the CRS from metadata;
   do not assume one.

7. Standard output bundle for every TS task:
   - main map (trend slope / anomaly map / change-date map) as TIF + PNG
   - timeseries.png (line chart, date axis, optional trend line)
   - timeseries.csv (date, value, n_valid columns — column names from params_used)
   - result.json with params_used, trend dict, anomaly dict, files list

8. Plain-language summary must be generated from result.json values only;
   never type a number that was not computed.
```

#### `CLS_KNOWLEDGE` block key rules (paraphrase — no magic numbers)

```
CLASSIFICATION GUIDANCE

When training labels (points or polygons with a label column) are supplied:

1. Interpret class names from the label column. Never invent class names.
   Show class_map ({int: str}) in propose_plan() before coding.

2. In propose_plan() show: class_map, n_samples_per_class, method_chosen,
   band_indices used, test_size, spatial split method.

3. scikit-learn availability:
   If GEOLLM_IMAGE=geollm-runtime-ts: use random_forest or gradient_boosting.
   Otherwise: use kmeans (always available) and state the limitation in assumptions.

4. Always use spatial_block split when data has a metric CRS to prevent
   spatial autocorrelation leakage. Use random only as fallback.

5. Required result.json keys: class_map, n_classes, overall_accuracy,
   confusion_matrix (2D list), per_class_f1 (dict), params_used, files.

6. Standard output bundle:
   - class_map.tif (int16) + class_map.png (save_classmap_n)
   - confidence_map.tif (float32) + confidence_map.png (if model supports)
   - confusion_matrix.png
   - classes.geojson (one polygon file per class, or one multi-class file)
   - result.json

7. Unknown/unclassifiable pixels: assign value 0 ("unknown") in class raster.
```

#### 6 Example Queries Across Domains

| # | Query | Data type | Method | New helpers invoked |
|---|---|---|---|---|
| 1 | "Has the forest been recovering since the wildfire last year?" | 12 Sentinel-2 scenes | OLS trend on NBR | `load_series`, `pixel_trend_map`, `save_timeseries_plot` |
| 2 | "Which months have the most abnormally low river flow compared to the historical average?" | 20-year monthly discharge rasters | Seasonal baseline + anomaly | `seasonal_baseline`, `anomaly_from_baseline`, `save_timeseries_plot`, `save_decomposition_plot` |
| 3 | "Map the field crop types using these GPS survey points labelled with crop name." | Multispectral image + CSV with lat/lon + `crop_type` column | Random Forest (Phase 3) or kmeans (Phase 2) | `sample_raster_at_points`, `spatial_train_test_split`, `fit_classifier`, `predict_in_chunks`, `save_classmap_n`, `save_confusion_matrix` |
| 4 | "When did the fishing vessel density in this port area start declining?" | Monthly SAR backscatter stack (5 years) | Change-point detection on zonal mean | `zonal_series`, `change_point_1d`, `save_changepoint_plot` |
| 5 | "Is the air quality index getting significantly worse in this district over 10 years?" | Annual pollution rasters (30 scenes) | Mann-Kendall trend + pixel map | `load_series`, `trend_test`, `pixel_trend_map`, `save_timeseries_plot` |
| 6 | "Classify this hyperspectral image into geological units using the labelled polygon outcrops." | Hyperspectral cube + GeoJSON polygons with `lithology` column | Spectral feature + Random Forest (Phase 3) or kmeans (Phase 2) | `sample_raster_at_polygons`, `build_feature_stack`, `fit_classifier`, `predict_in_chunks`, `save_classmap_n`, `save_confusion_matrix` |

---

### F. Validators

#### New file: `harness/ts_validator.py`

```python
def is_ts_result(result: dict | None) -> bool:
    """Returns True if result contains any TS or classification keys."""
    if not isinstance(result, dict):
        return False
    ts_keys = {"trend", "anomaly", "change_point", "confusion_matrix",
               "class_map", "n_classes", "timeseries"}
    return bool(ts_keys & result.keys())

def check_ts_outputs(result: dict, artifacts: list[str]) -> list[dict]:
    """
    Returns list of {severity, code, artifact, message} using the same
    schema as numerical_check._issue().
    
    Checks added (none modify existing check_outputs results):
    
    1. TREND SIGN CONSISTENCY: if 'trend' key present with 'slope_per_year'
       and 'trend_direction', assert sign(slope) matches direction string.
       Error if "decreasing" but slope > 0, or "increasing" but slope < 0.
    
    2. CONFUSION MATRIX PRESENT: if 'class_map' present in result,
       assert 'confusion_matrix' is a 2D list, 'overall_accuracy' is in [0,1],
       and 'class_names' list is non-empty.
    
    3. MULTI-CLASS RASTER: if any .tif artifact contains integer dtype and
       more than 2 unique values (sampled), assert result has 'class_map' key.
    
    4. UNITS PRESENT: if any result key ends with '_per_year' or '_value',
       assert result has a 'units' or 'variable_unit' key.
    
    5. CSV READABLE: for each .csv artifact, assert it can be read as a
       pandas DataFrame with at least 1 row and the 'date' column present.
    """
```

**Integration** (`docker_runner.py:281`, 3 additive lines only):

```python
# After: errors, warnings, artifacts = _validate(res, attempt_dir, cfg)
# Append (3 new lines):
if result is not None:
    from harness import ts_validator
    if ts_validator.is_ts_result(result):
        errors += ts_validator.check_ts_outputs(result, artifacts)
```

**Existing task protection:** `is_ts_result()` returns `False` for any standard result.json that has only `summary`, `assumptions`, `thresholds`, `files`, `selected_pixels`, `area_hectares`, etc. No new errors added to existing tasks.

---

### G. Visualization — Standard Output Bundle

The plain-language summary is always assembled from `result.json` values by the existing `final_check.template_answer()`. The agent must never type a number.

#### Time-Series Standard Bundle

| File | Generator | Content |
|---|---|---|
| `trend_slope.tif` | `write_raster` | float32 slope per pixel; CRS from input |
| `trend_slope.png` | `save_map` | slope raster; title and unit label from `params_used` |
| `timeseries.png` | `save_timeseries_plot` | date vs. zonal-mean value; optional trend line |
| `timeseries.csv` | `pandas.DataFrame.to_csv` | columns: `date`, `value`, `n_valid` (names from `params_used`) |
| `anomaly.tif` (if anomaly) | `write_raster` | float32 anomaly per pixel |
| `anomaly.png` (if anomaly) | `save_map` | anomaly map |
| `changepoint.png` (if CP) | `save_changepoint_plot` | line chart with vertical marker |
| `result.json` | `save_result` | `summary`, `assumptions`, `params_used`, `trend`, `timeseries_csv`, `files` |

#### Classification Standard Bundle

| File | Generator | Content |
|---|---|---|
| `class_map.tif` | `write_raster` (int16) | class raster; values from `class_map` |
| `class_map.png` | `save_classmap_n` | class map; legend from `class_map`; palette auto-generated |
| `confidence_map.tif` | `write_raster` (float32) | winning-class probability |
| `confidence_map.png` | `save_confidence_map` | confidence heatmap |
| `confusion_matrix.png` | `save_confusion_matrix` | heatmap; class_names from `class_map` |
| `classes.geojson` | `mask_to_geojson` per class | polygon export per class |
| `model.pkl` / `model_centroids.npy` | `save_model_metadata` | serialized model |
| `model_metadata.json` | `save_model_metadata` | class_map, band_indices, params_used |
| `result.json` | `save_result` | `summary`, `assumptions`, `class_map`, `n_classes`, `overall_accuracy`, `confusion_matrix`, `per_class_f1`, `params_used`, `files` |

---

### H. Frontend — Later Phase (No Changes in Phases 1–3)

> **Zero frontend changes until Phase 4. This section is design-only.**

#### New SSE Event (additive — existing frontend ignores unknown types)

```json
{
  "type": "timeline",
  "task_id": "task_1",
  "dates": ["2023-01-05", "2023-04-10"],
  "current_index": 3,
  "total_frames": 12
}
```

Unknown event types fall through to no-op in the existing event handler.

#### `timeline.json` Contract (served from new `/api/tasks/{id}/timeline` route)

```json
{
  "dates": ["2023-01-05", "..."],
  "variable": "NBR",
  "unit": "dimensionless",
  "frames": [
    {"date": "2023-01-05", "tif": "frame_0.tif", "png": "frame_0.png"}
  ],
  "zonal_series": {
    "dates": ["..."],
    "values": [0.12, 0.18],
    "zone_label": "study_area"
  }
}
```

#### Phase 4 Frontend Components

- `static/js/components/TimeSlider.js` — reads `timeline.json.dates`; plays PNGs
- Play/pause button; synced line chart beneath map highlights current date
- All vanilla JS; no framework change

---

### I. Sandbox Limits

#### Memory Budget

| Task type | Container memory | Source |
|---|---|---|
| Existing tasks | `cfg.sandbox_memory` (`GEOLLM_SANDBOX_MEMORY`, default `"4g"`) | `pi_config.py:48` |
| TS tasks | `cfg.ts_sandbox_memory` (`GEOLLM_TS_SANDBOX_MEMORY`, default: same) | New additive field |

**Chunked loading math:** `chunk_rows × W × n_bands × 4 bytes`.  
At `chunk_rows=256`, `W=10000`, `n_bands=4`: `256 × 10000 × 4 × 4 = 40 MB` per chunk. Well within 4 GB.

**Classification prediction math:** `chunk_rows × W × n_features × 4 bytes`.  
At 256 rows × 5000 px × 20 features: `≈ 100 MB` per chunk.

#### Timeout Budget

| Task type | Timeout | Source |
|---|---|---|
| Existing tasks | `cfg.sandbox_timeout_s` (default 180 s) | `pi_config.py:47` |
| TS tasks | `cfg.ts_sandbox_timeout_s` (`GEOLLM_TS_SANDBOX_TIMEOUT_S`, default: same) | New additive field |

The new timeout is passed to `run_code()` instead of `cfg.sandbox_timeout_s` only when the task's plan `modules` list contains `"series"` or `"classify"`. Detection happens in the 3-line `docker_runner.py` addition.

#### Prompt Guidance to Agent

`TS_KNOWLEDGE` states: *"Use `load_series` with the `chunk_rows` value from `GEOLLM_TS_CHUNK_ROWS`. Do not load all T scenes at once."*

---

### J. Backward-Compatibility & Regression Plan

#### Regression Reference Tasks

Run before and after each phase. Compare file hashes (SHA-256) of all outputs.

| ID | Query | Input | Expected artifacts |
|---|---|---|---|
| R1 | "Where is NDVI highest in this image?" | 1 Sentinel-2 scene | `mask.tif`, `mask.png`, `result.json` |
| R2 | "Show backscatter change between before and after" | 2 SAR VH scenes | `change.tif`, `change.png`, `result.json` |
| R3 | "Where are flooded areas in this SAR image?" | 2 VV SAR scenes | `flood.tif`, `flood.png`, `result.json` |
| R4 | "What percentage of pixels are above NDVI 0.4?" | 1 multispectral scene | `result.json` |
| R5 | "Compute spectral signature of the bright region" | 1 hyperspectral cube | `signature.png`, `result.json` |

#### Phase Gate: All R1–R5 must produce identical SHA-256 hashes before merge.

---

### K. Test Plan Per Phase

#### Phase 1 — `series.py` + `viz_ts.py` (line plots only; numpy/scipy/pandas; no Docker change)

| Test | Input | Assert |
|---|---|---|
| T1-1: date parsing | 5 synthetic TIFFs with ACQUISITION_DATETIME tags | `load_series` returns stack `(5,H,W)`; dates sorted oldest-first |
| T1-2: chunked loading | Same 5 TIFFs; `chunk_rows=1` | Peak RAM = single-row slice; final stack identical to `index_stack` result |
| T1-3: gap fill | Series `[1.0, NaN, NaN, 4.0]` at daily freq; `max_gap_days=5` | Linear interpolation: `[1.0, 2.0, 3.0, 4.0]` |
| T1-4: seasonal baseline | 24-month stack, alternating high/low values | January baseline ≠ July baseline |
| T1-5: Mann-Kendall | Monotone increasing series of 10 values | `trend="increasing"`, `p_value < 0.05`, `tau > 0` |
| T1-6: OLS trend map | 5-scene 10×10 raster stack with known slope | `pixel_trend_map` slope matches `numpy.polyfit` reference |
| **T1-D: domain independence** | Run T1-5 on (a) SAR backscatter series, (b) NDVI series | Same `trend_test` function; `params_used["method"]` identical; `slope_per_year` differs → proves no domain hardcoding |

#### Phase 2 — `classify.py` + full `viz_ts.py` (kmeans only; no Docker change)

| Test | Input | Assert |
|---|---|---|
| T2-1: point sampling | 1 multispectral TIF + 20 GPS points with `crop_type` column | `X.shape == (20, n_bands)`; `y` contains only mapped int values |
| T2-2: spatial split | 100 points; `method="spatial_block"`, `buffer_m=500` | No test point within 500 m of any training point |
| T2-3: kmeans fit | `X_train (80,4)`, `model_params={"k":3}` | Returns model with 3 centroids |
| T2-4: chunk predict | 500×500 raster; `chunk_rows=64` | `class_raster.shape == (500,500)`; all values in `class_map.keys()` |
| T2-5: metrics | Known `y_true`, `y_pred` for 3 classes | `OA == correct/total`; confusion matrix row-sums == per-class count |
| **T2-D: domain independence** | Run T2-1–T2-5 on (a) multispectral optical, (b) SAR multi-pol image | Same helpers; `band_indices` differ; `label_col` differs → proves no domain hardcoding |

#### Phase 3 — Docker `geollm-runtime-ts` with scikit-learn

| Test | Assert |
|---|---|
| `fit_classifier(model="random_forest")` in new image | No import error; fitted model has `.feature_importances_` |
| `predict_in_chunks` with RF model | OA > kmeans OA on same data |
| R1–R5 run with original `geollm-runtime` image | All SHA-256 hashes identical to pre-Phase-1 |

#### Phase 4 — Frontend

- Manual: time slider plays 12 frames without JS errors
- Manual: line chart syncs with slider position
- Automated: `/api/tasks/{id}/timeline` returns valid JSON matching contract

---

### L. Risks, Effort vs. Impact, Implementation Order

#### Risk Table

| Risk | Likelihood | Severity | Mitigation |
|---|---|---|---|
| Memory OOM on large T stacks | High | High | Mandatory chunked loader; TS memory env-var independent of existing |
| scikit-learn import in original image | Certain | High | `fit_classifier` raises clear `ImportError` with kmeans suggestion |
| Mann-Kendall too slow per-pixel at full res | Medium | Medium | `pixel_trend_map` exposes OLS only; MK only in 1D `trend_test` |
| `api_doc.py` MODULES edit breaks existing validator | Low | High | Unit test: assert all 13 existing names still present after edit |
| LLM hallucinates new module function names | Low | Medium | New modules added to `signatures()` → AST preflight catches wrong calls |
| Phase 3 Docker rebuild breaks existing queries | Medium | High | Two image tags coexist; `GEOLLM_IMAGE` env-var selects; original unchanged |
| Seasonal period inference from ambiguous query | Medium | Medium | `seasonal_baseline` raises ValueError if `period=None`; agent must ask user |

#### Effort vs. Impact Ranking

| Rank | Phase | Effort | Impact | Rationale |
|---|---|---|---|---|
| 1 | Phase 1: `series.py` + line plots | 3–4 days | Very High | Unlocks all TS queries with existing Docker image |
| 2 | Phase 1B: `prompts_ts.py` + `ts_validator.py` | 1–2 days | High | Makes system robust and self-checking with no Docker change |
| 3 | Phase 2: `classify.py` (kmeans) + confusion matrix viz | 3–4 days | High | Classification without Docker change |
| 4 | Phase 3: `Dockerfile.ts` + sklearn | 2–3 days | Medium | Full ML stack; requires image build and registry push |
| 5 | Phase 4: Frontend time slider | 3–5 days | Medium | UX polish; zero backend risk |

#### Implementation Order (smallest safe step first; each phase revertible)

```
Phase 0 — Preparation (no code changes)
  → Capture R1–R5 reference SHA-256 hashes.
  → Agree on Phase 1 scope. Approve this plan.

Phase 1 — series.py + viz_ts.py (line plots, trend maps)
  CREATE lib/geollm_lib/series.py
  CREATE lib/geollm_lib/viz_ts.py   (line plot, changepoint plot, decomposition)
  EDIT   harness/api_doc.py:7       → append "series", "viz_ts" to MODULES
  CREATE harness/prompts_ts.py      (TS_KNOWLEDGE only)
  EDIT   harness/pi_harness.py      → 5-line conditional TS injection
  EDIT   harness/pi_config.py       → ts_sandbox_timeout_s, ts_chunk_rows
  → Run R1–R5 regression. Revert all if any hash differs.

Phase 1B — Validator + Classification knowledge
  CREATE harness/ts_validator.py
  EDIT   harness/docker_runner.py   → 3-line ts_validator append
  UPDATE harness/prompts_ts.py      → add CLS_KNOWLEDGE
  EDIT   harness/pi_harness.py      → 2-line CLS injection condition
  → Run R1–R5 regression.

Phase 2 — classify.py (kmeans) + viz_ts.py (confusion, classmap_n)
  CREATE lib/geollm_lib/classify.py
  UPDATE lib/geollm_lib/viz_ts.py   → add confusion matrix, classmap_n, confidence
  EDIT   harness/api_doc.py:7       → append "classify"
  → Run R1–R5 regression.

Phase 3 — Docker geollm-runtime-ts + sklearn (requires image rebuild approval)
  CREATE docker/Dockerfile.ts
  UPDATE lib/geollm_lib/classify.py → add random_forest, gradient_boosting paths
  EDIT   harness/doc_lookup.py      → add scikit-learn, statsmodels entries
  EDIT   harness/pi_config.py       → ts_sandbox_memory field
  → Run R1–R5 with original GEOLLM_IMAGE. All hashes must be identical.

Phase 4 — Frontend (separate branch feature/ts-frontend)
  CREATE static/js/components/TimeSlider.js
  ADD    FastAPI route /api/tasks/{id}/timeline in web_app.py
  → No backend changes in Phases 1–3.
```

---

### M. NVIDIA OpenShell — Appendix (Separate Experiment, Separate Branch)

> ⚠️ Items marked **UNVERIFIED** were not fully read from primary documentation.
> This appendix describes an experiment only; it does not affect Phases 1–4.
> Branch: `feature/openshell-experiment`.

**What OpenShell is (from user-provided link):** NVIDIA OpenShell is described as "an open, secure runtime for AI agents" providing sandboxed execution and inference routing. It may support custom tool APIs for agents.

**Potential integration point in GeoLLM:**  
`harness/executor.py:run_code()` and `harness/docker_runner.py` currently manage a Docker container lifecycle manually (create → start → wait → remove via `docker-py`). OpenShell could potentially provide an equivalent secure execution environment with managed inference.

**What would NOT change under any OpenShell experiment:**  
`geollm_lib/*`, all harness validators, `pi_harness.py`, `orchestrator.py`, `web_app.py`, all prompts. The experiment is strictly in the runner layer.

**Proposed experiment:**
1. Read OpenShell API documentation fully. **UNVERIFIED: exact Python SDK API, authentication, volume mount support, Python package installation, network isolation model, GPU inference routing.**
2. Write `harness/openshell_runner.py` as a drop-in replacement for `executor.py:run_code()` with the **identical return schema** `{exit_code, timed_out, oom, stdout, stderr, result, artifacts, sandbox}`.
3. Select backend via env-var: `GEOLLM_RUNNER_BACKEND=docker|openshell`. Default `docker`.
4. `docker_runner.py` calls `_call_executor()` which already abstracts the runner via `inspect.signature` — the OpenShell runner can be injected there without changing `docker_runner.py`.
5. Never remove `docker_runner.py` or `executor.py`.

**Open questions for OpenShell (all UNVERIFIED):**
- Does OpenShell support running arbitrary Python scripts with custom installed packages?
- Does it support volume mounts equivalent to `/workspace/input`, `/workspace/output`?
- What is the inference routing capability — does it proxy Ollama/OpenAI calls?
- Is there a Python SDK or is it CLI-only?
- What are memory/CPU/timeout limits and how are they configured?
- Does it provide network isolation equivalent to `network_mode=none`?
- What is the authentication and pricing model?

---

### N. Questions for the User

1. **`tests/` directory** — Not opened. What test framework is used? Are there existing test fixtures with known-good reference outputs for R1–R5?
2. **Docker registry** — Where is `geollm-runtime` published? Is there a CI/CD pipeline for Docker builds, or is the image built and loaded manually on the host?
3. **`eval/` directory** — Not opened. Are there evaluation harness scripts for end-to-end task correctness that should be added to the regression matrix?
4. **`scripts/` directory** — Not opened. Are there helper scripts for image builds or data prep that should be updated in Phase 3?
5. **`pi_extension/geollm.ts`** — Not opened. Are there tool registration changes needed in the TypeScript extension for new `geollm_lib` modules to appear in the agent's tool list? Or do all modules auto-register via `api_doc.signatures()`?
6. **`pi_prompt.md` template variables** — The file uses `string.Template.substitute()`. Are there already template variables for knowledge/context injection, or must `ts_knowledge` and `cls_knowledge` be added as new placeholders? (Confirms the exact 5-line edit scope.)
7. **Classification ML stack** — Should Phase 3 (scikit-learn) be planned at all, or should the system rely on scipy kmeans indefinitely?
8. **Seasonal period inference** — When the user does not specify a period (monthly, weekly, annual), should the agent ask a clarifying question or raise an error? Or should a default period be read from the config?
9. **Mann-Kendall approximation** — The plan implements MK via `scipy.stats.kendalltau`. Is this approximation scientifically acceptable, or is the exact Kendall S-distribution (needed for small N < 10) required for your use cases?
10. **Frontend JS approach** — From `static/js/index.js` (351 bytes) and `static/js/html.js` (299 bytes), the frontend appears to use vanilla JS (no framework). Is this confirmed? Are there constraints on adding new `.js` component files?
11. **`doc_lookup.py` whitelist update timing** — Should the doc_lookup entries for new packages be added before or after the Docker image is built and verified? (Ensures the whitelist and the image are always in sync.)
12. **Two-scene queries with TS helpers** — If a user supplies exactly 2 scenes and asks "has X changed over time?", should the system use the existing `change.py` helpers or the new `series.py` helpers? (Determines the condition threshold: `>= 2` vs. `>= 3`.)
