import pytest
import httpx
from web_app import app

@pytest.mark.anyio
async def test_raster_stats_task1():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/raster/stats?path=task_1/outputs/landcover_2020-06.tif")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "stats" in data
        assert data["is_classified"] is True
        assert len(data["classes"]) >= 2

@pytest.mark.anyio
async def test_raster_stats_task2_classified():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/raster/stats?path=task_1/outputs/landcover_change_first_to_last_same_season.tif")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["is_classified"] is True
        assert len(data["classes"]) >= 2

@pytest.mark.anyio
async def test_raster_dynamic_png_render():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/raster/png?path=task_1/outputs/landcover_2020-06.tif&cmap=Viridis&vmin=1&vmax=3")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"
        assert len(r.content) > 100

@pytest.mark.anyio
async def test_raster_pixel_inspection():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/raster/pixel?path=task_1/outputs/landcover_2020-06.tif&lon=59.5&lat=45.0")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["inside"] is True

@pytest.mark.anyio
async def test_file_inspect_laz():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/file/inspect?path=autzen-classified.copc.laz")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["category"] == "lidar"
        assert data["point_count"] == 10653336
