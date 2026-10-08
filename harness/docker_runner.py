"""Bridge: Pi extension -> path-checked, validated run through harness.executor.
Prints exactly ONE JSON line to stdout (everything else goes to stderr)."""
import contextlib
import inspect
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.executor import run_code          # noqa: E402
from harness.pi_config import load_config      # noqa: E402

RASTER_EXT = {".tif", ".tiff"}


def _next_attempt(run_dir: Path):
    n = 1
    while True:
        d = run_dir / f"attempt_{n:02d}"
        try:
            d.mkdir(parents=True)
            return n, d
        except FileExistsError:
            n += 1


def _safe_inputs(requested, allowed_originals):
    """Only files GeoLLM itself supplied may be mounted. Returns (files, error)."""
    allowed = {str(Path(o).resolve()): o for o in allowed_originals}
    if not requested:
        return list(allowed.values()), None
    out = []
    for r in requested:
        hit = allowed.get(str(Path(r).resolve()))
        if hit is None:
            return None, f"Input file not permitted: {r!r}. Allowed: {list(allowed.values())}"
        out.append(hit)
    return out, None


def _call_executor(code, files, attempt_dir, cfg):
    params = inspect.signature(run_code).parameters
    wanted = {"timeout": cfg.sandbox_timeout_s, "memory": cfg.sandbox_memory, "cpus": cfg.sandbox_cpus}
    return run_code(code, files, attempt_dir, **{k: v for k, v in wanted.items() if k in params})


def _find_artifact(a, attempt_dir: Path):
    p = Path(a)
    cands = [p] if p.is_absolute() else [attempt_dir / p, attempt_dir / "outputs" / p, attempt_dir / "output" / p]
    for c in cands:
        if c.exists():
            return c
    hits = list(attempt_dir.rglob(p.name))
    return hits[0] if hits else None

def _validate(res, attempt_dir, cfg):
    errors, warnings, artifacts = [], [], []
    if res.get("exit_code") != 0:
        return errors, warnings, artifacts

    result = res.get("result")
    q = os.environ.get("GEOLLM_QUESTION", "").lower()

    # 1. Allow inspection calls to succeed without punishing the agent
    if result is None:
        # Script inspected data; not a fatal error
        return errors, warnings, artifacts

    # 2. Check summary in result.json
    summary = result.get("summary") if isinstance(result, dict) else None
    if not summary or (isinstance(summary, str) and len(summary.strip()) < 20):
        errors.append("result.json is missing a substantive 'summary' section explaining the findings and evidence.")

    # 3. Collect declared artifacts
    for a in res.get("artifacts") or []:
        found = _find_artifact(a, attempt_dir)
        if found is None:
            errors.append(f"Declared output file not found: {a}")
            continue
        artifacts.append(str(found))

    # 4. Dynamically verify deliverables based on user request (NO HARDCODING)
    needs_spatial = any(w in q for w in ("geotiff", ".tif", "tif", "raster", "spatial result", "spatial output", "georeferenced form", "vector", "geojson"))
    has_spatial = any(Path(a).suffix.lower() in RASTER_EXT or Path(a).suffix.lower() in (".geojson", ".gpkg") for a in artifacts)
    if needs_spatial and not has_spatial:
        errors.append("The task requires georeferenced spatial outputs (GeoTIFF .tif), but none were saved to /workspace/output. Use write_raster() or rasterio to save them.")

    needs_map = any(w in q for w in ("map", "image", "visual", "figure", "plot", "png"))
    has_map = any(Path(a).suffix.lower() == ".png" for a in artifacts)
    if needs_map and not has_map:
        errors.append("The task requires map/visual outputs, but no .png figures were saved to /workspace/output. Use matplotlib or geollm_lib.viz to save map images.")

    return errors, warnings, artifacts


def _message(ok, attempt, res, errors, artifacts, cfg):
    cap = cfg.max_message_chars
    tail = lambda s: (s or "")[-cap:]

    sandbox = res.get("sandbox") or {}
    input_files = sandbox.get("input_files") or []

    sandbox_lines = [
        "",
        "SANDBOX PATH CONTRACT:",
        f"Working directory: {sandbox.get('working_directory', '/workspace/output')}",
        f"Input directory: {sandbox.get('input_directory', '/workspace/input')}",
        f"Output directory: {sandbox.get('output_directory', '/workspace/output')}",
    ]

    if input_files:
        sandbox_lines.append("Mounted input files:")
        for item in input_files:
            sandbox_lines.append(
                f"- {item.get('filename', 'unknown')}: "
                f"{item.get('sandbox_path', 'unknown')}"
            )

        # If the subagent ran an inspection step:
    if res.get("exit_code") == 0 and res.get("result") is None:
        return (
            f"Inspection completed successfully (attempt {attempt}/{cfg.max_tool_calls}).\n"
            f"Discovered data / metadata:\n{tail(res.get('stdout'))}\n"
            + "\n".join(sandbox_lines)
            + "\n\nNEXT ACTION: Inspection complete. Now write your full analysis script that computes the results, saves all required GeoTIFF (.tif) rasters, saves all map figures (.png), and saves result.json with summary."
        )

    # When all outputs are verified:
    if ok:
        return (
            f"Execution SUCCEEDED (attempt {attempt}/{cfg.max_tool_calls}).\n"
            f"Artifacts: {', '.join(Path(a).name for a in artifacts) or '(none)'}\n"
            f"Result:\n{json.dumps(res.get('result'), default=str, indent=2)[:cap]}\n"
            f"Stdout:\n{tail(res.get('stdout'))}\n"
            + "\n".join(sandbox_lines)
            + "\n\nCRITICAL STOP DIRECTIVE: All required spatial outputs, map images, and result.json with summary are verified and COMPLETE. Make ZERO further tool calls. Output your final text summary report now and STOP."
        )

    
    parts = [
        f"Execution FAILED "
        f"(attempt {attempt}/{cfg.max_tool_calls}, "
        f"exit code {res.get('exit_code')})."
    ]

    if errors:
        parts.append("Problems:\n- " + "\n- ".join(errors))

    if res.get("error"):
        parts.append(f"Final error:\n{res['error']}")

    if res.get("stderr"):
        parts.append("Stderr:\n" + tail(res["stderr"]))

    if res.get("stdout"):
        parts.append("Stdout:\n" + tail(res["stdout"]))

    parts.extend(sandbox_lines)

    parts.append("Fix the cause and call run_geospatial_code again.")

    return "\n".join(parts)

def main():
    cfg = load_config()
    run_dir = None
    out = {"ok": False, "attempt": 0, "message": "runner failed before starting", "artifacts": []}
    try:
        run_dir = Path(os.environ["GEOLLM_RUN_DIR"])
        allowed = json.loads(os.environ["GEOLLM_ALLOWED_FILES"])
        payload = json.loads(sys.stdin.read())
        attempt, attempt_dir = _next_attempt(run_dir)
        out["attempt"] = attempt

        files, err = _safe_inputs(payload.get("input_files") or [], allowed)
        if err:
            out["message"] = err
        else:
            (attempt_dir / "script.py").write_text(payload["code"], encoding="utf-8")
            with contextlib.redirect_stdout(sys.stderr):      # keep our stdout clean
                res = _call_executor(payload["code"], files, attempt_dir, cfg)
            errors, warnings, artifacts = _validate(res, attempt_dir, cfg)
            ok = res.get("exit_code") == 0 and not errors
            out = {
    "ok": ok,
    "attempt": attempt,
    "exit_code": res.get("exit_code"),
    "errors": errors,
    "warnings": warnings,
    "artifacts": artifacts,
    "result": res.get("result"),
    "error": res.get("error"),
    "sandbox": res.get("sandbox"),
    "message": _message(
        ok,
        attempt,
        res,
        errors,
        artifacts,
        cfg,
    ),
}
    except Exception as e:
        out["message"] = f"Runner exception: {type(e).__name__}: {e}"
    if run_dir is not None:
        try:
            (run_dir / "last_status.json").write_text(json.dumps(out, default=str, indent=2), encoding="utf-8")
        except Exception:
            pass
    sys.stdout.write(json.dumps(out, default=str) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()