# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Geospatial analysts, earth scientists, and GIS practitioners who need automated, reliable analysis on satellite imagery (Sentinel-2, EMIT hyperspectral, Landsat) without writing custom geospatial Python scripts. Secondary audiences include remote sensing researchers benchmarking autonomous AI agent execution in isolated sandboxes.

## Product Purpose

GeoLLM automates end-to-end geospatial image processing and raster analysis through natural language. It removes manual scripting bottlenecks by translating user questions into validated Python pipelines that run inside isolated Docker sandboxes and produce verifiable map deliverables (GeoTIFFs, PNGs, GeoJSONs, statistical reports). Success means analysts obtain correct, quality-inspected geospatial outputs without security risks or environment setup friction.

## Positioning

Unlike cloud-dependent geospatial APIs or general-purpose code assistants, GeoLLM runs fully offline with zero network exposure in isolated containers. Local sub-agents autonomously draft execution plans, run Python scripts against local multi-band/hyperspectral rasters, inspect deliverables using a vision model, and self-correct defects before handing back deliverables.

## Operating Context

- Local desktop and workstation environments running Python 3.11+, Docker Desktop, and Ollama.
- Inputs: Large multi-spectral and hyperspectral satellite rasters (`.tif`, `.tiff`, `.geojson`, `.csv`) stored in `data/`.
- Execution: Multi-container concurrent sandboxes (`task_1`, `task_2`, `task_3`) with human-in-the-loop plan approval gates.
- Output: Standard geospatial artifacts (GeoTIFF rasters, classified PNG maps, vector GeoJSON contours, spectral signature CSVs) rendered in a unified browser workbench with canvas GeoRaster previews.

## Capabilities and Constraints

- Up to 3 concurrent worker sandboxes with real-time SSE telemetry (streaming text, reasoning/thinking, tool starts/finishes with exit codes and durations, vision inspection passes).
- Zero-network Docker execution to ensure security and determinism.
- Resilient SSE streams with 15s keepalives, monotonic event replay via `Last-Event-ID`, and a 5s fallback polling loop.
- Deliverables strictly scoped to the final succeeded run attempt to eliminate intermediate file duplicates.
- Band role mappings (e.g. Red, NIR, SWIR, Green, Blue) and auto-inspection of dataset dimensions and projections.

## Brand Commitments

- Brand Name: GeoLLM (Astryx Autonomous Geospatial Workbench).
- Voice: Technical, precise, transparent, operational, high-signal telemetry.
- Aesthetics: Dark/light hybrid technical workbench styling (Inter and JetBrains Mono fonts, high-density telemetry, clear status pills, Claude Code-style activity feeds).

## Evidence on Hand

- Real multi-band datasets in `data/` (Sentinel-2 bands, EMIT hyperspectral reflectance rasters with 285 bands).
- Canonical run artifacts in `runs/20261019_125539_task_1` (confidence maps, material maps, spectral signature CSVs/PNGs, vector contours).
- Validated harness infrastructure (`harness/orchestrator.py`, `harness/pi_harness.py`, `harness/docker_runner.py`, `harness/visual_check.py`).

## Product Principles

1. **Deterministic, Isolated Execution**: All code runs inside fresh, zero-network Docker containers; no unexpected side effects or external data leaks.
2. **True Sub-Agent Transparency**: Telemetry displays the model's actual thoughts, streaming text, tool invocations, and vision critiques verbatim—never canned or hardcoded status strings.
3. **Canonical Deliverable Integrity**: Only final, succeeded attempt artifacts are surfaced to analysts; intermediate failures and scratch logs remain isolated.
4. **Human-in-the-Loop Safeguards**: Complex analysis plans pause for operator review and feedback before substantive code execution begins.

## Accessibility & Inclusion

- High-contrast telemetry tags, status pills, and typography hierarchy optimized for analytical dashboards.
- Clear mono-spaced code and JSON review drawers.
- Keyboard-accessible inspection controls and canvas previews for raster outputs.
