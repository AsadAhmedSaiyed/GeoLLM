"""
Prompt additions and system guidance for Time Series and Classification workflows.
Additive module plugged into GeoLLM harness when time series/classification queries are detected.
"""

TIME_SERIES_GUIDELINES = """
### TIME SERIES AND CLASSIFICATION WORKFLOW RULES:
1. Multi-temporal stacks must be aligned:
   - Use `geollm_lib.series.load_series(paths)` or check `same_grid()` before stacking rasters.
   - For memory efficiency on large scenes, process in chunks or downsample when computing global trends.
2. In classification tasks:
   - Always prevent spatial data leakage: use spatial splitting (`spatial_train_test_split`) rather than naive random train/test splits.
   - Evaluate model metrics with `classification_metrics()` and save a confusion matrix heatmap via `geollm_lib.viz_ts.plot_confusion_matrix`.
   - Never classify entire large rasters in a single `model.predict(raster.reshape(-1, C))` call; use chunked/tiled prediction (`predict_in_chunks`).
   - For pre-trained universal land-use/infrastructure (EuroSAT 10-class), call `classify_with_pretrained('eurosat', rgb)` or `load_pretrained_model('eurosat')` directly without re-training.
3. Visualization:
   - For 1D temporal statistics, generate plots using `geollm_lib.viz_ts.plot_series`.
   - For interactive multi-date frontend previews, generate `timeline.json` using `geollm_lib.viz_ts.make_timeline_json` alongside downsampled PNG previews.
4. Progress tracking:
   - For iterative algorithms or chunked operations, print structured progress lines: `[PROGRESS] step=N/TOTAL percent=P message="Doing task"`
"""

def get_time_series_prompt_additions() -> str:
    """Return supplemental guidelines for the agent when running time-series tasks."""
    return TIME_SERIES_GUIDELINES

