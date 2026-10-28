# GeoLLM Context, Architecture & Error Analysis

> **Notice:** This document contains full project context, codebase architecture, error analysis, historical vs recent comparison, and tracking logs. Prior to executing any queries or modifications, review this context. Update findings here after operations without altering application source code.

---

## 1. Project Context & Purpose

**GeoLLM (Astryx Autonomous Geospatial Workbench)** is an offline geospatial analysis system. It converts natural language user queries into executable Python code, runs the scripts inside isolated, zero-network Docker sandboxes, validates outputs (via automated visual checks, numerical assertions, and multi-stage sub-agent reviews), and surfaces verified map deliverables (GeoTIFFs, PNGs, GeoJSON vectors, CSV statistics).

### Architectural Core
- **LLM Engine:** Local Qwen2.5-Coder:7B (via Ollama) or remote model via OpenRouter (e.g., Qwen3-Coder).
- **Harness Infrastructure (`harness/`):**
  - `orchestrator.py`: Multi-task manager coordinating up to 3 concurrent worker slots (`task_1`, `task_2`, `task_3`).
  - `pi_harness.py`: Agent execution loop using Pi extension architecture.
  - `pi_extension/geollm.ts`: TypeScript bridge registering `run_geospatial_code` tool.
  - `docker_runner.py`: Zero-network Docker container runner executing GDAL, rasterio, geopandas, numpy, scipy code.
  - Verification Sub-agents (`validator.py`, `numerical_check.py`, `visual_check.py`, `final_check.py`, `result_check.py`, `debugger.py`, `patcher.py`).
- **Geospatial Library (`lib/geollm_lib/`):** Custom offline utilities covering band roles (`bands.py`), spectral indices (`indices.py`), SAR analysis (`sar.py`), hyperspectral (`hyperspectral.py`), change detection (`change.py`), spatial alignment (`align.py`), temporal processing (`temporal.py`), vector ops (`vector.py`), and visualization (`viz.py`).
- **Web Interface (`web_app.py`, `static/`, `templates/`):** FastAPI backend + React 18 frontend with real-time SSE telemetry streams, 3-worker task slots, raster preview modals, and human-in-the-loop plan approval gates.

---

## 2. Failed Attempt Analysis (Attempt-Level vs Task-Level)

### Key Distinction
In GeoLLM, a **failed attempt** occurs when a generated Python script throws an exception inside the Docker sandbox during execution. The harness intercepts stdout/stderr, logs the failure, feeds the error stack trace back to the LLM agent, and triggers an autonomous self-correction loop (retry). A task is only considered failed if all retries are exhausted without producing valid output.

---

### Historical Error Distribution (All 318 Logged Attempts)

- **Total Logged Attempts:** 318
- **Successful Attempts:** 207 (65.1%)
- **Failed Attempts (Retried):** 111 (34.9%)
- **Average Attempts Per Task:** 5.5 attempts
- **Task Retry Rate:** 55 out of 58 tasks (94.8%) required at least 1 retry attempt before completion.
- **Overall Task Success Rate:** 56 out of 58 tasks (96.6%) ultimately succeeded after self-correction.

#### Top Error Categories Across History:
1. **`ValueError` (40 occurrences / 36.0% of failures):**
   - *Causes:* CSV DictWriter field mismatches (`dict contains fields not in fieldnames`), array shape mismatches during raster operations, invalid threshold value bounds.
2. **`AttributeError` (21 occurrences / 18.9% of failures):**
   - *Causes:* Calling missing or deprecated methods on rasterio/geopandas/shapely objects (e.g., calling deprecated `shapely.ops.transform` or accessing non-existent attributes on DatasetReader).
3. **`TypeError` (18 occurrences / 16.2% of failures):**
   - *Causes:* Incompatible data types passed to GDAL/numpy functions (e.g., floating-point indices into arrays, passing lists where ndarrays are required).
4. **`FileNotFoundError` (10 occurrences / 9.0% of failures):**
   - *Causes:* Incorrect file path references inside the container (e.g., trying to access host paths like `data/sample.tif` instead of mounted sandbox paths `/workspace/input/sample.tif`).
5. **`rasterio.errors.RasterioIOError` (9 occurrences / 8.1% of failures):**
   - *Causes:* Attempting to open unmounted or non-existent files, band index out of bounds, incompatible projection/CRS read attempts.
6. **`NameError` (8 occurrences / 7.2% of failures):**
   - *Causes:* Unimported functions or variable scope leaks in generated scripts.
7. **`KeyError` (4 occurrences / 3.6% of failures):**
   - *Causes:* Missing expected keys in GeoJSON feature properties or raster metadata dictionaries.

---

## 3. Comparison: Historical vs Recent 6 Tasks (Oct 22, 2026)

### Analysis of the 6 Most Recent Tasks
The 6 recent task runs analyzed:
- `20261022_185202_task_1` (5 attempts)
- `20261022_185240_task_2` (5 attempts)
- `20261022_185329_task_3` (5 attempts)
- `20261022_195950_task_1` (4 attempts)
- `20261022_200025_task_2` (4 attempts)
- `20261022_200153_task_3` (6 attempts)

---

### Detailed Attempt Breakdown & Comparison

| Metric / Dimension | Historical Pattern (Oct 1 - Oct 18) | Recent Tasks (Oct 22) | Observed Shift / Improvement |
| :--- | :--- | :--- | :--- |
| **Primary Failure Cause** | File path errors (`FileNotFoundError`), `RasterioIOError`, raw `NameError` / syntax errors. | CSV dictionary schema mismatch (`ValueError: dict contains fields not in fieldnames`), `AssertionError` in legend validation. | **Path errors eliminated.** Sandbox pathing instructions (`/workspace/input/`) are now respected on attempt 1. |
| **Deprecation Warnings** | Not captured or causing execution halts. | Deprecation warnings present (`shapely.ops.transform()` deprecation), but execution completes. | Non-fatal warnings no longer block artifact generation. |
| **Self-Correction Speed** | High attempt count (up to 16 attempts per task, avg 5.5). | Lower attempt count (4 to 6 attempts per task, avg 4.8). | **12.7% reduction** in retries needed before final completion. |
| **Final Task Outcome** | 96.6% success rate (2/58 failed completely). | **100% success rate (6/6 succeeded).** | All tasks successfully generated valid `.tif`, `.png`, `.geojson`, and `.csv` deliverables. |
| **Plan Formulation Quality** | Generic plans, limited limitation disclosures. | Rigorous hypothesis framing, band metadata uncertainty disclosures, explicit limit statements. | Plans explicitly declare band/calibration limits prior to code execution. |

---

### Specific Error Instances & Self-Correction in Recent Tasks

#### Instance 1: CSV DictWriter Field Mismatch (`ValueError`)
- **Occurred in:** `20261022_185202_task_1` (Attempt 2), `20261022_185329_task_3` (Attempt 3)
- **Error Stack:** `ValueError: dict contains fields not in fieldnames: 'interpretive_note', 'history_code'` and `'class_code'`
- **What Happened:** Generated code constructed summary records with additional metadata keys not declared in the `csv.DictWriter` header list.
- **Harness Recovery:** Harness returned stack trace -> LLM updated `fieldnames` parameter to include extra dictionary keys -> Attempt 3/4 succeeded.

#### Instance 2: Legend Handle Label Assertion Failure (`AssertionError`)
- **Occurred in:** `20261022_185240_task_2` (Attempt 4)
- **Error Stack:** `AssertionError` on `assert all(f'{classes[a]} → {classes[b]}' in [h.get_label() for h in handles] for a,b in pairs)`
- **What Happened:** Strict assertion check verified Matplotlib plot legend labels against class pairs, but unicode arrow formatting (`→`) differed.
- **Harness Recovery:** LLM simplified label formatting in script -> Attempt 5 generated `landcover_2016.png` and `landcover_2024.png` cleanly.

#### Instance 3: Multi-Attempt Refinement without Code Crash
- **Occurred in:** `20261022_195950_task_1` (Attempts 1-4), `20261022_200025_task_2` (Attempts 1-4)
- **What Happened:** Python code executed with exit code 0 on early attempts, but visual/numerical check sub-agents flagged quality or legend formatting deficiencies.
- **Harness Recovery:** Auto-retry triggered based on visual/quality critique -> LLM regenerated script with enhanced colormaps and threshold masks -> Final attempt approved.

---

## 4. Key Findings & Honesty Check

1. **Has improvement occurred? YES, but with specific nuances:**
   - **Pathing and IO Errors are SOLVED:** Historical runs frequently failed attempt 1 due to host vs container path confusion (`data/file.tif` vs `/workspace/input/file.tif`). In recent runs, zero path errors occurred.
   - **Self-Correction is Working Reliably:** 100% of recent tasks resolved early attempt errors within 4-6 attempts.
   - **New Error Types Surface at Higher Standards:** As basic syntax/IO errors declined, new error types appeared (CSV schema strictness, legend handle assertions, visual review rejections). This represents progress from *runtime crash errors* to *output quality refinement*.

2. **Remaining Risk Areas:**
   - **Shapely Deprecation:** Scripts rely heavily on deprecated `shapely.ops.transform()`. While currently returning warnings, future library updates will break this.
   - **CSV Schema Rigidity:** `csv.DictWriter` errors recur across tasks when LLMs dynamically inject extra descriptive columns without registering them in headers.

---

## 5. Session Context & Execution Guidelines for Claude Code

When starting any query or task in this repository:
1. **First read this document (`claude code .md`)** to maintain full context.
2. **Never modify existing codebase files** unless explicitly instructed by the user.
3. **After executing queries or observations, update this document** with any new context, logs, or findings gathered during the session.

---
*Document initialized and verified: October 2026*

---

# Time Series and Classification Feasibility Analysis

### Executive Summary (Under 10 Lines)
- **Query Ambiguity:** "Amount of water" ambiguously denotes either surface water *area* (km²/ha, solvable via optical/SAR satellite imagery) or water *volume/level* (m³/depth, insolvable without bathymetry, gauge curves, or high-res DEMs). Current GeoLLM can answer **area**, not **volume**.
- **Current State:** Basic date extraction (`temporal.py`), 2-date index differencing (`change.py`), and NDWI/MNDWI indices (`indices.py`) exist. Gap-filling, seasonality removal, robust trend testing, water gain/loss transition masks, and machine learning classification are completely absent.
- **Environment Blockers:** The Docker sandbox has no network and lacks `scikit-learn`, `statsmodels`, and `pymannkendall`. Any classification must currently be synthesized ad-hoc in pure NumPy/SciPy.
- **Roadmap:** Proposed modular enhancements (`water.py`, `series.py`, `ml.py`), new visualizations (gain/loss/persistence maps, time series plots), strict validator assertions, and Docker package additions.

---

## Main Test Query Analysis
**Query:** *"How much did the water change in this place from the start date to the end date?"*  
*(Example: a lake or reservoir imaged in Jan 2020 and Jan 2025, or monthly over those 5 years).*

### Critical Ambiguity: Surface Area vs. Storage Volume
1. **Surface Water Area (km² or hectares):**
   - *Status:* **CAN BE ANSWERED** by the current architecture.
   - Optical satellites (Sentinel-2, Landsat) measure surface reflectance, enabling water delineation through normalized difference indices (NDWI, MNDWI). SAR satellites (Sentinel-1) detect low specular backscatter over calm open water. By thresholding these indices and multiplying pixel counts by ground pixel area (in projected CRS), horizontal water extent can be calculated.
2. **Water Volume or Level (m³, acre-feet, or gauge height):**
   - *Status:* **CANNOT BE ANSWERED** by the current architecture.
   - Volume requires third-dimension bathymetric surveys, water depth rating curves (area-elevation-volume curves), or radar/lidar altimetry. DEMs only capture exposed topography when the reservoir is dry; underwater bathymetry is invisible to optical satellites and standard DEMs. The repository contains no altimetry parsers, hydrodynamic models, or gauge station data.

---

## PART A: What Already Exists

### 1. Module Audit: Public Functions, Signatures & Limitations

#### `lib/geollm_lib/temporal.py`
- `acquisition_date(path) -> Optional[datetime.datetime]`:
  - *Inputs:* `path` (str or Path to raster).
  - *Outputs:* `datetime` object or `None`.
  - *Logic:* Inspects raster tags for `ACQUISITION_DATETIME`, `DATETIME`, `DATE`, `datetime`, `TIFFTAG_DATETIME`.
  - *Limits:* Fails silently (`None`) if GeoTIFF tags omit acquisition timestamps (e.g. standard processed TIFFs lacking STAC metadata).
- `order_by_date(paths) -> list[tuple[str, datetime.datetime]]`:
  - *Inputs:* `paths` (iterable of file paths).
  - *Outputs:* List of `(path, datetime)` sorted oldest first.
  - *Limits:* Raises fatal `ValueError` if *any* single file lacks a readable date; no graceful fallback.
- `index_stack(paths, name="ndvi") -> tuple[np.ndarray, list[datetime.datetime]]`:
  - *Inputs:* `paths` (list of rasters), `name` (index string).
  - *Outputs:* `(stack, dates)` where `stack` is 3D ndarray `(T, H, W)` and `dates` is list of `datetime`.
  - *Limits:* Hard assertion requiring every file to match the reference grid exactly (`src.crs == ref.crs`, `src.shape == ref.shape`, transform atol 1e-6); raises `ValueError` if rasters are not pre-aligned. Hardcoded to single index calculations; loads full multi-date stack into memory simultaneously.
- `trend_per_year(stack, dates) -> np.ndarray`:
  - *Inputs:* `stack` `(T, H, W)`, `dates` (list of `datetime`).
  - *Outputs:* 2D float32 array of least-squares linear slope (index units / year).
  - *Limits:* Ordinary least-squares (OLS) linear slope only; returns `NaN` where valid observations $< 3$. Highly sensitive to outliers and clouds; completely ignores seasonal cycles.
- `anomaly_zscore(stack) -> np.ndarray`:
  - *Inputs:* `stack` `(T, H, W)`.
  - *Outputs:* 2D float32 array of z-scores for the final time step relative to previous steps.
  - *Limits:* Requires $\ge 3$ dates. Assumes stationary Gaussian baseline; seasonal differences between dates yield false anomalies.
- `change_magnitude(a, b) -> np.ndarray`:
  - *Inputs:* `a`, `b` (2D arrays of same shape).
  - *Outputs:* `(b - a)` float32 array.
  - *Limits:* Naive difference without significance testing or classification.

#### `lib/geollm_lib/change.py`
- `index_difference(before_src, after_src, name="ndvi") -> tuple[np.ndarray, np.ndarray, np.ndarray]`:
  - *Inputs:* Open rasterio dataset readers `before_src`, `after_src`, `name` (str).
  - *Outputs:* `(before_index, after_index, difference_array)`.
  - *Limits:* Internal `_guard` strictly rejects identical filenames, identical `ACQUISITION_DATETIME` tags, and grid mismatches. Only computes single index difference.
- `significant_change(diff, direction="decrease", n_std=1.0, abs_threshold=None) -> tuple[np.ndarray, float]`:
  - *Inputs:* `diff` (2D ndarray), `direction` ("decrease" or "increase"), `n_std` (float), `abs_threshold` (optional float).
  - *Outputs:* `(boolean_mask, cutoff_value)`.
  - *Limits:* Symmetric statistical cutoff based on scene standard deviation; produces a single boolean mask. Does not track transitions (gain vs. loss vs. persistence).

#### `lib/geollm_lib/indices.py`
- `INDEX_DEFS`: Dictionary defining 8 multispectral indices:
  - `ndvi` (nir, red): Vegetation vigor.
  - `ndmi` (nir, swir1): Canopy moisture.
  - `nbr` (nir, swir2): Burn severity.
  - `ndwi` (green, nir): McFeeters open water.
  - `mndwi` (green, swir1): Xu modified open water.
  - `ndbi` (swir1, nir): Built-up/bare surfaces.
  - `savi` (nir, red): Soil-adjusted vegetation index ($L=0.5$).
  - `evi` (nir, red, blue): Enhanced vegetation index.
- `compute_index(name, src, bands=None) -> np.ndarray`:
  - *Inputs:* `name` (str), `src` (open raster reader), optional `bands` mapping dict.
  - *Outputs:* Float32 2D array with values in $[-1, 1]$ (NaN for nodata).
  - *Limits:* Automatically normalizes integer reflectances $>2$ (Sentinel-2 0..10000 scale) to $0..1$ via internal `_refl()`. Does NOT provide automated thresholding or binary masking.

#### `lib/geollm_lib/align.py`
- `same_grid(a, b) -> bool`:
  - *Outputs:* `True` if `crs`, `shape`, and `transform` match within 1e-6 tolerance.
- `align_to(ref, other_path, out_path=None, resampling="bilinear") -> str`:
  - *Inputs:* `ref` (open dataset reader), `other_path` (path to warp), `out_path` (target path), `resampling` (nearest, bilinear, cubic, average).
  - *Outputs:* String path to warped GeoTIFF.
  - *Limits:* Default `resampling="bilinear"` corrupts categorical masks or discrete classification maps unless caller manually overrides to `resampling="nearest"`.
- `gdal_info(path) -> dict`: Wraps CLI `gdalinfo -json`.
- `gdal_warp(sources, dst_path, crs=None, resolution=None, resampling="bilinear") -> str`: CLI wrapper for `gdalwarp`.
- `gdal_mosaic(sources, dst_path, resampling="nearest") -> str`: CLI mosaic wrapper.

#### `lib/geollm_lib/viz.py`
- `save_map(arr, path, title, cmap="RdYlGn", vmin=None, vmax=None)`: Saves continuous heatmap with colorbar.
- `save_mask_map(mask, path, title, background=None, color="red", label="Selected")`: Saves boolean mask overlaid on background with pixel count in legend.
- `save_class_map(classes, path, title, labels)`: Plots integer class raster with a fixed 5-color palette (`#1a9850`, `#d73027`, `#4575b4`, `#fdae61`, `#762a83`) plus gray for other.
- *Limits:* Completely lacks time series line plotting (`plt.plot`), comparative bar charts, confusion matrix heatmaps, or multi-class transition maps (gain/loss/stable).

---

### 2. Time Series Capabilities: Existing vs. Missing

| Time Series Capability | Exists in Repo? | Implementation Location | Missing / Limitations |
| :--- | :---: | :--- | :--- |
| **Date Extraction & Sorting** | **YES** | `temporal.py:13-34` (`acquisition_date`, `order_by_date`) | Fails if metadata tags lack ISO timestamps. |
| **Multi-date Stacking** | **YES** | `temporal.py:36-49` (`index_stack`) | Requires strict grid identity; loads all rasters into RAM simultaneously. |
| **Per-pixel Linear Trend** | **YES** | `temporal.py:51-66` (`trend_per_year`) | Ordinary least-squares only; non-robust to outliers; ignores seasonality. |
| **Baseline Anomaly Detection** | **YES** | `temporal.py:68-76` (`anomaly_zscore`) | Simple z-score against history; no seasonal cycle baseline. |
| **Temporal Gap Filling** | **NO** | *None* | No interpolation (linear, spline, Whittaker) for cloudy or missing dates. |
| **Seasonality Decomposition** | **NO** | *None* | No harmonic regression, Fourier terms, or STL decomposition. |
| **Non-parametric Trend Tests** | **NO** | *None* | No Mann-Kendall test, no Sen's slope estimator. |
| **Change-Point Detection** | **NO** | *None* | No BFAST, LandTrendr, CUSUM, or Pelt algorithms. |
| **Forecasting** | **NO** | *None* | No ARIMA, exponential smoothing, or predictive temporal models. |

---

### 3. Water Analysis Components Audit
- **Water Indices in `indices.py`:**
  - `ndwi` (Green, NIR) — McFeeters (1996): Defined at line 36.
  - `mndwi` (Green, SWIR1) — Xu (2006): Defined at line 37.
- **Water Mask Function:**
  - **MISSING.** There is no `water_mask()` function. `masks.py:25-29` has generic `threshold_mask(arr, value, keep="above")`, but no built-in dynamic thresholding (e.g. Otsu), shadow rejection, or water body extraction.
- **Pixel-Area Calculator with Projected CRS:**
  - **PARTIAL.** `masks.py:47-64` (`area_stats(mask, src)`) checks `src.crs.is_projected` and linear units `metre`/`meter`/`m`. It computes `px = abs(src.res[0] * src.res[1])` and outputs `area_hectares = count * px / 10000`. If CRS is geographic (degrees), it returns `area_hectares = None` with warning. However, it does not output `km²` directly.
- **Gain / Loss / Persistent Water Logic in `change.py`:**
  - **MISSING.** `change.py` provides only single-direction `significant_change` masks. It has no 3-state categorical transition logic:
    $$\text{Persistent Water} = M_{start} \land M_{end}$$
    $$\text{Water Loss} = M_{start} \land \neg M_{end}$$
    $$\text{Water Gain} = \neg M_{start} \land M_{end}$$

---

### 4. Classification Capabilities Audit
- **Existing Frameworks:** **NONE.** The codebase contains zero machine learning training routines, feature engineering pipelines, cross-validation splitters, or accuracy evaluators.
- **Runtime Generation:** Any classification that occurs is generated **purely at runtime by LLM-written code**. The model either:
  1. Hand-codes heuristic multi-index threshold rules (e.g. `(ndvi > 0.4) = 1`, `(mndwi > 0) = 2`).
  2. Uses unsupervised clustering from `scipy.cluster.vq.kmeans2` (which lacks supervised class label semantics).

---

### 5. Sandbox Environment & Installed Package Audit
Inspected `docker/Dockerfile`, `harness/doc_lookup.py:18-31`, and `harness/validator.py:4-6`:

| Library | Status in Container | Version / Location | Notes |
| :--- | :---: | :---: | :--- |
| **`numpy`** | **INSTALLED** | v2.4.6 (`Dockerfile:4`) | Full numerical array operations. |
| **`scipy`** | **INSTALLED** | v1.17.1 (`Dockerfile:4`) | Optimization, ndimage, distance transforms. |
| **`pandas`** | **INSTALLED** | v3.0.6 (`Dockerfile:4`) | Dataframe manipulation. |
| **`rasterio`** | **INSTALLED** | v1.4.4 (`Dockerfile:4`) | Geospatial raster I/O and warping. |
| **`geopandas`** | **INSTALLED** | v1.2.0 (`Dockerfile:4`) | Vector spatial operations. |
| **`shapely`** | **INSTALLED** | v2.2.0 (`Dockerfile:4`) | Computational geometry. |
| **`matplotlib`** | **INSTALLED** | v3.11.2 (`Dockerfile:4`) | Headless plotting (`Agg` backend). |
| **`scikit-learn`** | **MISSING** | *Blocked* | Blocked by `doc_lookup.py:52-58`; warned in `docker_runner.py:182-184`. |
| **`lightgbm`** | **MISSING** | *Not in Docker* | No gradient boosting available. |
| **`statsmodels`** | **MISSING** | *Not in Docker* | No statistical time series decomposition. |
| **`pymannkendall`**| **MISSING** | *Not in Docker* | No non-parametric trend tests. |
| **`ruptures`** | **MISSING** | *Not in Docker* | No change-point detection algorithms. |
| **`seaborn`** | **MISSING** | *Not in Docker* | No advanced statistical charting. |

*Critical Constraint:* Containers run with `network_mode="none"` (`harness/executor.py:88`). The LLM cannot install missing packages at runtime via `pip`. Any attempt to import uninstalled libraries aborts with `ModuleNotFoundError`.

---

## PART B: Pipeline Execution Trace for Water Queries

### Pipeline Path
1. `web_app.py` -> `orchestrator.py:145-185` (`TaskManager.submit_task()`) assigns a worker slot (`task_1`).
2. `pi_harness.py:88-133` (`solve()`) inspects datasets via `metadata.inspect_dataset(files)` and compiles prompt.
3. Subagent invokes `propose_plan` via `pi_extension/geollm.ts:157-197`; waits for human approval (`pi_harness.py:277`).
4. Upon approval, agent writes Python and calls `run_geospatial_code` (`geollm.ts:19-154`).
5. `docker_runner.py` validates preflight AST and allowed files (`docker_runner.py:30-49, 248-265`) and invokes `executor.py:43-109` to run the isolated container.
6. Post-execution verification pipeline executes sequentially:
   - `docker_runner.py:70-115` (`_validate` checks exit code, `result.json` summary, and file existence).
   - `numerical_check.py:79-163` (`check_outputs` inspects GeoTIFF CRS, valid mask percentages, and index value bounds).
   - `result_check.py:20-57` (`check_result` verifies summary, assumptions, percentage bounds, and metric area units).
   - `visual_check.py:8-75` (`check_images` runs vision model critique on up to 3 PNGs).
   - `final_check.py:10-64` (`check_requirements`, `judge`, `ground_numbers`).

---

### Case Analysis

#### Case 1 (Two Dates): *"Water change between start date and end date for this area."*
1. **Probable LLM Script:**
   - Calls `indices.compute_index("mndwi", src)` for both dates.
   - Applies fixed threshold `mndwi > 0.0` to obtain boolean water masks.
   - Computes pixel counts and areas via `masks.area_stats()`.
   - Computes net change: $\Delta = \text{Area}_{end} - \text{Area}_{start}$.
   - Plots masks via `viz.save_mask_map` and writes `result.json`.
2. **Failure Modes & Weaknesses:**
   - *CRS Error:* If inputs are geographic (`EPSG:4326`), `src.res` is in degrees. Calculating area without reprojecting to UTM yields degrees squared (meaningless for km²).
   - *Fixed Zero-Threshold Trap:* Fixed $0.0$ threshold fails on turbid water, shallow shores, or dark asphalt/mountain shadows, causing false water detections.
   - *Cloud & Shadow Contamination:* Unmasked cloud shadows exhibit low reflectance across optical bands and high apparent MNDWI, causing massive false water gains/losses.
   - *Seasonality Blindness:* Comparing January (dry season) to August (monsoon) detects normal seasonal reservoir oscillation, but the LLM reports it as permanent environmental change.
3. **Validator Capabilities:**
   - `numerical_check.py:123-127` catches empty (`sel == 0`) or 100% full (`sel == valid`) masks.
   - `result_check.py:49-52` checks if `hectare` is reported when CRS resolution is not in metres.
   - *Blindspots:* Cannot verify if water area exceeds total bounding box; cannot verify if identical thresholds were applied to both dates; cannot verify gain/loss consistency.
4. **Relevant Prompt Text:**
   - `prompts.py:41`: `"NDWI/MNDWI can be useful for open-water detection."`
   - `prompts.py:63-69`: `"Temporal analysis: Change analysis normally requires appropriate observations from multiple dates. Register/align datasets before pixel-wise comparison when necessary. Consider acquisition timing, seasonal effects, clouds, shadows, sensor differences..."`
   - `prompts.py:74-75`: `"Area calculations require an appropriate metric/equal-area CRS or another defensible area calculation method."`

#### Case 2 (Time Series): *"Show water area every month over 5 years and say if it is shrinking."*
1. **Probable LLM Script:**
   - Attempts to loop over 60 rasters, calling `temporal.index_stack()` or calculating MNDWI sequentially.
   - Fits an ordinary linear regression line over time using `np.polyfit()` or `temporal.trend_per_year()`.
   - Plots a line chart using `matplotlib.pyplot`.
2. **Failure Modes & Weaknesses:**
   - *Container OOM & Timeout:* Loading 60 scenes simultaneously into memory crashes the 2GB container RAM limit (`cfg.sandbox_memory`), triggering Docker OOM killer (`docker_runner.py:75-76`). Processing 60 scenes sequentially exceeds the 180s timeout (`docker_runner.py:74`).
   - *Missing Libraries:* The agent may try `import pymannkendall` or `import statsmodels` to assess trend significance, immediately failing with `ModuleNotFoundError`.
   - *Irregular Observations:* Cloud-covered months will be missing; simple linear regression treats unevenly spaced dates as continuous time steps.
   - *Visualization Gap:* `viz.py` has no time series plotting function; the agent must write custom matplotlib code from scratch, frequently failing on date axis formatting.
3. **Validator Capabilities:**
   - Validators evaluate individual GeoTIFFs and PNGs. They have no temporal logic to verify whether slopes match directional claims (shrinking vs. expanding) or whether R² / p-values are valid.
4. **Relevant Prompt Text:**
   - `prompts.py:68-69`: `"Do not claim causation when the available data only establishes correlation or spatial/temporal change."`
   - `pi_prompt.md:96`: `"Always read only the specific band indexes needed for your calculation... reading all bands into memory at once will cause Out-Of-Memory or Timeout."`

#### Case 3 (Classification): *"Classify land cover (water, vegetation, built-up, bare) using these labeled points, then report water change."*
1. **Probable LLM Script:**
   - Discovers that `scikit-learn` is missing.
   - Either crashes trying `from sklearn.ensemble import RandomForestClassifier`, or attempts heuristic rule thresholding combining multiple indices (`mndwi > 0` for water, `ndvi > 0.4` for vegetation, `ndbi > 0` for built-up, rest bare).
   - Alternatively tries unsupervised clustering using `scipy.cluster.vq.kmeans2`.
2. **Failure Modes & Weaknesses:**
   - *Missing ML Stack:* Lack of Random Forest, SVM, or Gradient Boosting prevents supervised classification.
   - *Spatial Auto-correlation & Leakage:* If writing custom nearest-neighbor code, LLMs perform random point splitting instead of spatial block splitting, causing severe overfitting.
   - *Threshold Gaps and Overlaps:* Multi-index rule heuristics leave ambiguous unclassified pixels or assign pixels to multiple classes simultaneously.
   - *No Accuracy Metrics:* Fails to generate confusion matrices, producer's/user's accuracy, or Kappa statistics.
3. **Validator Capabilities:**
   - `numerical_check.py:100` only recognizes binary masks (`{0, 1, 255}`). A 4-class integer raster (`{0, 1, 2, 3}`) is flagged as a continuous float raster.
   - Validators do not check for confusion matrices, overall accuracy, or spatial independence of test points.
4. **Relevant Prompt Text:**
   - `prompts.py:78-85`: `"Land-cover classes: Terms such as agricultural, forest, urban, wetland or residential are semantic classes, not automatically equivalent to one spectral index... Do not pretend an index alone proves a land-cover class."`
   - `pi_prompt.md:94-95`: `"Machine learning frameworks like scikit-learn (sklearn), torch, tensorflow, and cv2 are NOT installed. For clustering, classification, or filtering, use scipy (e.g. scipy.cluster.vq.kmeans2, scipy.ndimage) or standard numpy."`

---

## PART C: Recommended Design (Specification Only)

### 1. Architectural Placement
- **New Library Modules in `lib/geollm_lib/`:**
  - `lib/geollm_lib/water.py`: Water body extraction, dynamic Otsu thresholding, cloud/shadow exclusion, and 3-state transition analysis.
  - `lib/geollm_lib/series.py`: Memory-chunked time-series aggregation, gap filling, and non-parametric trend testing.
  - `lib/geollm_lib/ml.py`: Supervised classifiers (Random Forest wrappers), spatial CV splitters, and classification metric evaluations.
- **Prompt Guidance (`harness/prompts.py` & `harness/pi_prompt.md`):** Add explicit rules governing water change accounting (gain/loss/persistence), temporal seasonality matching, and spatial validation.
- **Tool Registry (`harness/pi_extension/geollm.ts`):** Retain `run_geospatial_code` as the core execution tool, but register new module signatures in `doc_lookup.py` for Context7 lookup.

---

### 2. Proposed Function Signatures

```python
# ==============================================================================
# lib/geollm_lib/water.py
# ==============================================================================

def water_mask(
    src,
    index: str = "mndwi",
    threshold: str | float = "otsu",
    cloud_mask: Optional[np.ndarray] = None
) -> tuple[np.ndarray, float]:
    """
    Computes a boolean water mask from a raster reader using MNDWI or NDWI.
    If threshold='otsu', dynamically computes the bimodal threshold on valid pixels.
    Returns (water_mask_bool_2d, applied_threshold_float).
    """
    ...

def pixel_area_km2(src) -> float:
    """
    Returns single pixel area in square kilometers.
    Enforces that src.crs is projected with metric linear units; raises ValueError if geographic.
    """
    ...

def water_change(
    before_src,
    after_src,
    index: str = "mndwi",
    threshold: str | float = "otsu"
) -> dict:
    """
    Calculates 3-state water transition between two dates.
    Returns dict:
      - 'transition_raster': 2D int8 array (0=Non-water, 1=Persistent, 2=Lost, 3=Gained)
      - 'start_area_km2': float
      - 'end_area_km2': float
      - 'persistent_km2': float
      - 'loss_km2': float
      - 'gain_km2': float
      - 'net_change_km2': float (gain - loss)
      - 'net_change_percent': float
      - 'threshold_before': float
      - 'threshold_after': float
    """
    ...

# ==============================================================================
# lib/geollm_lib/series.py
# ==============================================================================

def water_area_series(
    paths: list[str],
    index: str = "mndwi",
    threshold: float = 0.0,
    chunk_size: int = 1024
) -> pd.DataFrame:
    """
    Iterates over temporal rasters in spatial chunks to prevent container OOM.
    Returns DataFrame with columns: ['date', 'water_pixels', 'water_area_km2', 'valid_pixels'].
    """
    ...

def trend_test(
    dates: list[datetime.datetime],
    values: list[float] | np.ndarray
) -> dict:
    """
    Performs Mann-Kendall non-parametric monotonic trend test and Sen's slope estimator.
    Returns dict:
      - 'trend': str ('increasing', 'decreasing', 'no_trend')
      - 'p_value': float
      - 'sens_slope_per_year': float
      - 'tau': float
      - 'significant': bool (p < 0.05)
    """
    ...

def fill_temporal_gaps(
    df: pd.DataFrame,
    date_col: str,
    value_col: str,
    method: str = "linear"
) -> pd.DataFrame:
    """
    Resamples irregularly spaced time-series to regular intervals (e.g. monthly 'MS')
    and fills gaps using linear interpolation or spline smoothing.
    """
    ...

# ==============================================================================
# lib/geollm_lib/ml.py
# ==============================================================================

def spatial_train_test_split(
    gdf,
    label_col: str,
    test_size: float = 0.3,
    buffer_dist_m: float = 1000.0
) -> tuple:
    """
    Performs spatial block train/test splitting to prevent spatial autocorrelation leakage.
    Returns (train_gdf, test_gdf).
    """
    ...

def train_classifier(
    X_train: np.ndarray,
    y_train: np.ndarray,
    model_type: str = "random_forest",
    n_estimators: int = 100
) -> object:
    """
    Trains a supervised classifier (e.g. RandomForestClassifier).
    Returns fitted model object.
    """
    ...

def classification_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    class_names: dict[int, str]
) -> dict:
    """
    Computes confusion matrix, overall accuracy, per-class precision, recall, and F1-score.
    Returns structured dictionary matching result.json contract.
    """
    ...
```

---

### 3. Required Docker Packages
To support time series and machine learning, update `docker/Dockerfile`:
- `scikit-learn`: Random Forest, spatial splitting, confusion matrices, classification metrics.
- `statsmodels`: Time series decomposition (STL), seasonal adjustment.
- `pymannkendall`: Non-parametric Mann-Kendall trend tests and Sen's slope calculation.
- `seaborn`: Statistical charting and confusion matrix heatmaps.

---

### 4. Prompt Rules to Add
1. **Seasonal Matching Rule:** When computing multi-year water change, compare acquisitions from the same season/month to prevent dry vs. wet seasonal false positives.
2. **Projected CRS Rule:** Surface area must be computed in a metric projected coordinate system (e.g., UTM / Equal Earth). If data is geographic (WGS84 degrees), reprojecting via `align_to()` is mandatory.
3. **Transition Mass-Balance Rule:** Water change must report all three components: Gain, Loss, and Persistent water. Net change must equal Gain minus Loss.
4. **Consistent Thresholding Rule:** Both before and after scenes must use identical, justified index thresholds.
5. **Spatial Independence Rule:** When training classifiers on geospatial points, random splitting is prohibited; spatial block cross-validation must be used.
6. **Classification Verification Rule:** All classification models must report Overall Accuracy, a full Confusion Matrix, and per-class Precision and Recall.

---

### 5. New Validator Assertions
- In `harness/numerical_check.py`:
  - `check_transition_consistency()`: For transition rasters, verifies pixel values strictly adhere to `{0: Non-water, 1: Persistent, 2: Loss, 3: Gain}`.
  - `check_area_bounds()`: Asserts reported water area is strictly $\le$ total bounding box area.
  - `check_classifier_metrics()`: If classification is performed, asserts confusion matrix exists in `result.json` and overall accuracy $\in [0, 1]$.
- In `harness/result_check.py`:
  - Enforces `net_change_km2 == pytest.approx(gain_km2 - loss_km2, rel=1e-3)`.
  - Asserts time series trend directions ('shrinking' vs. 'expanding') strictly match the mathematical sign of Sen's slope.

---

### 6. Visualization Enhancements

| Visualization Type | Function in `viz.py` | Status | Design Specification |
| :--- | :--- | :---: | :--- |
| **Continuous Index Map** | `save_map()` | **EXISTS** | RdYlGn / Viridis colormap with colorbar. |
| **Binary Mask Map** | `save_mask_map()` | **EXISTS** | Single boolean mask over grayscale background. |
| **Discrete Land Cover Map** | `save_class_map()` | **EXISTS** | Integer classes with legend patches. |
| **Water Transition Map** | `save_transition_map()` | **NEW** | 3-color map: Blue=Persistent, Red=Lost Water, Green=New Water, Gray=Land. |
| **Before / After Bar Chart** | `save_comparison_bar()` | **NEW** | Side-by-side bar chart showing $t_{start}$ vs. $t_{end}$ area with delta bracket. |
| **Monthly Area Time Series** | `save_timeseries_plot()` | **NEW** | Date vs. Area line plot with Sen's slope trend line and 95% confidence ribbon. |
| **Confusion Matrix Heatmap** | `save_confusion_matrix()` | **NEW** | Normalized matrix heatmap showing predicted vs. actual classes with colorbar. |

---

### 7. Deliverables & CSV Schema Contract

#### Water Change Deliverables
- `water_start.tif`: Georeferenced binary water mask at start date.
- `water_end.tif`: Georeferenced binary water mask at end date.
- `water_transition.tif`: 4-class categorical transition GeoTIFF (0=Land, 1=Persistent, 2=Lost, 3=Gained).
- `water_transition_map.png`: Publication-grade map visualization with clear color legend.
- `water_area_trend.png`: Line plot of historical water area over time (if multi-date).
- `water_change_stats.csv`: Structured tabular accounting.

#### Standardized CSV Columns (`water_change_stats.csv`)
| Column | Type | Example | Description |
| :--- | :--- | :--- | :--- |
| `date` | str (ISO) | `2025-01-18` | Acquisition timestamp. |
| `water_area_km2` | float | `38.80` | Total water surface area. |
| `gain_km2` | float | `1.15` | Area of newly emerged water. |
| `loss_km2` | float | `7.55` | Area of dried/lost water. |
| `net_change_km2` | float | `-6.40` | Net expansion or shrinkage. |
| `change_percent` | float | `-14.16` | Percentage change relative to start. |
| `method` | str | `MNDWI_Otsu` | Algorithm utilized. |
| `threshold_used` | float | `0.042` | Actual numerical index cutoff. |
| `cloud_mask_applied`| bool | `True` | Whether clouds/shadows were removed. |

---

## PART D: Risks and Implementation Order

### 1. Effort vs. Impact Ranking

| Rank | Component | Effort | Impact | Justification |
| :---: | :--- | :---: | :---: | :--- |
| **1** | `water.py` Module (Otsu + Area + Gain/Loss) | **LOW** | **HIGH** | Immediate reliability for water change queries; prevents CRS & threshold errors. |
| **2** | Visualizations (`save_transition_map`, `save_timeseries_plot`) | **LOW** | **HIGH** | High-signal UI deliverables; enables rapid visual verification. |
| **3** | Docker Image Package Update (`scikit-learn`, `statsmodels`) | **LOW** | **HIGH** | Unblocks machine learning and statistical time series without complex code. |
| **4** | `ml.py` Module (Spatial CV + Metrics) | **MED** | **HIGH** | Establishes rigorous supervised classification standards. |
| **5** | `series.py` Module (Chunked Loader + Mann-Kendall) | **MED** | **MED** | Prevents OOM crashes during long time series analysis. |
| **6** | Custom Deep Learning / Segmentation Models | **HIGH** | **LOW** | Premature; classical ML and index thresholding handle 95% of current tasks. |

---

### 2. Technical Risks & Constraints
1. **Container Memory & Timeout Limits:** Loading 60 Sentinel-2 scenes simultaneously in `index_stack()` exceeds the 2GB RAM container allocation and triggers OOM kills. *Mitigation:* `water_area_series()` must process scenes sequentially in chunks, storing only summary scalar statistics in memory.
2. **High Attempt Retry Overhead:** Historical data shows a 34.9% attempt failure rate and 5.5 attempts per task. Multi-step ML pipelines increase the surface area for code crashes. *Mitigation:* Provide robust, pre-tested helpers in `geollm_lib` so the LLM writes 10 lines of orchestration code rather than 150 lines of raw NumPy.
3. **Sensor Discrepancies:** Comparing Sentinel-2 (10m/20m) with Landsat 8 (30m) introduces radiometric and resolution biases. *Mitigation:* Prompt rules must require sensor matching or spatial resampling with explicit caveat statements in `result.json`.

---

### 3. Step-by-Step Implementation & Testing Plan
- **Step 1: Water Module & Unit Tests**
  - Implement `lib/geollm_lib/water.py`.
  - Test on `data/before_VH.tif` and `data/after_VH.tif` (or `S2_2024pre_B03.tif` / `S2_2024_B03.tif`).
  - Verify `pixel_area_km2()` raises error on WGS84 rasters and succeeds on UTM rasters.
- **Step 2: Transition Visualization**
  - Add `save_transition_map()` and `save_comparison_bar()` to `lib/geollm_lib/viz.py`.
  - Verify legend handles, label strings, and PNG color rendering.
- **Step 3: Dockerfile Update**
  - Add `scikit-learn`, `statsmodels`, `pymannkendall` to `docker/Dockerfile`.
  - Rebuild image (`docker build -t geollm-runtime -f docker/Dockerfile .`).
  - Update `harness/doc_lookup.py` whitelist to include the new packages.
- **Step 4: Machine Learning Helper**
  - Implement `lib/geollm_lib/ml.py`.
  - Test on synthetic points using `geopandas.GeoDataFrame` to verify spatial block train/test splitting.
- **Step 5: Time Series Chunking & Trend Testing**
  - Implement `lib/geollm_lib/series.py`.
  - Test on a 12-month synthetic raster stack; verify peak RAM consumption stays $< 500\text{ MB}$.
- **Step 6: Validator Enforcement**
  - Add transition consistency and area bound checks to `harness/numerical_check.py` and `harness/result_check.py`.

---

### 4. Expected Answer Format for the Water Query
When the user asks: *"How much did the water change in this place from the start date to the end date?"*, the system should produce:

> **Surface Water Change Analysis:**
> Surface water area in the target region changed from **45.20 km²** on 2020-01-15 to **38.80 km²** on 2025-01-18, representing a net reduction of **-6.40 km² (-14.16%)**.
> 
> **Transition Accounting:**
> - **Persistent Water:** 37.65 km² remained submerged across both dates.
> - **Water Loss (Dried):** 7.55 km² transitioned from water to dry land.
> - **Water Gain (New):** 1.15 km² of previously dry land became inundated.
> 
> **Methodology & Assumptions:**
> - **Sensor:** Sentinel-2 L2A (10m/20m bands).
> - **Index & Threshold:** Modified Normalized Difference Water Index (MNDWI) using dynamic Otsu thresholding (cutoff = 0.042).
> - **Seasonal Control:** Both scenes acquired in mid-January to minimize seasonal drawdown bias.
> - **Projection:** Areas computed in UTM Zone 40N (EPSG:32640).
> - **Deliverables Generated:** `water_transition.tif`, `water_transition_map.png`, and `water_change_stats.csv`.

---

## Questions for the User
1. **Target Imagery Archive:** What sensor imagery (Sentinel-2 L2A, Landsat 8/9, Sentinel-1 SAR) will be primarily used for your multi-year lake/reservoir monitoring?
2. **Time Series Resolution:** For 5-year queries, will you be analyzing quarterly/annual snapshots (2–10 scenes) or dense monthly/bi-weekly stacks (60–120 scenes)?
3. **Classification Ground Truth:** Do you have reference vector training points (shapefile/GeoJSON) for land cover classes, or do you expect the system to generate training labels from spectral threshold heuristics?
4. **Volume Needs:** Do you require bathymetric depth estimation in the future, and if so, do you have access to regional DEMs or reservoir stage-storage rating curves?

