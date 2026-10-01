"""Run a Python script in a fresh, locked-down Docker container."""
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

import docker
from requests.exceptions import ConnectionError as ReqConnectionError
from requests.exceptions import ReadTimeout

IMAGE = "geollm-runtime"
MAX_LOG = 8000


def _tail(text, n=MAX_LOG):
    return text if len(text) <= n else "...[truncated]...\n" + text[-n:]


def run_code(code, input_files, run_dir, timeout=120, memory="2g", cpus=2.0):
    client = docker.from_env()
    work = Path(tempfile.mkdtemp(prefix="geollm_"))
    in_dir, code_dir, out_dir = work / "input", work / "code", work / "output"
    for d in (in_dir, code_dir, out_dir):
        d.mkdir()

    for f in input_files:
        dest = in_dir / Path(f).name
        shutil.copy(f, dest)
        os.chmod(dest, 0o644)
    (code_dir / "script.py").write_text(code)
    for d in (work, in_dir, code_dir):
        os.chmod(d, 0o755)
    os.chmod(out_dir, 0o777)  # container user must be able to write here (Linux)

    container = None
    timed_out = oom = False
    exit_code, stdout, stderr = -1, "", ""
    t0 = time.time()
    startup = duration = 0.0
    try:
        container = client.containers.create(
            IMAGE,
            command=["python", "/workspace/code/script.py"],
            working_dir="/workspace/output",
            environment={"MPLCONFIGDIR": "/tmp/mpl", "PYTHONDONTWRITEBYTECODE": "1"},
            # --- limits and protection ---
            network_mode="none",                 # no network at all
            mem_limit=memory, memswap_limit=memory,  # RAM cap, no swap
            nano_cpus=int(cpus * 1e9),           # CPU cap
            pids_limit=128,                      # stops fork bombs
            read_only=True,                      # container filesystem is read-only
            tmpfs={"/tmp": "size=256m"},         # only /tmp is writable scratch (besides output/)
            cap_drop=["ALL"],                    # drop Linux privileges
            security_opt=["no-new-privileges"],
            volumes={
                str(in_dir): {"bind": "/workspace/input", "mode": "ro"},
                str(code_dir): {"bind": "/workspace/code", "mode": "ro"},
                str(out_dir): {"bind": "/workspace/output", "mode": "rw"},
            },
        )
        container.start()
        startup = time.time() - t0
        t1 = time.time()
        try:
            exit_code = container.wait(timeout=timeout)["StatusCode"]
        except (ReadTimeout, ReqConnectionError):
            timed_out = True
            container.kill()
        duration = time.time() - t1
        container.reload()
        oom = bool(container.attrs["State"].get("OOMKilled", False))
        stdout = container.logs(stdout=True, stderr=False).decode(errors="replace")
        stderr = container.logs(stdout=False, stderr=True).decode(errors="replace")
    finally:
        if container is not None:
            container.remove(force=True)  # destroy the container

    # Save outputs to a permanent place, then delete the temp workspace
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    artifacts = []
    for p in out_dir.rglob("*"):
        if p.is_file():
            rel = p.relative_to(out_dir)
            (run_dir / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(p, run_dir / rel)
            artifacts.append(str(rel))
    result = None
    rj = out_dir / "result.json"
    if rj.exists():
        try:
            result = json.loads(rj.read_text())
        except json.JSONDecodeError:
            result = None
    shutil.rmtree(work, ignore_errors=True)

    return {
        "success": exit_code == 0 and not timed_out and not oom and result is not None,
        "exit_code": exit_code, "timed_out": timed_out, "oom": oom,
        "stdout": _tail(stdout), "stderr": _tail(stderr),
        "startup_s": round(startup, 2), "duration_s": round(duration, 2),
        "result": result, "artifacts": artifacts, "run_dir": str(run_dir),
    }