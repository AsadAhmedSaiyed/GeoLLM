"""Run a Python script in a fresh, locked-down Docker container (one container per execution)."""
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

import docker
from requests.exceptions import ConnectionError as ReqConnectionError
from requests.exceptions import ReadTimeout

IMAGE = os.environ.get("GEOLLM_IMAGE", "geollm-runtime")
MAX_LOG = 8000
OUTPUT_LIMIT_MB = int(os.environ.get("GEOLLM_OUTPUT_LIMIT_MB", "8192"))


def _tail(text, n=MAX_LOG):
    return text if len(text) <= n else "...[truncated]...\n" + text[-n:]

def _error_summary(stderr):
    if not stderr:
        return ""
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    if not lines:
        return ""
    return lines[-1]


def _open_perms(path):
    for root, dirs, files in os.walk(path):
        for d in dirs:
            os.chmod(os.path.join(root, d), 0o755)
        for f in files:
            os.chmod(os.path.join(root, f), 0o644)
    os.chmod(path, 0o755)


def _size_mb(path):
    return sum(f.stat().st_size for f in Path(path).rglob("*") if f.is_file()) / 1e6


def _stage_input_file(src: Path, dest: Path) -> None:
    """Link `src` to `dest` via zero-copy hardlink when on the same volume, falling back to copy."""
    try:
        os.link(src, dest)
    except OSError:
        shutil.copy(src, dest)
        try:
            os.chmod(dest, 0o644)
        except OSError:
            pass


def run_code(code, input_files, run_dir, timeout=120, memory="2g", cpus=2.0, env=None, prior=None, task_id="", image=None):
    """Run `code` once. prior={task_id: host_dir} mounts earlier task outputs read-only at /workspace/prior/<task_id>.
    Everything is saved under run_dir: code.py, stdout.txt, stderr.txt, outputs/."""
    client = docker.from_env()
    run_dir_path = Path(run_dir).resolve()
    run_dir_path.mkdir(parents=True, exist_ok=True)
    # Place temp work dir inside a hidden .sandbox_tmp folder on the same filesystem as run_dir
    # so os.link() is guaranteed zero-copy and find_artifacts() ignores it.
    try:
        tmp_base = run_dir_path.parent / ".sandbox_tmp"
        tmp_base.mkdir(parents=True, exist_ok=True)
        work = Path(
            tempfile.mkdtemp(
                prefix=f"geollm_{task_id}_" if task_id else "geollm_",
                dir=str(tmp_base),
            )
        )
    except OSError:
        work = Path(tempfile.mkdtemp(prefix=f"geollm_{task_id}_" if task_id else "geollm_"))
    in_dir, code_dir, out_dir = work / "input", work / "code", work / "output"
    for d in (in_dir, code_dir, out_dir):
        d.mkdir()
    seed_out = run_dir_path / "outputs"
    if seed_out.is_dir():
        for item in seed_out.rglob("*"):
            if item.is_file():
                rel_p = item.relative_to(seed_out)
                target_p = out_dir / rel_p
                target_p.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target_p)
                os.chmod(target_p, 0o666)

    # Zero-copy optimization: if all input_files come from a single directory with no extra files,
    # mount that directory directly as /workspace/input:ro; otherwise use hardlinks in in_dir.
    resolved_inputs = [Path(f).resolve() for f in input_files]
    parent_dirs = {p.parent for p in resolved_inputs}
    direct_mount_in_dir = None
    if len(parent_dirs) == 1:
        sole_dir = next(iter(parent_dirs))
        if sole_dir.is_dir():
            dir_files = {p.resolve() for p in sole_dir.iterdir() if p.is_file()}
            if dir_files == set(resolved_inputs):
                direct_mount_in_dir = sole_dir

    if direct_mount_in_dir is None:
        for src_p in resolved_inputs:
            dest = in_dir / src_p.name
            _stage_input_file(src_p, dest)
        mounted_in_dir = in_dir
    else:
        mounted_in_dir = direct_mount_in_dir

    input_manifest = [
        {
            "host_path": str(src_p),
            "sandbox_path": f"/workspace/input/{src_p.name}",
            "filename": src_p.name,
        }
        for src_p in resolved_inputs
    ]
    (code_dir / "script.py").write_text(code)
    for d in (work, in_dir, code_dir):
        os.chmod(d, 0o755)
    os.chmod(out_dir, 0o777)

    lib_dir = Path(__file__).resolve().parent.parent / "lib"
    volumes = {
        str(mounted_in_dir): {"bind": "/workspace/input", "mode": "ro"},
        str(code_dir): {"bind": "/workspace/code", "mode": "ro"},
        str(out_dir): {"bind": "/workspace/output", "mode": "rw"},
    }
    if lib_dir.exists():
        _open_perms(str(lib_dir))
        volumes[str(lib_dir)] = {"bind": "/opt/geollm", "mode": "ro"}
    for tid, host in (prior or {}).items():
        if Path(host).exists():
            _open_perms(host)
            volumes[str(Path(host).resolve())] = {"bind": f"/workspace/prior/{tid}", "mode": "ro"}

    container, timed_out, oom = None, False, False
    exit_code, stdout, stderr = -1, "", ""
    t0 = time.time()
    startup = duration = 0.0
    default_image = os.environ.get("GEOLLM_IMAGE", IMAGE)
    container_image = image or default_image
    if container_image != default_image:
        try:
            client.images.get(container_image)
        except Exception:
            container_image = default_image
    try:
        cname = f"geollm_{task_id}_{int(time.time())}" if task_id else None
        container = client.containers.create(
            container_image, command=["python", "/workspace/code/script.py"], working_dir="/workspace/output",
            name=cname,
            environment={"MPLCONFIGDIR": "/tmp/mpl", "PYTHONDONTWRITEBYTECODE": "1", **(env or {})},
            network_mode="none", mem_limit=memory, memswap_limit=memory, nano_cpus=int(cpus * 1e9),
            pids_limit=128, read_only=True, tmpfs={"/tmp": "size=512m"},
            cap_drop=["ALL"], security_opt=["no-new-privileges"], volumes=volumes,
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
            container.remove(force=True)

    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "code.py").write_text(code)
    (run_dir / "stdout.txt").write_text(stdout)
    (run_dir / "stderr.txt").write_text(stderr)
    oversize = _size_mb(out_dir) > OUTPUT_LIMIT_MB
    dest_out = run_dir / "outputs"
    if dest_out.exists():
        shutil.rmtree(dest_out)
    artifacts = []
    if oversize:
        dest_out.mkdir()
    else:
        try:
            shutil.move(str(out_dir), str(dest_out))
        except OSError:
            shutil.copytree(out_dir, dest_out)
        artifacts = sorted(p.relative_to(dest_out).as_posix() for p in dest_out.rglob("*") if p.is_file())
    result = None
    rj = dest_out / "result.json"
    if rj.exists():
        try:
            result = json.loads(rj.read_text())
        except json.JSONDecodeError:
            result = None
    shutil.rmtree(work, ignore_errors=True)
    return {
        "exit_code": exit_code,
    "timed_out": timed_out,
    "oom": oom,
    "oversize": oversize,
    "stdout": _tail(stdout),
    "stderr": _tail(stderr),
    "startup_s": round(startup, 2),
    "duration_s": round(duration, 2),
    "result": result,
    "artifacts": artifacts,
    "run_dir": str(run_dir),
    "output_dir": str(dest_out),
    "error": _error_summary(stderr),
    # Sandbox contract exposed to the agent
    "sandbox": {
        "working_directory": "/workspace/output",
        "input_directory": "/workspace/input",
        "output_directory": "/workspace/output",
        "input_files": input_manifest,
    },
    }
