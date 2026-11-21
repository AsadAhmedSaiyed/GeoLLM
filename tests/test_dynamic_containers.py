import pytest
import httpx
from pathlib import Path

from harness.resource_sizer import estimate_job_resources, next_memory_tier, get_host_budget_gb
from harness.orchestrator import TaskManager
from web_app import app


def test_resource_sizer_tiers(tmp_path):
    small_file = tmp_path / "tiny.tif"
    small_file.write_bytes(b"0" * 1024)
    prof_small = estimate_job_resources("Compute NDVI stats", [str(small_file)])
    assert prof_small.tier == "small"
    assert prof_small.memory == "4g"

    prof_heavy_q = estimate_job_resources("3D terrain flow accumulation and watershed", [str(small_file)])
    assert prof_heavy_q.tier == "small"
    assert prof_heavy_q.memory_gb == 4.0

    lidar_file = tmp_path / "scan.laz"
    lidar_file.write_bytes(b"0" * 2048)
    prof_lidar = estimate_job_resources("Canopy height model", [str(lidar_file)])
    assert prof_lidar.tier == "small"
    assert prof_lidar.memory_gb == 4.0

    nxt = next_memory_tier("4g")
    if get_host_budget_gb() >= 8.0:
        assert nxt == "8g"


def test_task_manager_dynamic_slots(tmp_path):
    tm = TaskManager(runs_dir=tmp_path)
    assert "task_1" in tm.tasks
    assert "task_2" in tm.tasks
    assert "task_3" in tm.tasks

    t4 = tm.create_task()
    assert t4 is not None
    assert t4.task_id == "task_4"
    assert "task_4" in tm.tasks

    cap = tm.capacity()
    assert cap["total_containers"] == 4
    assert cap["budget_ram_gb"] >= 8.0

    assert tm.delete_task("task_4") is True
    assert "task_4" not in tm.tasks
    assert not (tmp_path / "task_4").exists()
    assert tm.delete_task("task_1") is False


@pytest.mark.anyio
async def test_api_dynamic_tasks_lifecycle():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r_list = await client.get("/api/tasks")
        assert r_list.status_code == 200
        body = r_list.json()
        assert "capacity" in body
        assert body["capacity"]["max_containers"] >= 4

        r_create = await client.post("/api/tasks/create")
        assert r_create.status_code == 200
        new_id = r_create.json()["task_id"]
        assert new_id.startswith("task_")

        r_del = await client.delete(f"/api/tasks/{new_id}")
        assert r_del.status_code == 200
        assert r_del.json()["deleted"] == new_id

        r_reset = await client.post("/api/tasks/task_1/reset")
        assert r_reset.status_code == 200
