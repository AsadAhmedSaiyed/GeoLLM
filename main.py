import argparse
import sys
from pathlib import Path

from harness.agent import solve

DATA = Path("data")
ROLES = ("blue", "green", "red", "nir", "swir1", "swir2")
EXT = {".tif", ".tiff", ".geojson", ".gpkg", ".json"}

p = argparse.ArgumentParser(description="Ask a question about the geospatial files in data/")
p.add_argument("question")
p.add_argument("files", nargs="*", help="file names in data/ (or paths). Default: the only raster in data/")
p.add_argument("--bands", default="", help='only if bands are unlabelled, e.g. "red=3,nir=4"')
p.add_argument("--max-turns", type=int, default=6)
p.add_argument("--no-explain", action="store_true", help="print raw result JSON instead of a plain-language answer")
a = p.parse_args()

files = []
for f in a.files:
    path = Path(f) if Path(f).exists() else DATA / f
    if not path.exists():
        sys.exit(f"File not found: {f} (looked in the current folder and in data/)")
    files.append(str(path))
if not files:
    found = sorted(x for x in DATA.glob("*") if x.suffix.lower() in EXT)
    rasters = [x for x in found if x.suffix.lower() in (".tif", ".tiff")]
    if len(rasters) == 1:
        files = [str(rasters[0])]
    else:
        sys.exit("Say which files to use. Files in data/: " + ", ".join(x.name for x in found))

overrides = {}
if a.bands:
    for part in a.bands.split(","):
        role, _, num = part.partition("=")
        if role.strip() not in ROLES or not num.strip().isdigit():
            sys.exit(f"Bad --bands entry '{part}'. Use role=number with roles {ROLES}")
        overrides[role.strip()] = int(num)

r = solve(a.question, files, overrides=overrides, max_turns=a.max_turns, explain=not a.no_explain)
print("\n" + "=" * 60)
if r["status"] == "clarify":
    print("I need one detail before I can answer:\n" + r["answer"])
else:
    print(r["answer"])
print(f"\nstatus: {r['status']} | turns: {r['turns']} | {r['seconds']}s")
if r["artifacts"]:
    print("files:", r["run_dir"], r["artifacts"])