FROM python:3.11-slim

# GDAL command-line tools (Rasterio ships its own GDAL inside, this adds gdalinfo/gdalwarp)
RUN apt-get update && apt-get install -y --no-install-recommends gdal-bin \
    && rm -rf /var/lib/apt/lists/*

# Python geospatial libraries, installed once at build time (needs internet now, never again)
RUN pip install --no-cache-dir numpy rasterio geopandas shapely matplotlib

# Our library, importable as `import geollm_lib`
COPY lib/ /opt/geollm/
ENV PYTHONPATH=/opt/geollm

# Run as a normal user, not root
RUN useradd -m runner
USER runner
WORKDIR /workspace