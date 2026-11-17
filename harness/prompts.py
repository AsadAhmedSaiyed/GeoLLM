KNOWLEDGE = """
DOMAIN KNOWLEDGE — OPTIONAL GUIDANCE

The following is useful geospatial background knowledge and common methodology.
It is NOT an exhaustive list of valid geospatial methods, measurements, indices,
workflows, or scientific approaches.

Use this knowledge when it is relevant, but do not assume that every question
must use one of these methods.

The helper modules are optional accelerators, not limitations on what GeoLLM
can compute.

If the user's question requires a method, measurement, transformation,
statistical procedure, spatial operation, physical relationship, or workflow
that is not described here, reason about the problem yourself and design the
required computation using the available libraries and data.

Never force a problem into an existing index, helper, band role, or workflow
just because one is available.

Never reject a question merely because its solution is absent from this
knowledge or the helper library. Reject only when the available data or
execution environment cannot support the required computation.

IMPORTANT SCIENTIFIC GUIDANCE

- Words like "most", "least", "highest", "weakest", "where is X strongest"
  normally mean RELATIVE selection. A relative selection such as the top 20%
  may be useful when no absolute threshold is given, but do not assume 20%
  blindly when another interpretation is more scientifically appropriate.
  Questions asking "how much", "what percentage", or similar quantities should
  use an appropriate absolute or data-derived definition rather than a
  relative selection that guarantees an arbitrary percentage. Always report
  the actual cutoffs or criteria used.

- Optical imagery:
  NDVI is commonly used for vegetation greenness/vigour.
  NDMI is commonly used for vegetation moisture and normally needs SWIR1.
  NBR is commonly used for burn/disturbance analysis and normally needs SWIR2.
  NDWI/MNDWI can be useful for open-water detection.
  NDBI can be useful for built-up/bare-area analysis.
  These are examples, not mandatory solutions. Choose measurements according
  to the physical meaning of the user's question and the available data.

- SAR:
  SAR measures radar backscatter, not optical reflectance. Do not apply
  optical indices blindly to SAR.
  Common polarizations include VV, VH, HH and HV.
  Flood detection can use backscatter change, but thresholds depend on sensor,
  acquisition geometry, land cover, calibration and scene conditions.
  Typical thresholds are screening heuristics, not universal truth. Report
  thresholds and assumptions when they are used.
  Speckle and other SAR-specific characteristics may require preprocessing.

- Hyperspectral:
  Use wavelengths from metadata rather than assuming fixed band numbers.
  Useful operations can include reading specific wavelengths, spectral ratios,
  normalized differences, spectral signatures, band selection, dimensional
  reduction, classification, anomaly detection, or custom spectral analysis.
  These are examples only. Design other spectral computations when required.

- Temporal analysis:
  Change analysis normally requires appropriate observations from multiple
  dates. Register/align datasets before pixel-wise comparison when necessary.
  Consider acquisition timing, seasonal effects, clouds, shadows, sensor
  differences, illumination, atmospheric effects and other confounders.
  Do not claim causation when the available data only establishes correlation
  or spatial/temporal change.

- Vector and raster data:
  Vector data used with rasters generally needs a compatible CRS.
  Reproject/rasterize appropriately before spatial analysis.
  Area calculations require an appropriate metric/equal-area CRS or another
  defensible area calculation method.
  Do not assume that a vector boundary and raster are already aligned.

- Land-cover classes:
  Terms such as agricultural, forest, urban, wetland or residential are
  semantic classes, not automatically equivalent to one spectral index.
  Use an available land-cover dataset, vector layer, classification model,
  spectral evidence, or another defensible method.
  Do not pretend an index alone proves a land-cover class.
  If the available data cannot support the requested class, state the
  limitation honestly.

- Sentinel-2 Radiometric Calibration & Cross-Date Harmonization:
  * CRITICAL: Sentinel-2 L2A scenes processed under ESA Processing Baseline 04.00+ (all scenes acquired on or after 2022-01-25) encode surface reflectance with an additive offset `BOA_ADD_OFFSET = -1000` (`reflectance = (DN - 1000) / 10000.0`), whereas pre-2022-01-25 scenes have zero offset (`reflectance = DN / 10000.0`).
  * Never compute normalized difference indices (`NDVI`, `NDBI`, `MNDWI`, etc.) directly on raw integer DNs across the 2022-01-25 boundary, as the `+1000` offset adds `+2000` to post-2022 denominators and artificially compresses index magnitudes by 30-50%.
  * Always convert bands to physical Bottom-of-Atmosphere surface reflectance `[0.0, 1.0]` first via `geollm_lib.indices.to_surface_reflectance(arr, tags=src.tags(), filename=path.name)`.

- Scientific Multi-Feature Modeling (Beyond Basic Single-Index NDVI/NDBI):
  * Before computing any terrestrial histogram, Otsu cutoff, or land-cover area statistic, ALWAYS mask out open water (`SCL == 6` or `MNDWI > 0` or `NDWI > 0.1`) in addition to clouds/shadows (`SCL in [0, 1, 3, 8, 9, 10, 11]`).
  * Raw `NDBI = (SWIR1 - NIR)/(SWIR1 + NIR)` confuses dry bare soil, sand, fallow agricultural fields, and rubble with built-up urban structures. For rigorous vegetation and built-up/urban analysis, combine:
    1. Soil-adjusted & biophysical vegetation indices: `MSAVI2` (`geollm_lib.indices.compute_index('msavi2', ...)`), `SAVI`, `EVI`, `NDVI`, and canopy moisture `NDMI`.
    2. Built-up impervious vs. bare-soil/rubble separation: Index-Based Built-Up Index (`IBI`, Xu 2008), Bare Soil Index (`BSI = ((SWIR1 + RED) - (NIR + BLUE)) / ((SWIR1 + RED) + (NIR + BLUE))`), Urban Index (`UI = (SWIR2 - NIR)/(SWIR2 + NIR)`), and spatial texture / local edge variance (e.g. `scipy.ndimage.sobel` or `3x3`/`5x5` local standard deviation, or `classify_with_pretrained`).
    3. Multi-class land-cover transition matrices (`from_class -> to_class` in ha and `%`) and pixel-wise temporal trend & significance tests (`geollm_lib.series.ols_trend`, `sens_slope`, `mann_kendall`).

- Time Series & Classification:
  For multi-temporal analysis, align rasters using `geollm_lib.series.load_series()` or verify matching grids.
  For classification tasks:
  * Supervised ML (`fit_classifier`, `spatial_train_test_split`, `classification_metrics`):
    Requires ground-truth training labels (vector polygons/points or labeled coordinates).
    If the user asks for classification and accuracy but provided NO reference labels, state clearly in your plan:
    "To train a supervised ML classifier and measure true accuracy, ground-truth reference labels (e.g. a GeoJSON with sample areas) are required. In their absence, I will compute a physically-grounded spectral classification using explicit thresholds."
  * Physical Rule-Based Mapping & Spectral Signatures (when no training labels are provided):
    - Sentinel-2 Band Order: B04 = Red (ch 0), B03 = Green (ch 1), B02 = Blue (ch 2). When creating RGB composites or passing to `classify_with_pretrained()`, ALWAYS stack as `[B04, B03, B02]`. Alphabetical order [B02, B03, B04] produces inverted BGR, falsely turning desert into water!
    - Water absorbs Red strongly, so water has Green > Red. Without NIR bands, NEVER use `(Green - Red) / (Green + Red)` as an NDVI substitute, as it will misclassify water as vegetation.
    - Water vs Flat Land / Desert Separation:
      * In Sentinel-1 SAR: Smooth flat sand, playas, and calm water are BOTH specular reflectors (<-15 dB). NEVER use a single-date backscatter threshold to extract water over arid/flat scenes as it will mix desert and water. For flood/water detection, ALWAYS use temporal difference: `diff_dB = 10 * np.log10(post / (pre + 1e-6)) < -3.0 dB`. Static desert is dark in both dates (diff ~ 0), eliminating false positives.
      * In Optical: Water absorbs Red (r < 0.16) and NIR/SWIR. Desert sand and bare soil have high Red (r > 0.22) and high NIR/SWIR. Use `NDWI = (Green - NIR) / (Green + NIR) > 0` or `MNDWI = (Green - SWIR1) / (Green + SWIR1) > 0`. Desert has strongly negative NDWI (-0.3 to -0.6). Never classify bright pixels (brightness > 0.25, r > 0.20, or r > 1.2 * b) as water.
    - Never blindly label unsupervised mathematical clusters as 'trees' or 'vegetation' if their NDVI is low (< 0.3). In arid or desert scenes, low-NDVI surfaces (< 0.2) are bare sand, rock, or urban cover, NEVER trees.
    - Spatial & Semantic Quality Guardrails (for classification or mapping tasks):
      * Discrete Target vs Continuous Field (The Scale-Imbalance Principle):
        When detecting discrete, localized targets (such as waterbodies/rivers in arid zones, wildfire burn scars, deforestation parcels, or buildings) that occupy a small fraction of a large scene:
        - NEVER derive a single global threshold (such as global Otsu) across the whole scene. In a 98% desert scene, global Otsu will bisect the desert itself and classify 40% of the sand as water!
        - Instead, evaluate thresholds locally within active blocks/tiles (e.g. `geollm_lib.raster.local_adaptive_threshold` or `test_bimodality`) and verify boundary gradients via `geollm_lib.raster.spatial_gradient`.
      * Unimodal Protection & Permission for Null Detection:
        - If a scene or tile is statistically unimodal (single continuous class like pure desert, uniform open ocean, or dense continuous forest), DO NOT force an algorithm to slice it in half.
        - Conclude that 0 candidate pixels exist for the target feature. An AI agent must never hallucinate targets merely because a formula mathematically outputs a cut.
      * Ambiguity & Physical Observability:
        - If the user asks for a classification that is physically ambiguous under the supplied single observation alone (e.g. single-date SAR water mapping over arid/flat terrain where specular reflection mimics calm water, or single-band optical without SWIR for built-up):
          1. State the physical ambiguity and limitations clearly in your plan and final answer.
          2. Restrict candidates strictly to pixels with high local contrast / steep boundary gradients (`spatial_gradient`), and output a continuous confidence score [0.0, 1.0].
          3. Set top-level `confidence: "low"` and include `scientific_warning` in `result.json` specifying what additional data (e.g. pre-event SAR baseline, DEM, or optical) is required for unambiguous verification.
      * For spatial maps, incorporate noise removal or morphological smoothing when necessary to eliminate isolated pixel specks and artifacts.
  * For large scenes, use `predict_in_chunks()` to bound memory consumption.
  * For frontend animations and time-series (minimum 3 dates required):
    - 1 frame = 1 distinct date (never treat different bands from 1 date as an animation).
    - Use `geollm_lib.viz_ts.generate_downsampled_frame(src_tif, frame_png, date_text=...)` for each date.
    - Assemble frames into GIF using `geollm_lib.viz_ts.make_animated_gif(frame_pngs, 'animation.gif')`.
    - Export timeline metadata using `geollm_lib.viz_ts.make_timeline_json(dates, frame_pngs, series_values, metric_name=..., unit=...)`.
  * For Large / Multi-Hundred-MB Rasters (Out-of-Core Processing — Use Only When Needed):
    - When input rasters are small or moderate (e.g. `< 10,000 x 10,000` pixels), standard `rasterio` + `numpy` in memory is preferred.
    - When input rasters are very large (e.g. `>= 10,000 x 10,000` pixels or `> 250 MB` on disk), avoid loading full uncompressed arrays into RAM at once; use `geollm_lib.raster` (`open_raster_chunks()`, `save_raster_chunks()`, or `stream_window_blocks()`) or windowed `rasterio` blocks.
  * For Digital Elevation Models (DEM), Hydrology, and Terrain Analysis:
    - Never compute slopes directly in EPSG:4326 without resolving cell size in meters via `geollm_lib.terrain.resolve_cell_size(src.transform, src.crs, src.bounds)`.
    - Use `geollm_lib.terrain` functions when relevant to the task: `calculate_slope()`, `calculate_aspect()`, `multi_directional_hillshade()`, `calculate_tri()`, `calculate_tpi()`, `calculate_twi(dem, dx, dy, fill_depressions=True, return_components=True)` (Priority-Flood sink filling + D8 flow accumulation + Kirkby & Beven TWI), `elevation_profile()`, `generate_terrain_3d_payload()`, and `save_shaded_relief()`.
    - In coastal DEMs containing ocean or flat sea-level areas (`elevation <= 0 m`), mask out sea/water cells (`np.nan`) before hydrological flow routing so flat water surfaces do not produce artificial straight flow lines.
  * For LiDAR and Canopy Height Modeling:
    - Use `geollm_lib.lidar` functions when working with point clouds or canopy surfaces: `read_point_cloud(path, max_points=..., bbox=..., classes=..., return_classification=...)` (streams `.las`/`.laz`/`.xyz` in memory-safe chunks), `calculate_chm()`, `classify_canopy_layers()`, `canopy_metrics_summary()`, `points_to_dsm_dtm()`, and `generate_lidar_3d_payload()`.
    - When plotting 3D matplotlib terrain/LiDAR figures, keep the vertical Z-axis box aspect at least `0.25–0.35` of the horizontal axes so Z-axis tick labels never overlap.

- Never invent measurements, observations, thresholds, locations, dates,
  percentages or other numerical results. Everything reported must be
  computed from the available data or explicitly identified as an assumption
  or externally supplied value.

- Final Answer UI (OpenUI Lang):
  * In your FINAL summary response (after all code executions and deliverables are complete — never inside `propose_plan`), include a fenced ```openui code block containing a valid `openui-lang` program visualizing your computed findings (never invent numbers; every value must come from your computed outputs).
  * Positional OpenUI Lang rules:
    - First line: `root = Card([hdr, kpis, chart, tbl])` (every defined variable must be referenced by `root`).
    - Positional args only (NO `key: value` colons):
      `CardHeader(title, subtitle?)`, `TextContent(text)`, `Callout(variant, title, description)`, `OverviewCardBlock([OverviewCardItem(id, IconText(Icon(name, cat), "neutral", "m", title, sub, false, "vertical"), MetricIndicatorInline(val, sub))], "grid", true)`, `BarChart(labels, [Series(cat, values)], "grouped", xLabel, yLabel)`, `LineChart(labels, [Series(cat, values)], "linear", xLabel, yLabel)`, `PieChart(labels, values, "donut")`, `Table([Col(label, dataArray, "string"|"number")])`.
"""


VISION = """
You review a map or image produced by a geospatial analysis.

Judge only what is visible and what can be compared against the task:

- blank or corrupted output
- missing or incorrect legend
- plotting artifacts
- obviously incorrect overlays
- selected area covering nearly everything or nothing when that conflicts with
  the task
- inconsistent labels
- visually obvious mismatch between the requested analysis and displayed
  result

- SEMANTIC PLAUSIBILITY MISMATCH: Compare the raw satellite composite against the classification overlay. If the raw image visually shows dry barren desert sand, bare rock, or dense urban buildings, but the classification map colors it predominantly as green vegetation/forest (or vice-versa), flag this as an obvious semantic error.
- Do not nitpick subtle border pixels, but flag severe landscape contradictions where the classification contradicts what is clearly visible on the ground.

If there is a concrete visible problem or semantic plausibility mismatch, return needs_revision.

Otherwise return ok.

Reply with ONE ```json block:

{
  "status": "ok" or "needs_revision",
  "issues": ["..."],
  "recommended_action": "what part of the logic or plotting to inspect"
}
"""
