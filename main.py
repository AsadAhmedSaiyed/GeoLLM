import argparse
import sys
from pathlib import Path

import harness  # puts lib/ on sys.path
from geollm_lib.bands import ROLES
from harness import chat
from harness.orchestrator import TaskManager


DATA = Path("data")
EXT = {".tif", ".tiff", ".geojson", ".gpkg", ".json"}

p = argparse.ArgumentParser(description="Ask a question about geospatial files (looked up in data/)")
p.add_argument("question")
p.add_argument("files", nargs="*", help="file names in data/ or paths. Default: the only raster in data/")
p.add_argument("--bands", default="", help='only for unlabelled bands, e.g. "red=3,nir=4"')
p.add_argument("--max-turns", type=int, default=None, help="max tool calls per Pi run")
p.add_argument("--no-explain", action="store_true", help="keep the final answer short")
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
        sys.exit("Say which files to use. Files in data/: "
                 + ", ".join(x.name for x in sorted(DATA.glob("*")) if x.suffix.lower() in EXT))
    files = [str(rasters[0])]

overrides = {}
for part in filter(None, a.bands.split(",")):
    role, _, num = part.partition("=")
    if role.strip() not in ROLES or not num.strip().isdigit():
        sys.exit(f"Bad --bands entry '{part}'. Use role=number with roles {ROLES}")
    overrides[role.strip()] = int(num)


def on_finish(task_id):
    print("\n" + tm.outcome_line(task_id) + "\n> ", end="", flush=True)


tm = TaskManager(on_finish=on_finish, auto_approve=True)

task_id = tm.submit_task(a.question, files, overrides=overrides, max_turns=a.max_turns,
                         explain=not a.no_explain)
print(f"Analysis running in background as {task_id}. Progress prints below. "
      f"Chat with me about anything. Type 'quit' to exit.")

history = []
while True:
    try:
        q = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        break
    if q.lower() in ("quit", "exit"):
        break
    if not q:
        continue
    history.append({"role": "user", "content": q})
    try:
        reply = chat.ask(history[-6:], tm.multi_snapshot())
    except Exception as e:
        reply = f"(chat model error: {e})"
    if reply.strip().startswith("RUN_JOB:"):
        task = reply.strip()[len("RUN_JOB:"):].strip()
        print(f"\nProposed new job:\n{task}")
        if input("Run it? [y/N] ").strip().lower() != "y":
            reply = "Cancelled. No new job was started."
        else:
            new_tid = tm.submit_task(task, files, overrides=overrides, max_turns=a.max_turns,
                                     explain=not a.no_explain)
            if new_tid:
                reply = f"Started new background job as {new_tid}."
            else:
                reply = "All 3 task slots are busy. Wait for one to finish."
    history.append({"role": "assistant", "content": reply})
    print(reply)

# QUIT FIX: kill all running tasks and force exit
tm.cancel_all()
sys.exit(0)
