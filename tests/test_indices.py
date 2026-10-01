import numpy as np
import rasterio
from rasterio.transform import from_origin
from geollm_lib.indices import compute_index


def make_tif(path, red, nir):
    data = np.stack([red, nir]).astype("uint16")
    with rasterio.open(path, "w", driver="GTiff", height=2, width=2, count=2,
                       dtype="uint16", crs="EPSG:32643",
                       transform=from_origin(0, 0, 10, 10), nodata=0) as dst:
        dst.write(data)


def test_ndvi(tmp_path):
    p = tmp_path / "t.tif"
    make_tif(p, np.array([[100, 200], [300, 0]]), np.array([[300, 200], [100, 0]]))
    with rasterio.open(p) as src:
        out = compute_index("ndvi", src, {"red": 1, "nir": 2})
    assert np.isclose(out[0, 0], 0.5)
    assert np.isclose(out[0, 1], 0.0)
    assert np.isclose(out[1, 0], -0.5)
    assert np.isnan(out[1, 1])   # NoData stays NaN