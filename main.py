import argparse
import sys
from pathlib import Path

import harness  # puts lib/ on sys.path
from geollm_lib.bands import ROLES
# from harness.agent import solve
from harness.pi_harness import solve


DATA = Path("data")
EXT = {".tif", ".tiff", ".geojson", ".gpkg", ".json"}

p = argparse.ArgumentParser(description="Ask a question about geospatial files (looked up in data/)")
p.add_argument("question")
p.add_argument("files", nargs="*", help="file names in data/ or paths. Default: the only raster in data/")
p.add_argument("--bands", default="", help='only for unlabelled bands, e.g. "red=3,nir=4"')
p.add_argument("--max-turns", type=int, default=None, help="max attempts per task (default 3)")
p.add_argument("--no-explain", action="store_true", help="print the raw result JSON instead of an explanation")
a = p.parse_args()

files = []
for f in a.files:
    path = Path(f) if Path(f).exists() else DATA / f
    if not path.exists():
        sys.exit(f"File not found: {f} (looked in the current folder and in data/)")
    files.append(str(path))
if not files:
    rasters = sorted(x for x in DATA.glob("*") if x.suffix.lower() in (".tif", ".tiff"))
    if len(rasters) != 1:
        sys.exit("Say which files to use. Files in data/: " + ", ".join(x.name for x in sorted(DATA.glob("*")) if x.suffix.lower() in EXT))
    files = [str(rasters[0])]

overrides = {}
for part in filter(None, a.bands.split(",")):
    role, _, num = part.partition("=")
    if role.strip() not in ROLES or not num.strip().isdigit():
        sys.exit(f"Bad --bands entry '{part}'. Use role=number with roles {ROLES}")
    overrides[role.strip()] = int(num)

r = solve(a.question, files, overrides=overrides, max_turns=a.max_turns, explain=not a.no_explain)
print("\n" + "=" * 60)
print(("I need one detail before I can answer:\n" if r["status"] == "clarify" else "") + r["answer"])
print(f"\nstatus: {r['status']} | attempts: {r['turns']} | {r['seconds']}s | tasks: {r['tasks']}")
for w in r["warnings"]:
    print("warning:", w)
if r["artifacts"]:
    print("files in", r["run_dir"] + ":", *r["artifacts"], sep="\n  ")