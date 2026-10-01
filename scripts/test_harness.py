import sys
sys.path.insert(0, ".")
from harness.executor import run_code

# 1. Real analysis in the container
code = '''
import rasterio
from geollm_lib.indices import compute_index
from geollm_lib.stats import raster_stats
from geollm_lib.result import save_result
with rasterio.open("/workspace/input/sentinel2_small.tif") as src:
    ndvi = compute_index("ndvi", src, {"red": 3, "nir": 4})
save_result(raster_stats(ndvi))
'''
res = run_code(code, ["data/sentinel2_small.tif"], "runs/manual_ok")
print({k: v for k, v in res.items() if k != "result"}); print(res["result"])

# 2. Network must be blocked
res = run_code("import socket; socket.create_connection(('1.1.1.1', 53), timeout=3)",
               ["data/sentinel2_small.tif"], "runs/manual_net")
print("network test ->", res["exit_code"], res["stderr"][-150:])

# 3. Infinite loop must be killed
res = run_code("while True: pass", ["data/sentinel2_small.tif"], "runs/manual_timeout", timeout=5)
print("timeout test ->", res["timed_out"])