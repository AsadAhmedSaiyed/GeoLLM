FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends gdal-bin \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir \
    numpy \
    scipy \
    pandas \
    rasterio \
    geopandas \
    shapely \
    pyogrio \
    matplotlib \
    scikit-learn==1.5.2 \
    statsmodels==0.14.4 \
    ruptures==1.1.9
COPY lib/ /opt/geollm/
ENV PYTHONPATH=/opt/geollm
RUN useradd -m runner
USER runner
WORKDIR /workspace

