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


def test_landsat_c2l2_optical_and_thermal_scaling(tmp_path):
    from datetime import datetime
    from geollm_lib.indices import to_surface_reflectance, to_celsius, compute_index
    from geollm_lib.sar import is_db
    from geollm_lib.series import ols_trend, mann_kendall, sens_slope, change_points
    from harness import api_doc, doc_lookup

    # 1. USGS Landsat C2L2 optical scaling: reflectance = DN * 0.0000275 - 0.2
    # Red = 0.05 -> DN = 9091; NIR = 0.35 -> DN = 20000 -> true NDVI = (0.35 - 0.05)/(0.35 + 0.05) = 0.75
    red_dn = np.full((2, 2), 9091.0, dtype="float32")
    nir_dn = np.full((2, 2), 20000.0, dtype="float32")
    tags = {"collection": "landsat-c2-l2"}
    r_refl = to_surface_reflectance(red_dn, tags=tags)
    n_refl = to_surface_reflectance(nir_dn, tags=tags)
    assert np.allclose(r_refl, 0.05, atol=1e-3)
    assert np.allclose(n_refl, 0.35, atol=1e-3)
    ndvi = (n_refl - r_refl) / (n_refl + r_refl)
    assert np.allclose(ndvi, 0.75, atol=1e-3)

    # 2. USGS Landsat C2L2 thermal scaling: Kelvin = DN * 0.00341802 + 149.0 -> 300 K (26.85 C) at DN = 44177.6
    th_dn = np.full((2, 2), 44177.6, dtype="float32")
    lst_c = to_celsius(th_dn, tags=tags)
    assert np.allclose(lst_c, 26.85, atol=0.05)

    # 3. SAR is_db resilience against isolated negative noise pixel in linear SAR
    lin_sar = np.full((10, 10), 0.15, dtype="float32")
    lin_sar[0, 0] = -1e-6
    assert is_db(lin_sar) is False

    # 4. Vectorized series trend & change_points NaN index mapping
    dates = [datetime(2020 + i, 5, 1) for i in range(6)]
    stack = np.zeros((6, 4, 4), dtype="float32")
    for t in range(6):
        stack[t] = 0.2 + 0.05 * t
    trend = ols_trend(stack, dates)
    mk = mann_kendall(stack)
    sen = sens_slope(stack, dates)
    assert np.allclose(trend["slope"], 0.05, atol=1e-3)
    assert np.all(mk["significant"])
    assert np.allclose(sen, 0.05, atol=1e-3)

    # 5. api_doc & doc_lookup registration of terrain, lidar, and laspy
    sigs = api_doc.signatures()
    assert "terrain" in sigs
    assert "lidar" in sigs
    assert "laspy" in doc_lookup.DOCKER_INSTALLED_PACKAGES