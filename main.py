import argparse
from harness.agent import solve

p = argparse.ArgumentParser()
p.add_argument("question")
p.add_argument("files", nargs="+")
p.add_argument("--bands", default="", help='e.g. "red=3,nir=4,swir1=5,swir2=6,blue=1"')
a = p.parse_args()

q = a.question + (f"\nBand mapping given by the user (1-based): {a.bands}" if a.bands else "")
out = solve(q, a.files)
if not out["ok"]:
    print(out["answer"])
print("\nAttempts:", out["attempts"], "| Files:", out["run_dir"], out["artifacts"])