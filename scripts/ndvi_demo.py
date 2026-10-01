import sys
sys.path.insert(0, "lib")
import rasterio
from geollm_lib.indices import compute_index
from geollm_lib.stats import raster_stats
from geollm_lib.io import write_raster
from geollm_lib.viz import save_map

path, red, nir = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
with rasterio.open(path) as src:
    ndvi = compute_index("ndvi", src, {"red": red, "nir": nir})
    print(raster_stats(ndvi))
    write_raster("outputs/ndvi.tif", ndvi, src)
    save_map(ndvi, "outputs/ndvi.png", "NDVI", vmin=-1, vmax=1)