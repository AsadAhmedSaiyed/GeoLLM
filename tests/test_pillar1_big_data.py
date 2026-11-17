"""Tests for Pillar 1: Big-Data Engine, Out-of-Core Processing, and Scientific Hydrology."""
import tempfile
from pathlib import Path
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

import geollm_lib.raster as graster
from geollm_lib.indices import _nd, compute_index
from geollm_lib.terrain import calculate_twi
from geollm_lib.lidar import read_point_cloud


@pytest.fixture
def sample_raster_file(tmp_path):
    """Creates a synthetic 2-band float32 GeoTIFF file."""
    p = tmp_path / "test_geo.tif"
    h, w = 128, 128
    transform = from_origin(55.0, 25.0, 0.0001, 0.0001)

    profile = {
        "driver": "GTiff",
        "height": h,
        "width": w,
        "count": 2,
        "dtype": "float32",
        "crs": "EPSG:4326",
        "transform": transform,
        "tiled": True,
        "blockxsize": 64,
        "blockysize": 64,
    }

    # Band 1 = Red (0.1..0.4), Band 2 = NIR (0.4..0.8)
    b1 = np.full((h, w), 0.2, dtype=np.float32)
    b2 = np.full((h, w), 0.6, dtype=np.float32)

    with rasterio.open(p, "w", **profile) as dst:
        dst.write(b1, 1)
        dst.write(b2, 2)

    return p


def test_raster_chunks_open_and_save(sample_raster_file, tmp_path):
    """Tests lazy chunked opening and saving using Dask and xarray."""
    da = graster.open_raster_chunks(sample_raster_file, chunk_size=(64, 64))
    assert graster.is_chunked(da)
    assert da.shape == (2, 128, 128)

    # Calculate NDVI lazily on Dask chunks
    red = da.sel(band=1)
    nir = da.sel(band=2)
    ndvi_lazy = (nir - red) / (nir + red)

    assert graster.is_chunked(ndvi_lazy)

    out_p = tmp_path / "out_ndvi_chunks.tif"
    saved = graster.save_raster_chunks(ndvi_lazy, out_p, chunk_size=(64, 64))
    assert Path(saved).exists()

    with rasterio.open(saved) as src:
        assert src.shape == (128, 128)
        arr = src.read(1)
        # (0.6 - 0.2) / (0.6 + 0.2) = 0.4 / 0.8 = 0.5
        assert np.allclose(arr, 0.5, atol=1e-4)


def test_stream_window_blocks(sample_raster_file, tmp_path):
    """Tests bounded-memory streaming window blocks."""
    out_p = tmp_path / "streamed_out.tif"

    def double_val(block):
        return block * 2.0

    graster.stream_window_blocks(sample_raster_file, out_p, double_val, block_size=32)
    assert out_p.exists()

    with rasterio.open(out_p) as src:
        assert src.count == 2
        b1 = src.read(1)
        assert np.allclose(b1, 0.4, atol=1e-4)


def test_indices_support_dask_arrays():
    """Tests that spectral indices work seamlessly on Dask arrays without crashing."""
    import dask.array as da

    red_np = np.full((32, 32), 0.2, dtype=np.float32)
    nir_np = np.full((32, 32), 0.6, dtype=np.float32)

    red_da = da.from_array(red_np, chunks=(16, 16))
    nir_da = da.from_array(nir_np, chunks=(16, 16))

    out_dask = _nd(nir_da, red_da)
    computed = out_dask.compute()
    assert np.allclose(computed, 0.5, atol=1e-4)


def test_twi_v_valley_convergence():
    """
    Tests that calculate_twi correctly routes water flow:
    In a V-shaped valley, water converges at the center furrow, giving higher TWI at the bottom.
    """
    # Create a 21x21 V-shaped valley sloping down toward the center column (c=10)
    # and also sloping gently down from north to south (r=0..20)
    rows, cols = 21, 21
    r_coords, c_coords = np.mgrid[0:rows, 0:cols]

    # Valley floor is at c = 10. Elevation increases as |c - 10|
    valley_slope = np.abs(c_coords - 10) * 5.0
    longitudinal_slope = (20 - r_coords) * 1.0
    dem = (valley_slope + longitudinal_slope).astype(np.float32)

    dx, dy = 10.0, 10.0  # 10m grid
    twi, accum, slope_deg = calculate_twi(dem, dx, dy, return_components=True)

    # Accumulation at the valley bottom (c=10) should be much higher than on the ridges (c=0 or c=20)
    assert accum[15, 10] > accum[15, 0]
    assert accum[15, 10] > accum[15, 20]

    # TWI at the valley bottom must be substantially higher than at the dry ridge
    assert twi[15, 10] > twi[15, 0]
    assert twi[15, 10] > twi[15, 20]
    assert np.all(np.isfinite(twi))

    # Inject a deep artificial pit at (r=10, c=10) in the valley channel and verify Priority-Flood
    # routes water past the pit to the downstream outlet at (r=18, c=10).
    dem_with_pit = dem.copy()
    dem_with_pit[10, 10] = -50.0
    twi_filled, accum_filled, _ = calculate_twi(dem_with_pit, dx, dy, fill_depressions=True, return_components=True)
    assert accum_filled[18, 10] > accum_filled[5, 10]


def test_chunked_point_cloud_reading(tmp_path):
    """Tests chunked ASCII point cloud reading with bounding box filtering."""
    p = tmp_path / "test_points.xyz"
    # Write 100 points
    with open(p, "w") as f:
        for i in range(100):
            # x in 0..99, y in 100..199, z in 10..109
            f.write(f"{float(i)} {float(i + 100)} {float(i + 10)}\n")

    # Read with max_points = 20
    x, y, z = read_point_cloud(p, max_points=20, chunk_size=10)
    assert len(x) == 20
    assert x[0] == 0.0
    assert x[-1] == 19.0

    # Read with spatial bounding box filter: x in [40..59] and return_classification=True
    x_sub, y_sub, z_sub, cls_sub = read_point_cloud(
        p, bbox=(40.0, 140.0, 59.0, 159.0), chunk_size=15, return_classification=True
    )
    assert len(x_sub) == 20
    assert len(cls_sub) == 20
    assert np.all(x_sub >= 40.0)
    assert np.all(x_sub <= 59.0)
