import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import ListedColormap, to_rgb


def save_map(arr, path, title, cmap="RdYlGn", vmin=None, vmax=None):
    """Continuous map with a colour bar."""
    fig, ax = plt.subplots(figsize=(8, 8))
    im = ax.imshow(arr, cmap=cmap, vmin=vmin, vmax=vmax)
    ax.set_title(title)
    ax.axis("off")
    fig.colorbar(im, ax=ax, shrink=0.7)
    fig.savefig(str(path), dpi=150, bbox_inches="tight")
    plt.close(fig)


def save_mask_map(mask, path, title, background=None, color="red", label="Selected"):
    """Selected pixels in `color` over a grayscale background (array) with a legend. Says so if nothing is selected."""
    mask = np.asarray(mask, bool)
    fig, ax = plt.subplots(figsize=(8, 8))
    if background is not None:
        ax.imshow(background, cmap="gray")
    else:
        ax.imshow(np.full(mask.shape, 0.85), cmap="gray", vmin=0, vmax=1)
    ax.imshow(np.ma.masked_where(~mask, np.ones(mask.shape)), cmap=ListedColormap([color]), alpha=0.75)
    ax.set_title(title + ("  (no pixels selected)" if not mask.any() else ""))
    ax.axis("off")
    ax.legend(handles=[mpatches.Patch(color=color, label=f"{label} ({int(mask.sum())} px)")], loc="lower left")
    fig.savefig(str(path), dpi=150, bbox_inches="tight")
    plt.close(fig)


def save_class_map(classes, path, title, labels):
    """classes: int array (0 = other); labels: {1: 'Healthy', 2: 'Stressed'}. Draws one colour per class with a legend."""
    palette = ["#1a9850", "#d73027", "#4575b4", "#fdae61", "#762a83"]
    other = "#dddddd"
    img = np.zeros(classes.shape + (3,))
    img[:] = to_rgb(other)
    handles = []
    for i, (k, name) in enumerate(labels.items()):
        c = palette[i % len(palette)]
        img[classes == k] = to_rgb(c)
        handles.append(mpatches.Patch(color=c, label=f"{name} ({int((classes == k).sum())} px)"))
    handles.append(mpatches.Patch(color=other, label="Other"))
    fig, ax = plt.subplots(figsize=(8, 8))
    ax.imshow(img)
    ax.set_title(title)
    ax.axis("off")
    ax.legend(handles=handles, loc="lower left")
    fig.savefig(str(path), dpi=150, bbox_inches="tight")
    plt.close(fig)