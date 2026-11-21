"""Unit tests for scientifically rigorous hyperspectral helpers and metadata inspection."""
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from geollm_lib.bands import BandError
from geollm_lib.hyperspectral import (
    absorption_feature_depth,
    bad_band_mask,
    band_at,
    band_wavelengths,
    continuum_removal,
    normalized_difference_nm,
    read_wavelength_subset,
    spectral_angle,
    spectral_ratio,
    spectral_signature,
    spectral_unmix,
)
from geollm_lib.metadata import inspect_dataset


def _write_hs_tif(path, cube, wavelengths, tag_mode="per_band", unit="", extra_tags=None):
    """Helper to write a synthetic hyperspectral GeoTIFF."""
    nb, h, w = cube.shape
    transform = from_origin(500000.0, 4000000.0, 30.0, 30.0)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=h,
        width=w,
        count=nb,
        dtype="float32",
        crs="EPSG:32633",
        transform=transform,
        nodata=np.nan,
    ) as dst:
        dst.write(cube.astype("float32"))
        if extra_tags:
            dst.update_tags(**extra_tags)
        if tag_mode == "dataset":
            dst.update_tags(wavelengths=",".join(str(x) for x in wavelengths))
            if unit:
                dst.update_tags(wavelength_unit=unit)
        elif tag_mode == "per_band":
            for i, wl in enumerate(wavelengths, start=1):
                if wl is not None:
                    val = f"{wl} {unit}".strip()
                    dst.update_tags(i, WAVELENGTH=val)
        elif tag_mode == "descriptions":
            for i, wl in enumerate(wavelengths, start=1):
                if wl is not None:
                    dst.set_band_description(i, f"{wl} {unit}".strip())


def test_band_wavelengths_nm_and_um(tmp_path):
    wl_nm = np.linspace(400.0, 2400.0, 21)
    cube = np.ones((21, 8, 8), dtype="float32") * 0.3

    # 1. Explicit nm in per-band tags
    p_nm = tmp_path / "hs_nm.tif"
    _write_hs_tif(p_nm, cube, wl_nm, tag_mode="per_band", unit="nm")
    with rasterio.open(p_nm) as src:
        wl, how = band_wavelengths(src)
        assert how == "explicit_unit"
        assert np.allclose(wl, wl_nm)
        assert band_at(src, 2200.0, tol=10.0) == 19

    # 2. Unitless micrometers (0.4 .. 2.4) in dataset tag
    p_um = tmp_path / "hs_um.tif"
    _write_hs_tif(p_um, cube, wl_nm / 1000.0, tag_mode="dataset")
    with rasterio.open(p_um) as src:
        wl, how = band_wavelengths(src)
        assert how == "assumed_um"
        assert np.allclose(wl, wl_nm)

    # 3. Missing QA band wavelength: strict fails, allow_missing=True succeeds
    p_qa = tmp_path / "hs_qa.tif"
    wl_with_qa = list(wl_nm[:5]) + [None]
    _write_hs_tif(p_qa, cube[:6], wl_with_qa, tag_mode="per_band", unit="nm")
    with rasterio.open(p_qa) as src:
        with pytest.raises(BandError):
            band_wavelengths(src, allow_missing=False)
        wl, _ = band_wavelengths(src, allow_missing=True)
        assert np.isfinite(wl[:5]).all()
        assert np.isnan(wl[5])


def test_bad_band_mask_water_vapor_and_bbl():
    wl = np.array([450.0, 850.0, 1380.0, 1420.0, 1650.0, 1850.0, 2200.0, 2340.0])
    good = bad_band_mask(wl, exclude_water_vapor=True)
    # 1380, 1420, 1850 are inside standard water-vapor absorption windows
    assert list(good) == [True, True, False, False, True, False, True, True]

    # Combine with sensor bbl tag masking band 0 (450 nm)
    tags = {"bbl": "{0, 1, 1, 1, 1, 1, 1, 1}"}
    good_bbl = bad_band_mask(wl, tags=tags, exclude_water_vapor=True)
    assert list(good_bbl) == [False, True, False, False, True, False, True, True]


def test_read_wavelength_subset_and_ratios(tmp_path):
    wl = np.linspace(400.0, 2400.0, 51)  # 40 nm step
    cube = np.zeros((51, 6, 6), dtype="float32")
    for i, w in enumerate(wl):
        cube[i] = w / 1000.0  # encode wavelength/1000 as reflectance value

    p = tmp_path / "hs_sub.tif"
    _write_hs_tif(p, cube, wl, tag_mode="dataset", unit="nm")
    with rasterio.open(p) as src:
        sub, actual, idxs = read_wavelength_subset(src, [600.0, 840.0, 2200.0], tol=25.0)
        assert sub.shape == (3, 6, 6)
        assert np.allclose(actual, [600.0, 840.0, 2200.0])
        assert np.allclose(sub[0], 0.6)
        assert np.allclose(sub[2], 2.2)

        rat = spectral_ratio(src, 2200.0, 600.0, tol=25.0)
        assert np.allclose(rat, 2.2 / 0.6, atol=1e-4)

        nd = normalized_difference_nm(src, 840.0, 600.0, tol=25.0)
        assert np.allclose(nd, (0.84 - 0.60) / (0.84 + 0.60), atol=1e-4)


def test_continuum_removal_and_absorption_depth():
    # Synthetic SWIR spectrum (2050..2350 nm) with a Gaussian Al-OH absorption dip at 2200 nm
    wl = np.linspace(2050.0, 2350.0, 31)  # 10 nm step
    baseline = 0.4 + 0.0002 * (wl - 2050.0)  # gentle linear slope
    dip = 0.15 * np.exp(-0.5 * ((wl - 2200.0) / 18.0) ** 2)
    spec = (baseline - dip).astype("float32")

    cr_1d = continuum_removal(wl, spec)
    assert cr_1d.shape == (31,)
    # Endpoints lie on the upper convex hull
    assert np.isclose(cr_1d[0], 1.0, atol=1e-5)
    assert np.isclose(cr_1d[-1], 1.0, atol=1e-5)
    # Minimum must occur at 2200 nm (index 15) and be significantly < 1.0
    assert int(np.nanargmin(cr_1d)) == 15
    assert cr_1d[15] < 0.75

    # 3D cube with a NaN pixel
    cube = np.broadcast_to(spec[:, None, None], (31, 4, 4)).copy()
    cube[:, 0, 0] = np.nan
    cr_3d = continuum_removal(wl, cube)
    assert cr_3d.shape == (31, 4, 4)
    assert np.isnan(cr_3d[:, 0, 0]).all()
    assert np.allclose(cr_3d[:, 2, 2], cr_1d, atol=1e-5)

    # Linear continuum absorption depth at 2200 nm between 2120 and 2280 nm
    depth_1d = absorption_feature_depth(wl, spec, feature_nm=2200.0, left_nm=2120.0, right_nm=2280.0, tol=10.0)
    assert 0.25 < depth_1d < 0.45

    depth_3d = absorption_feature_depth(wl, cube, feature_nm=2200.0, left_nm=2120.0, right_nm=2280.0, tol=10.0)
    assert depth_3d.shape == (4, 4)
    assert np.isnan(depth_3d[0, 0])
    assert np.isclose(depth_3d[2, 2], depth_1d, atol=1e-5)


def test_spectral_unmix_fcls_and_streaming(tmp_path):
    wl = np.linspace(450.0, 2400.0, 40)
    # 3 linearly independent synthetic endmembers (vegetation, soil/clay, carbonate)
    em_veg = 0.05 + 0.45 / (1.0 + np.exp(-(wl - 710.0) / 15.0)) - 0.25 * np.exp(-0.5 * ((wl - 1900.0) / 120.0) ** 2)
    em_clay = 0.25 + 0.0001 * (wl - 450.0) - 0.12 * np.exp(-0.5 * ((wl - 2200.0) / 25.0) ** 2)
    em_carb = 0.35 - 0.00005 * (wl - 450.0) - 0.14 * np.exp(-0.5 * ((wl - 2340.0) / 25.0) ** 2)
    endmembers = np.vstack([em_veg, em_clay, em_carb]).astype("float32")

    true_fracs = np.array([0.5, 0.3, 0.2], dtype="float32")
    mixed = (true_fracs[:, None] * endmembers).sum(axis=0)  # (40,)
    cube = np.broadcast_to(mixed[:, None, None], (40, 10, 10)).copy()
    cube[:, 0, 0] = np.nan

    # 1. Direct NumPy cube FCLS
    abund, rmse = spectral_unmix(cube, endmembers, method="fcls")
    assert abund.shape == (3, 10, 10)
    assert rmse.shape == (10, 10)
    assert np.isnan(abund[:, 0, 0]).all()
    assert np.all(abund[:, 5, 5] >= 0.0)
    assert np.isclose(abund[:, 5, 5].sum(), 1.0, atol=1e-4)
    assert np.allclose(abund[:, 5, 5], true_fracs, atol=1e-2)
    assert rmse[5, 5] < 1e-3

    # 2. Streamed rasterio dataset with small block_size=4
    p = tmp_path / "hs_mix.tif"
    _write_hs_tif(p, cube, wl, tag_mode="dataset", unit="nm")
    with rasterio.open(p) as src:
        abund_s, rmse_s = spectral_unmix(src, endmembers, method="fcls", block_size=4)
        assert np.allclose(abund_s[:, 5, 5], true_fracs, atol=1e-2)
        assert np.isnan(abund_s[:, 0, 0]).all()
        assert rmse_s[5, 5] < 1e-3

        # 3. Streamed spectral_angle with water-vapor exclusion
        good = bad_band_mask(wl, exclude_water_vapor=True)
        good_idxs = [i + 1 for i, ok in enumerate(good) if ok]
        ang = spectral_angle(src, mixed[good], band_indices=good_idxs, block_size=4)
        assert ang.shape == (10, 10)
        assert np.isnan(ang[0, 0])
        assert np.isclose(ang[5, 5], 0.0, atol=1e-4)

        # 4. Spectral signature over valid mask
        wl_sig, mean_sig = spectral_signature(src, band_indices=good_idxs)
        assert len(wl_sig) == len(good_idxs)
        assert np.allclose(mean_sig, mixed[good], atol=1e-4)


def test_metadata_inspect_hyperspectral_summary(tmp_path):
    # 60-band hyperspectral GeoTIFF spanning 400..2465 nm (35 nm step)
    wl = np.linspace(400.0, 2465.0, 60)
    cube = np.ones((60, 16, 16), dtype="float32") * 0.25
    p = tmp_path / "emit_like.tif"
    _write_hs_tif(p, cube, wl, tag_mode="per_band", unit="nm")

    facts = inspect_dataset([p])
    info = facts["files"]["emit_like.tif"]
    assert info["band_count"] == 60
    assert info["bands_truncated"] is True
    assert len(info["bands"]) == 10  # pixel sampling stays fast/capped
    ss = info["spectral_summary"]
    assert ss["is_hyperspectral"] is True
    assert ss["wavelength_count"] == 60
    assert np.isclose(ss["min_nm"], 400.0)
    assert np.isclose(ss["max_nm"], 2465.0)
    assert ss["flagged_bad_or_water_vapor_bands"] > 0
    assert ss["good_bands_excl_water_vapor"] < 60
