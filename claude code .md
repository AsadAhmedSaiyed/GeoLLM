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
