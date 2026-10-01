import matplotlib
matplotlib.use("Agg")  # no screen needed inside Docker
import matplotlib.pyplot as plt


def save_map(arr, path, title, cmap="RdYlGn", vmin=None, vmax=None):
    fig, ax = plt.subplots(figsize=(8, 8))
    im = ax.imshow(arr, cmap=cmap, vmin=vmin, vmax=vmax)
    ax.set_title(title)
    ax.axis("off")
    fig.colorbar(im, ax=ax, shrink=0.7)
    fig.savefig(str(path), dpi=150, bbox_inches="tight")
    plt.close(fig)