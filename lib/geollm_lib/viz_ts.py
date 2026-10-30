"""
Time series and classification visualizers for GeoLLM.
Produces timeline.json and publication-quality figures for frontends and reports.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Sequence

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image


def plot_series(
    dates: list[datetime],
    values: list[float] | np.ndarray | pd.Series,
    out_path: str | Path,
    *,
    title: str = "Time Series",
    ylabel: str = "Value",
    trend: np.ndarray | None = None,
    change_dates: list[datetime] | None = None,
    dpi: int = 150,
) -> Path:
    """Plot 1D time series with optional trend line and change point markers."""
    fig, ax = plt.subplots(figsize=(10, 4.5), dpi=dpi)
    y = np.asarray(values)

    ax.plot(dates, y, marker="o", markersize=4, linestyle="-", color="#1f77b4", label="Observed")

    if trend is not None:
        ax.plot(dates, trend, linestyle="--", color="#d62728", label="Trend")

    if change_dates:
        for cd in change_dates:
            ax.axvline(cd, color="#2ca02c", linestyle=":", linewidth=1.8, label="Change Point")

    ax.set_title(title, fontsize=12, fontweight="bold")
    ax.set_xlabel("Date", fontsize=10)
    ax.set_ylabel(ylabel, fontsize=10)
    ax.grid(True, linestyle="--", alpha=0.6)

    handles, labels = ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    if by_label:
        ax.legend(by_label.values(), by_label.keys(), loc="best")

    fig.autofmt_xdate()
    fig.tight_layout()

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_confusion_matrix(
    cm: np.ndarray,
    class_names: list[str],
    out_path: str | Path,
    *,
    normalize: bool = True,
    title: str = "Confusion Matrix",
    cmap: str = "Blues",
    dpi: int = 150,
) -> Path:
    """Plot confusion matrix heatmap."""
    fig, ax = plt.subplots(figsize=(6, 5), dpi=dpi)
    data = cm.astype(float)
    if normalize:
        sums = data.sum(axis=1, keepdims=True)
        sums[sums == 0] = 1.0
        data = data / sums

    im = ax.imshow(data, interpolation="nearest", cmap=cmap)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

    ax.set(
        xticks=np.arange(data.shape[1]),
        yticks=np.arange(data.shape[0]),
        xticklabels=class_names,
        yticklabels=class_names,
        title=title,
        ylabel="True Label",
        xlabel="Predicted Label",
    )
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right", rotation_mode="anchor")

    fmt = ".2f" if normalize else "d"
    thresh = data.max() / 2.0
    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            val = data[i, j]
            text = f"{val:{fmt}}" if normalize else f"{int(cm[i, j])}"
            ax.text(
                j,
                i,
                text,
                ha="center",
                va="center",
                color="white" if val > thresh else "black",
            )

    fig.tight_layout()
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_feature_importance(
    importances: list[float] | np.ndarray,
    feature_names: list[str],
    out_path: str | Path,
    *,
    title: str = "Feature Importance",
    dpi: int = 150,
) -> Path:
    """Plot horizontal bar chart of feature importances."""
    fig, ax = plt.subplots(figsize=(8, max(4.0, len(feature_names) * 0.35)), dpi=dpi)
    imp = np.asarray(importances)
    indices = np.argsort(imp)

    ax.barh(range(len(indices)), imp[indices], color="#2b5c8f", align="center")
    ax.set_yticks(range(len(indices)))
    ax.set_yticklabels([feature_names[i] for i in indices])
    ax.set_xlabel("Relative Importance")
    ax.set_title(title, fontweight="bold")
    ax.grid(axis="x", linestyle="--", alpha=0.6)

    fig.tight_layout()
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_misclassification_map(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    out_path: str | Path,
    *,
    title: str = "Classification Accuracy Map (Green=Correct, Red=Error)",
    dpi: int = 150,
) -> Path:
    """Plot spatial 2D map showing correct vs misclassified pixels."""
    fig, ax = plt.subplots(figsize=(8, 7), dpi=dpi)
    H, W = y_true.shape
    rgb = np.zeros((H, W, 3), dtype=np.uint8)

    correct = (y_true == y_pred) & (y_true >= 0)
    incorrect = (y_true != y_pred) & (y_true >= 0) & (y_pred >= 0)

    rgb[correct] = [46, 204, 113]
    rgb[incorrect] = [231, 76, 60]

    ax.imshow(rgb)
    ax.set_title(title, fontsize=11, fontweight="bold")
    ax.axis("off")

    fig.tight_layout()
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def generate_downsampled_frame(
    src_path: str | Path,
    out_png_path: str | Path,
    max_dim: int = 512,
    *,
    date_text: str | None = None,
    title: str | None = None,
    cmap: str = "viridis",
    vmin: float | None = None,
    vmax: float | None = None,
    metric_label: str = "",
    dpi: int = 150,
) -> Path:
    """Generate a publication-quality colored map frame with burned-in date text and colorbar."""
    import rasterio

    src_p = Path(src_path)
    if not src_p.is_file():
        raise FileNotFoundError(f"Frame raster not found: {src_path}")

    with rasterio.open(src_p) as src:
        count = src.count
        if count >= 3:
            # 3-band RGB composite
            r = src.read(1, masked=True).filled(np.nan)
            g = src.read(2, masked=True).filled(np.nan)
            b = src.read(3, masked=True).filled(np.nan)
            rgb_bands = [r, g, b]
            stretched = []
            for ch in rgb_bands:
                valid_ch = ch[np.isfinite(ch)]
                if valid_ch.size:
                    p2, p98 = np.percentile(valid_ch, [2.0, 98.0])
                    denom = p98 - p2 if p98 > p2 else 1.0
                    stretched.append(np.clip((ch - p2) / denom, 0.0, 1.0))
                else:
                    stretched.append(np.zeros_like(ch))
            rgb_arr = np.stack(stretched, axis=-1)
            is_rgb = True
        else:
            arr = src.read(1, masked=True)
            data = arr.filled(np.nan)
            is_rgb = False

    fig, ax = plt.subplots(figsize=(6, 5), dpi=dpi)

    if is_rgb:
        ax.imshow(rgb_arr, origin="upper")
    else:
        valid_data = data[np.isfinite(data)]
        if valid_data.size:
            calc_min = float(np.nanpercentile(valid_data, 1.0)) if vmin is None else vmin
            calc_max = float(np.nanpercentile(valid_data, 99.0)) if vmax is None else vmax
        else:
            calc_min, calc_max = 0.0, 1.0

        im = ax.imshow(data, cmap=cmap, vmin=calc_min, vmax=calc_max, origin="upper")
        cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        if metric_label:
            cbar.set_label(metric_label, fontsize=9)
        cbar.ax.tick_params(labelsize=8)

    if title:
        ax.set_title(title, fontsize=10, fontweight="bold", pad=8)
    ax.axis("off")

    # Burn-in date banner badge in top-left corner
    if date_text:
        ax.text(
            0.03, 0.94,
            f" {date_text} ",
            transform=ax.transAxes,
            fontsize=9,
            fontweight="bold",
            color="white",
            va="top",
            ha="left",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#0f172a", edgecolor="#38bdf8", alpha=0.88, linewidth=1.2),
        )

    fig.tight_layout()
    out = Path(out_png_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, bbox_inches="tight", dpi=dpi)
    plt.close(fig)

    # Downsample if dimensions exceed max_dim
    with Image.open(out) as im_pil:
        if max(im_pil.size) > max_dim:
            im_pil.thumbnail((max_dim, max_dim), Image.Resampling.BILINEAR)
            im_pil.save(out)

    return out


def make_animated_gif(
    png_paths: Sequence[str | Path],
    out_gif_path: str | Path,
    duration_ms: int = 600,
    loop: int = 0,
) -> Path:
    """Assemble a sequence of per-date map PNGs into an animated GIF."""
    valid_paths = [Path(p) for p in png_paths if Path(p).is_file()]
    if len(valid_paths) < 2:
        raise ValueError(f"make_animated_gif requires at least 2 images, got {len(valid_paths)}")

    images = [Image.open(p) for p in valid_paths]
    # Ensure uniform size matching first image
    base_size = images[0].size
    resized = []
    for im in images:
        if im.size != base_size:
            resized.append(im.resize(base_size, Image.Resampling.BILINEAR))
        else:
            resized.append(im)

    out = Path(out_gif_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    resized[0].save(
        out,
        save_all=True,
        append_images=resized[1:],
        duration=duration_ms,
        loop=loop,
    )
    for im in images:
        im.close()

    return out


def make_timeline_json(
    dates: list[datetime],
    frame_files: list[str],
    series_values: list[float] | None = None,
    *,
    out_path: str | Path = "timeline.json",
    title: str = "Time Series Timeline",
    unit: str = "",
    metric_name: str | None = None,
    colorbar_min: float | None = None,
    colorbar_max: float | None = None,
) -> Path:
    """Write strict timeline.json schema for the React frontend time slider with rich metadata."""
    if len(dates) != len(frame_files):
        raise ValueError("dates and frame_files must have equal length")

    frames = []
    for i, (d, f) in enumerate(zip(dates, frame_files)):
        val = float(series_values[i]) if (series_values and i < len(series_values)) else None
        fname = Path(f).name
        date_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
        label_str = f"{date_str}: {val:.3f} {unit}".strip() if val is not None else date_str
        frames.append({
            "index": i,
            "date": d.isoformat() if hasattr(d, "isoformat") else str(d),
            "file": fname,
            "value": val,
            "label": label_str,
            "png_url": None,
            "colorbar_min": colorbar_min,
            "colorbar_max": colorbar_max,
            "metric_name": metric_name or title,
        })

    payload = {
        "version": "1.0",
        "title": title,
        "metric_name": metric_name or title,
        "unit": unit,
        "total_frames": len(frames),
        "colorbar_min": colorbar_min,
        "colorbar_max": colorbar_max,
        "frames": frames,
    }

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, indent=2)
    return out

