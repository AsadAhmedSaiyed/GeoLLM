import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import ListedColormap


def save_map(arr, path, title, cmap="RdYlGn", vmin=None, vmax=None):
    fig, ax = plt.subplots(figsize=(8, 8))
    im = ax.imshow(arr, cmap=cmap, vmin=vmin, vmax=vmax)
    ax.set_title(title)
    ax.axis("off")
    fig.colorbar(im, ax=ax, shrink=0.7)
    fig.savefig(str(path), dpi=150, bbox_inches="tight")
    plt.close(fig)


def save_mask_map(mask, path, title, background=None, color="red"):
    """Selected pixels in `color`, over an optional grayscale background array."""
    mask = np.asarray(mask, bool)
    fig, ax = plt.subplots(figsize=(8, 8))
    if background is not None:
        ax.imshow(background, cmap="gray")
    else:
        ax.imshow(np.zeros(mask.shape), cmap="gray", vmin=0, vmax=1)
    ax.imshow(np.ma.masked_where(~mask, np.ones(mask.shape)), cmap=ListedColormap([color]), alpha=0.75)
    ax.set_title(title)
    ax.axis("off")
    fig.savefig(str(path), dpi=150, bbox_inches="tight")
    plt.close(fig)