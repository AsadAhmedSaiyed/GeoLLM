import json
import re
import time
from pathlib import Path

from . import executor, llm, prompts, validator

INSPECT_CODE = '''
import os
from geollm_lib.metadata import inspect_geotiff
from geollm_lib.result import save_result
out = {}
for n in sorted(os.listdir("/workspace/input")):
    try:
        out[n] = inspect_geotiff("/workspace/input/" + n)
    except Exception as e:
        out[n] = {"error": str(e)}
save_result(out)
'''

CHANGE_WORDS = ("loss", "change", "deforest", "compare", "difference", "before", "after")

INDEX_NEEDS = {
    "ndvi": ["red", "nir"],
    "ndmi": ["nir", "swir1"],
    "nbr": ["nir", "swir2"],
    "evi": ["nir", "red", "blue"],
}


def missing_bands(question, meta):
    """Return problems like 'NDMI needs a swir1 band' when the file/user can't supply it."""
    q = question.lower()
    given = set(re.findall(r"(\w+)=\d+", q))          # roles the user mapped
    labels = set()
    for info in meta.values():
        for b in info.get("bands", []):
            if b.get("description"):
                labels.add(b["description"].lower())
    problems = []
    for idx, roles in INDEX_NEEDS.items():
        if re.search(rf"\b{idx}\b", q):
            for r in roles:
                if r not in given and r not in labels:
                    problems.append(f"{idx.upper()} needs a '{r}' band")
    return problems

def classify(res):
    """Name the kind of failure, or None if the run worked."""
    if res["timed_out"]:
        return "timeout"
    if res["oom"]:
        return "out_of_memory"
    if res["exit_code"] != 0:
        lines = res["stderr"].strip().splitlines()
        last = lines[-1] if lines else "unknown"
        return "runtime_error:" + last.split(":")[0]
    if res["result"] is None:
        return "no_result"
    return None


def _log(entry):
    Path("runs").mkdir(exist_ok=True)
    with open("runs/log.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")


def solve(question, files, max_attempts=3):
    if len(files) < 2 and any(w in question.lower() for w in CHANGE_WORDS):
        return {"ok": False,
                "answer": "Vegetation loss/change needs two images of the same area from different dates "
                          "(before and after). You provided one. Please add a second GeoTIFF.",
                "attempts": 0, "result": None, "artifacts": [], "run_dir": ""}
        
    run_id = time.strftime("%Y%m%d_%H%M%S")
    base = Path("runs") / run_id

    print("[1/4] Reading file metadata in a container...", flush=True)
    meta = executor.run_code(INSPECT_CODE, files, base / "inspect")
    print(f"      done in {meta['duration_s']}s (container startup {meta['startup_s']}s)", flush=True)
    if not meta["success"]:
        return {"ok": False, "answer": "Could not read the input file:\n" + meta["stderr"],
                "attempts": 0, "result": None, "artifacts": [], "run_dir": str(base)}

    problems = missing_bands(question, meta["result"])
    if problems:
        labels = sorted({b.get("description") for i in meta["result"].values() for b in i.get("bands", []) if b.get("description")})
        return {"ok": False,
                "answer": "Cannot compute this with the given file: " + "; ".join(problems)
                          + f". The file's bands are: {', '.join(labels)}.",
                "attempts": 0, "result": None, "artifacts": [], "run_dir": str(base)}

    messages = [
        {"role": "system", "content": prompts.SYSTEM},
        {"role": "user", "content": f"Dataset metadata:\n{json.dumps(meta['result'], indent=1)}\n\nQuestion: {question}"},
    ]

    final_res, attempts_used = None, 0
    for n in range(1, max_attempts + 1):
        attempts_used = n
        print(f"\n[2/4] Attempt {n}/{max_attempts}: LLM is writing code (slow on CPU, keep waiting)...", flush=True)
        reply = llm.chat(messages)
        code = llm.extract_code(reply)
        res, ftype, feedback = None, None, ""

        if code is None:
            ftype, feedback = "no_code", "You must reply with one ```python block."
        else:
            problems = validator.validate(code)
            if problems:
                ftype, feedback = "validation", "Validation failed:\n- " + "\n- ".join(problems)
            else:
                print("[3/4] Running the code in a fresh Docker container...", flush=True)
                res = executor.run_code(code, files, base / f"attempt_{n}")
                print(f"      exit code {res['exit_code']}, ran {res['duration_s']}s, files: {res['artifacts']}", flush=True)
                ftype = classify(res)
                if ftype:
                    feedback = f"The script failed ({ftype}).\nstderr:\n{res['stderr'][-1500:]}"

        if ftype:
            print(f"      FAILED: {ftype}\n      {feedback[:400]}", flush=True)

        _log({"run_id": run_id, "question": question, "model": llm.MODEL, "attempt": n,
              "failure_type": ftype, "startup_s": res["startup_s"] if res else None,
              "duration_s": res["duration_s"] if res else None})

        if ftype is None:
            final_res = res
            break
        messages += [
            {"role": "assistant", "content": reply},
            {"role": "user", "content": feedback + "\nFix the script. Reply with one ```python block."},
        ]

    if final_res is None:
        result = final_res["result"]
        if isinstance(result, dict) and "error" in result:
            _log({"run_id": run_id, "question": question, "model": llm.MODEL, "attempt": attempts_used,
              "failure_type": "refused_by_script", "startup_s": None, "duration_s": None})
            return {"ok": False, "answer": "Cannot complete this request: " + str(result["error"]),
                "attempts": attempts_used, "result": result, "artifacts": [], "run_dir": final_res["run_dir"]}
        return {"ok": False, "answer": f"Failed after {attempts_used} attempts. Last problem: {feedback}",
                "attempts": attempts_used, "result": None, "artifacts": [], "run_dir": str(base)}

    print("\n[4/4] LLM is writing the final explanation...", flush=True)
    answer = llm.chat([
        {"role": "system", "content": prompts.FINAL},
        {"role": "user", "content": f"Question: {question}\n\nResult JSON:\n{json.dumps(final_res['result'])[:6000]}\n\nOutput files: {final_res['artifacts']}"},
    ])
    return {"ok": True, "answer": answer, "attempts": attempts_used, "result": final_res["result"],
            "artifacts": final_res["artifacts"], "run_dir": final_res["run_dir"]}