"""Context7 Safe Documentation Lookup Service for GeoLLM.

Ensures that:
1. Lookups are strictly whitelisted to match the Docker container's installed packages.
2. Uninstalled packages are blocked immediately with suggestions.
3. Live, version-accurate documentation is retrieved from Context7.
4. Responses are cached locally to ensure 0ms latency on repeated queries.
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

# EXACT WHITELIST OF PACKAGES INSTALLED IN DOCKER (geollm-runtime / geollm-runtime-ts)
DOCKER_INSTALLED_PACKAGES = {
    "affine": {"version": "3.0.1", "context7_id": "/rasterio/affine"},
    "contourpy": {"version": "1.3.3", "context7_id": "/matplotlib/contourpy"},
    "geopandas": {"version": "1.2.0", "context7_id": "/geopandas/geopandas"},
    "matplotlib": {"version": "3.11.2", "context7_id": "/matplotlib/matplotlib"},
    "numpy": {"version": "2.4.6", "context7_id": "/numpy/numpy"},
    "pandas": {"version": "3.0.6", "context7_id": "/pandas-dev/pandas"},
    "pillow": {"version": "12.3.0", "context7_id": "/python-pillow/Pillow"},
    "pyogrio": {"version": "0.13.0", "context7_id": "/geopandas/pyogrio"},
    "pyproj": {"version": "3.7.2", "context7_id": "/pyproj4/pyproj"},
    "rasterio": {"version": "1.4.4", "context7_id": "/rasterio/rasterio"},
    "scipy": {"version": "1.17.1", "context7_id": "/scipy/scipy"},
    "shapely": {"version": "2.2.0", "context7_id": "/shapely/shapely"},
    "scikit-learn": {"version": "1.5.2", "context7_id": "/scikit-learn/scikit-learn"},
    "sklearn": {"version": "1.5.2", "context7_id": "/scikit-learn/scikit-learn"},
    "statsmodels": {"version": "0.14.4", "context7_id": "/statsmodels/statsmodels"},
    "ruptures": {"version": "1.1.9", "context7_id": "/deepcharles/ruptures"},
}

CACHE_DIR = Path(__file__).resolve().parent.parent / "runs" / ".context7_cache"


def _sanitize_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name)


def lookup_docs(package: str, query: str) -> str:
    """Fetch official Context7 documentation for an installed package.
    
    Strictly verifies that package is inside the Docker runtime environment.
    """
    pkg = package.lower().strip()

    # Aliases
    if pkg in ("pil", "image"):
        pkg = "pillow"
    elif pkg == "scikit-learn":
        pkg = "sklearn"

    # 1. WHITELIST SECURITY CHECK: Block uninstalled packages
    if pkg not in DOCKER_INSTALLED_PACKAGES:
        allowed_list = ", ".join(sorted(DOCKER_INSTALLED_PACKAGES.keys()))
        return (
            f"BLOCKED: Library '{package}' is NOT installed in the Docker execution container.\n"
            f"Installed libraries: {allowed_list}.\n"
            f"If you need machine learning, clustering, or filtering, use 'geollm_lib.classify', 'geollm_lib.series', or 'scipy'."
        )

    pkg_info = DOCKER_INSTALLED_PACKAGES[pkg]
    lib_id = pkg_info["context7_id"]
    version = pkg_info["version"]

    # 2. LOCAL DISK CACHE CHECK (0ms latency for repeated lookups)
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_key = f"{_sanitize_name(pkg)}_{_sanitize_name(query)}.txt"
        cache_path = CACHE_DIR / cache_key
        if cache_path.exists():
            return cache_path.read_text(encoding="utf-8")
    except Exception:
        cache_path = None

    # 3. QUERY CONTEXT7 REST API
    url = "https://context7.com/api/v2/context?" + urllib.parse.urlencode({
        "libraryId": lib_id,
        "query": query,
    })

    headers = {
        "User-Agent": "GeoLLM-Agent/1.0",
        "Accept": "text/plain, application/json, */*",
    }
    api_key = os.environ.get("CONTEXT7_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            content = resp.read().decode("utf-8", errors="ignore").strip()

        if content:
            # Truncate to avoid context window blowup
            if len(content) > 3000:
                content = content[:3000] + "\n\n...[documentation truncated for brevity]..."

            result = (
                f"### Context7 Live Documentation: {pkg} (Installed v{version})\n"
                f"Query: {query}\n\n"
                f"{content}"
            )

            # Save to cache
            if cache_path:
                try:
                    cache_path.write_text(result, encoding="utf-8")
                except Exception:
                    pass

            return result

    except Exception as e:
        # Graceful fallback if network is unreachable
        return (
            f"Context7 API lookup failed for {pkg}.{query} ({e}).\n"
            f"Reference: '{pkg}' is installed at v{version} in the execution container."
        )

    return f"No specific documentation found for '{query}' in {pkg}."


def main():
    if len(sys.argv) < 3:
        print("Usage: python doc_lookup.py <package> <query>")
        sys.exit(1)

    package = sys.argv[1]
    query = " ".join(sys.argv[2:])
    print(lookup_docs(package, query))


if __name__ == "__main__":
    main()
