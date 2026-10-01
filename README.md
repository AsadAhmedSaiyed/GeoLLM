# GeoLLM

Offline geospatial analysis: a local LLM writes Python that runs in a fresh, no-network Docker container.

## Flow
User question -> local LLM (Qwen2.5-Coder 7B via Ollama) -> harness (validate, retry, log) -> Docker -> structured result

## Setup
1. Install Python 3.11+, Docker Desktop, Ollama
2. `ollama pull qwen2.5-coder:7b`
3. `python -m venv .venv && source .venv/Scripts/activate`
4. `pip install -r requirements.txt`
5. `docker build -f docker/Dockerfile -t geollm-runtime .`
6. Put a GeoTIFF in `data/` (e.g. a Sentinel-2 sample from Microsoft Planetary Computer)

## Run
`python main.py "Calculate NDVI and give statistics" data/sample.tif --bands "red=3,nir=4"`

## Supported
NDVI/EVI stats and maps, threshold/percentage queries, refusals for impossible requests.

## Not validated yet
Two-date vegetation loss, NDMI/NBR on files with SWIR bands, other sensors.