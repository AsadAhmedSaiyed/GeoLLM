"""Run Python scripts in persistent, pre-warmed Docker containers.

Instead of creating and destroying a container on every attempt, each active
workspace (`task_id`) keeps one long-lived container with heavy geospatial
libraries pre-imported. Each execution forks a clean child in milliseconds,
and an idle reaper automatically shuts down unused containers after 10 minutes.
"""
from __future__ import annotations

import atexit
import json
import os
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

import docker
from requests.exceptions import ConnectionError as ReqConnectionError
from requests.exceptions import ReadTimeout

IMAGE = os.environ.get("GEOLLM_IMAGE", "geollm-runtime")
MAX_LOG = 8000
OUTPUT_LIMIT_MB = int(os.environ.get("GEOLLM_OUTPUT_LIMIT_MB", "8192"))
IDLE_TIMEOUT_S = int(os.environ.get("GEOLLM_CONTAINER_IDLE_S", "600"))

# Pre-warmed resident daemon inside the container: imports heavy libraries once,
# then forks a clean Copy-on-Write child per request over /tmp/geollm_worker.sock.
_WORKER_DAEMON = r'''
import json, os, runpy, signal, socket, sys, traceback

SOCK = "/tmp/geollm_worker.sock"
if os.path.exists(SOCK):
    os.unlink(SOCK)

# Pre-import heavy geospatial/scientific stack once at container startup
for _mod in ("numpy", "scipy", "matplotlib", "rasterio"):
    try:
        __import__(_mod)
    except Exception:
        pass

signal.signal(signal.SIGCHLD, signal.SIG_IGN)
srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
srv.bind(SOCK)
srv.listen(8)

while True:
    conn, _ = srv.accept()
    try:
        raw = b""
        while not raw.endswith(b"\n"):
            chunk = conn.recv(4096)
            if not chunk:
                break
            raw += chunk
        req = json.loads(raw.decode("utf-8") or "{}")
        script_path = req.get("script", "/workspace/code/script.py")
        out_log = req.get("stdout", "/tmp/last_stdout.txt")
        err_log = req.get("stderr", "/tmp/last_stderr.txt")
        r_pipe, w_pipe = os.pipe()
        pid = os.fork()
        if pid == 0:
            os.close(r_pipe)
            try:
                so = os.open(out_log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o666)
                se = os.open(err_log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o666)
                os.dup2(so, 1)
                os.dup2(se, 2)
                os.close(so)
                os.close(se)
                os.chdir("/workspace/output")
                sys.argv = [script_path]
                code_obj = compile(open(script_path, "r", encoding="utf-8").read(), script_path, "exec")
                ns = {"__name__": "__main__", "__file__": script_path}
                exec(code_obj, ns)
                rc = 0
            except SystemExit as e:
                rc = int(e.code) if isinstance(e.code, int) else (0 if e.code is None else 1)
            except BaseException:
                traceback.print_exc()
                rc = 1
            finally:
                sys.stdout.flush()
                sys.stderr.flush()
                os.write(w_pipe, str(rc).encode())
                os.close(w_pipe)
            os._exit(rc)
        else:
            os.close(w_pipe)
            rc_bytes = b""
            while True:
                b = os.read(r_pipe, 64)
                if not b:
                    break
                rc_bytes += b
            os.close(r_pipe)
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass
            rc = int((rc_bytes.decode() or "1").strip())
            conn.sendall((json.dumps({"exit_code": rc}) + "\n").encode("utf-8"))
    except Exception as exc:
        try:
            conn.sendall((json.dumps({"exit_code": 1, "error": str(exc)}) + "\n").encode("utf-8"))
        except Exception:
            pass
    finally:
        conn.close()
'''

_EXEC_CLIENT = r'''
import json, os, socket, sys
req = json.dumps({"script": sys.argv[1], "stdout": sys.argv[2], "stderr": sys.argv[3]}) + "\n"
c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
c.connect("/tmp/geollm_worker.sock")
c.sendall(req.encode("utf-8"))
buf = b""
while not buf.endswith(b"\n"):
    ch = c.recv(4096)
    if not ch:
        break
    buf += ch
c.close()
res = json.loads(buf.decode("utf-8") or '{"exit_code":1}')
sys.exit(int(res.get("exit_code", 1)))
'''


def _tail(text: str, n: int = MAX_LOG) -> str:
    return text if len(text) <= n else "...[truncated]...\n" + text[-n:]


def _error_summary(stderr: str) -> str:
    if not stderr:
        return ""
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _open_perms(path: str | Path) -> None:
    for root, dirs, files in os.walk(path):
        for d in dirs:
            os.chmod(os.path.join(root, d), 0o755)
        for f in files:
            os.chmod(os.path.join(root, f), 0o644)
    os.chmod(path, 0o755)


def _reset_out_dir(out_dir: Path, seed_dir: Path) -> None:
    """Empty `out_dir` and copy in the contents of `seed_dir` (if any)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for child in out_dir.iterdir():
        try:
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink()
        except OSError:
            pass
    if seed_dir.is_dir():
        for item in seed_dir.rglob("*"):
            if item.is_file():
                target = out_dir / item.relative_to(seed_dir)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
                try:
                    os.chmod(target, 0o666)
                except OSError:
                    pass
    try:
        os.chmod(out_dir, 0o777)
    except OSError:
        pass


def _size_mb(path: Path) -> float:
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


@dataclass
class _WarmContainer:
    task_id: str
    container: object
    work_dir: Path
    in_dir: Path
    code_dir: Path
    out_dir: Path
    mounted_in_dir: Path
    image: str
    memory: str
    cpus: float
    input_key: tuple
    prior_key: tuple
    last_used: float = field(default_factory=time.time)
    lock: threading.Lock = field(default_factory=threading.Lock)


_POOL_LOCK = threading.Lock()
_WARM_POOL: Dict[str, _WarmContainer] = {}
_REAPER_STARTED = False


def _destroy_warm(entry: _WarmContainer) -> None:
    try:
        entry.container.remove(force=True)
    except Exception:
        pass
    shutil.rmtree(entry.work_dir, ignore_errors=True)


def release_container(task_id: str) -> bool:
    """Immediately stop and remove the warm container for `task_id`."""
    with _POOL_LOCK:
        entry = _WARM_POOL.pop(task_id, None)
    if entry is None:
        return False
    _destroy_warm(entry)
    return True


def release_all_containers() -> None:
    with _POOL_LOCK:
        entries = list(_WARM_POOL.values())
        _WARM_POOL.clear()
    for e in entries:
        _destroy_warm(e)


def _reap_idle_loop() -> None:
    while True:
        time.sleep(30)
        now = time.time()
        expired: list[_WarmContainer] = []
        with _POOL_LOCK:
            for tid, entry in list(_WARM_POOL.items()):
                # Only reap if not currently executing (lock not held) and idle > IDLE_TIMEOUT_S
                if (now - entry.last_used) >= IDLE_TIMEOUT_S and not entry.lock.locked():
                    expired.append(_WARM_POOL.pop(tid))
        for entry in expired:
            _destroy_warm(entry)


def _ensure_reaper() -> None:
    global _REAPER_STARTED
    if not _REAPER_STARTED:
        _REAPER_STARTED = True
        t = threading.Thread(target=_reap_idle_loop, daemon=True, name="geollm-container-reaper")
        t.start()
        atexit.register(release_all_containers)


def _prepare_mounts(input_files, run_dir_path: Path, task_id: str):
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
            _stage_input_file(src_p, in_dir / src_p.name)
        mounted_in_dir = in_dir
    else:
        mounted_in_dir = direct_mount_in_dir

    for d in (work, in_dir, code_dir):
        os.chmod(d, 0o755)
    os.chmod(out_dir, 0o777)

    input_manifest = [
        {
            "host_path": str(src_p),
            "sandbox_path": f"/workspace/input/{src_p.name}",
            "filename": src_p.name,
        }
        for src_p in resolved_inputs
    ]
    return work, in_dir, code_dir, out_dir, mounted_in_dir, input_manifest


def _build_volumes(mounted_in_dir: Path, code_dir: Path, out_dir: Path, prior) -> dict:
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
    return volumes


def _get_or_create_warm(
    client,
    task_id: str,
    input_files,
    run_dir_path: Path,
    container_image: str,
    memory: str,
    cpus: float,
    env: Optional[dict],
    prior,
) -> tuple[_WarmContainer, list, bool]:
    """Return (warm_entry, input_manifest, was_cold_start)."""
    _ensure_reaper()
    resolved = [Path(f).resolve() for f in input_files]
    input_key = tuple(sorted(str(p) for p in resolved))
    prior_key = tuple(sorted((str(k), str(v)) for k, v in (prior or {}).items()))

    with _POOL_LOCK:
        existing = _WARM_POOL.get(task_id) if task_id else None
        if existing is not None:
            same_cfg = (
                existing.image == container_image
                and existing.memory == memory
                and existing.cpus == cpus
                and existing.input_key == input_key
                and existing.prior_key == prior_key
            )
            alive = False
            if same_cfg:
                try:
                    existing.container.reload()
                    alive = existing.container.status == "running"
                except Exception:
                    alive = False
            if alive:
                existing.last_used = time.time()
                manifest = [
                    {"host_path": str(p), "sandbox_path": f"/workspace/input/{p.name}", "filename": p.name}
                    for p in resolved
                ]
                return existing, manifest, False
            # Config changed (e.g. OOM RAM upgrade or TS image) or container died -> replace cleanly
            _WARM_POOL.pop(task_id, None)
            _destroy_warm(existing)

    work, in_dir, code_dir, out_dir, mounted_in_dir, manifest = _prepare_mounts(
        input_files, run_dir_path, task_id
    )
    (code_dir / "_daemon.py").write_text(_WORKER_DAEMON, encoding="utf-8")
    (code_dir / "_client.py").write_text(_EXEC_CLIENT, encoding="utf-8")
    volumes = _build_volumes(mounted_in_dir, code_dir, out_dir, prior)

    cpu_count_str = str(max(1, int(round(cpus))))
    container_env = {
        "MPLCONFIGDIR": "/tmp/mpl",
        "PYTHONDONTWRITEBYTECODE": "1",
        "GDAL_NUM_THREADS": "ALL_CPUS",
        "OMP_NUM_THREADS": cpu_count_str,
        "OPENBLAS_NUM_THREADS": cpu_count_str,
        "MKL_NUM_THREADS": cpu_count_str,
        "GDAL_CACHEMAX": "512",
        **(env or {}),
    }

    cname = f"geollm_{task_id}_{int(time.time())}" if task_id else None
    container = client.containers.create(
        container_image,
        command=["python", "-u", "/workspace/code/_daemon.py"],
        working_dir="/workspace/output",
        name=cname,
        environment=container_env,
        network_mode="none",
        mem_limit=memory,
        memswap_limit=memory,
        shm_size="1g",
        nano_cpus=int(cpus * 1e9),
        pids_limit=256,
        read_only=True,
        tmpfs={"/tmp": "size=512m"},
        cap_drop=["ALL"],
        security_opt=["no-new-privileges"],
        volumes=volumes,
    )
    container.start()

    # Wait briefly for the pre-warmed socket to appear (up to 4s)
    for _ in range(40):
        res = container.exec_run(["test", "-S", "/tmp/geollm_worker.sock"])
        if res.exit_code == 0:
            break
        time.sleep(0.1)

    entry = _WarmContainer(
        task_id=task_id,
        container=container,
        work_dir=work,
        in_dir=in_dir,
        code_dir=code_dir,
        out_dir=out_dir,
        mounted_in_dir=mounted_in_dir,
        image=container_image,
        memory=memory,
        cpus=cpus,
        input_key=input_key,
        prior_key=prior_key,
    )
    if task_id:
        with _POOL_LOCK:
            _WARM_POOL[task_id] = entry
    return entry, manifest, True


def run_code(code, input_files, run_dir, timeout=120, memory="2g", cpus=2.0, env=None, prior=None, task_id="", image=None):
    """Run `code` inside a persistent warm container for `task_id` (or ephemeral if task_id is empty)."""
    client = docker.from_env()
    run_dir_path = Path(run_dir).resolve()
    run_dir_path.mkdir(parents=True, exist_ok=True)

    default_image = os.environ.get("GEOLLM_IMAGE", IMAGE)
    container_image = image or default_image
    if container_image != default_image:
        try:
            client.images.get(container_image)
        except Exception:
            container_image = default_image

    t0 = time.time()
    entry, input_manifest, cold = _get_or_create_warm(
        client, task_id, input_files, run_dir_path, container_image, memory, cpus, env, prior
    )
    startup = time.time() - t0

    timed_out, oom = False, False
    exit_code, stdout, stderr = -1, "", ""
    t1 = time.time()

    with entry.lock:
        entry.last_used = time.time()
        # Warm containers are reused across attempts. Wipe /workspace/output and re-seed it only
        # from the host-side outputs of this run, so files from failed or quarantined attempts
        # never leak into later attempts.
        _reset_out_dir(entry.out_dir, run_dir_path / "outputs")
        (entry.code_dir / "script.py").write_text(code, encoding="utf-8")
        out_log = "/tmp/run_stdout.txt"
        err_log = "/tmp/run_stderr.txt"

        try:
            # Enforce per-attempt timeout cleanly in a helper thread
            exec_res_box: dict = {}

            def _do_exec():
                try:
                    # Prefer the pre-warmed fork daemon; fall back to direct python if socket unavailable
                    r = entry.container.exec_run(
                        ["python", "/workspace/code/_client.py", "/workspace/code/script.py", out_log, err_log],
                        workdir="/workspace/output",
                    )
                    if r.exit_code != 0 and b"ConnectionRefusedError" in (r.output or b""):
                        r2 = entry.container.exec_run(
                            ["python", "/workspace/code/script.py"],
                            workdir="/workspace/output",
                            demux=True,
                        )
                        exec_res_box["exit_code"] = r2.exit_code
                        so_b, se_b = r2.output if isinstance(r2.output, tuple) else (r2.output, b"")
                        exec_res_box["stdout"] = (so_b or b"").decode(errors="replace")
                        exec_res_box["stderr"] = (se_b or b"").decode(errors="replace")
                        return
                    exec_res_box["exit_code"] = r.exit_code
                except (ReadTimeout, ReqConnectionError, Exception) as exc:
                    exec_res_box["exc"] = exc

            th = threading.Thread(target=_do_exec, daemon=True)
            th.start()
            th.join(timeout=timeout)
            if th.is_alive():
                timed_out = True
                release_container(task_id) if task_id else _destroy_warm(entry)
            elif "exc" in exec_res_box:
                stderr = str(exec_res_box["exc"])
            else:
                exit_code = int(exec_res_box.get("exit_code", -1))
                if "stdout" in exec_res_box:
                    stdout = exec_res_box["stdout"]
                    stderr = exec_res_box["stderr"]
                else:
                    so_r = entry.container.exec_run(["cat", out_log])
                    se_r = entry.container.exec_run(["cat", err_log])
                    stdout = (so_r.output or b"").decode(errors="replace") if so_r.exit_code == 0 else ""
                    stderr = (se_r.output or b"").decode(errors="replace") if se_r.exit_code == 0 else ""
        finally:
            if not timed_out:
                try:
                    entry.container.reload()
                    oom = bool(entry.container.attrs["State"].get("OOMKilled", False)) or exit_code == 137 or "MemoryError" in stderr
                    if oom or entry.container.status != "running":
                        if task_id:
                            release_container(task_id)
                        else:
                            _destroy_warm(entry)
                except Exception:
                    pass

        duration = time.time() - t1

        # Copy outputs back to run_dir/outputs (preserving warm container's out_dir for next step!)
        dest_out = run_dir_path / "outputs"
        artifacts = []
        oversize = False
        if entry.out_dir.is_dir():
            oversize = _size_mb(entry.out_dir) > OUTPUT_LIMIT_MB
            if dest_out.exists():
                shutil.rmtree(dest_out)
            if oversize:
                dest_out.mkdir()
            else:
                shutil.copytree(entry.out_dir, dest_out)
                artifacts = sorted(p.relative_to(dest_out).as_posix() for p in dest_out.rglob("*") if p.is_file())
        else:
            # Container work dir was destroyed (e.g. timeout or crash): keep whatever outputs
            # the host already has and report the failure cleanly instead of crashing.
            dest_out.mkdir(parents=True, exist_ok=True)

    (run_dir_path / "code.py").write_text(code, encoding="utf-8")
    (run_dir_path / "stdout.txt").write_text(stdout, encoding="utf-8")
    (run_dir_path / "stderr.txt").write_text(stderr, encoding="utf-8")

    result = None
    rj = dest_out / "result.json"
    if rj.exists():
        try:
            result = json.loads(rj.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            result = None

    if not task_id:
        _destroy_warm(entry)

    return {
        "exit_code": exit_code,
        "timed_out": timed_out,
        "oom": oom,
        "oversize": oversize,
        "stdout": _tail(stdout),
        "stderr": _tail(stderr),
        "startup_s": round(startup, 2),
        "duration_s": round(duration, 2),
        "warm_hit": not cold,
        "result": result,
        "artifacts": artifacts,
        "run_dir": str(run_dir_path),
        "output_dir": str(dest_out),
        "error": _error_summary(stderr),
        "sandbox": {
            "working_directory": "/workspace/output",
            "input_directory": "/workspace/input",
            "output_directory": "/workspace/output",
            "input_files": input_manifest,
        },
    }
