"""Optional adapter to the Pi agent runtime (https://github.com/badlogic/pi-mono) over its RPC mode.
Pi is used ONLY as an LLM backend here: built-in tools are disabled. Geospatial work stays in GeoLLM.
UNVERIFIED: the 'prompt' command shape below was not checked against your installed Pi. Read its docs/rpc.md and `pi --help`."""
import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading

PI_CMD = os.environ.get("PI_COMMAND", "pi")
PI_ARGS = os.environ.get("PI_ARGS", "").split()          # e.g. model selection flags of your Pi version
PROMPT_TYPE = os.environ.get("PI_PROMPT_TYPE", "prompt")   # verify against docs/rpc.md
END_EVENTS = ("agent_end", "agent_settled")


def available():
    return shutil.which(PI_CMD) is not None


def _assistant_text(event):
    """Tolerant extraction of the last assistant message text from an agent_end event."""
    msgs = event.get("messages") or []
    for m in reversed(msgs):
        if isinstance(m, dict) and m.get("role") == "assistant":
            c = m.get("content")
            if isinstance(c, str):
                return c
            if isinstance(c, list):
                return "".join(p.get("text", "") for p in c if isinstance(p, dict))
    return None


def complete(messages, timeout=600):
    """Send the whole conversation as one prompt to a fresh Pi RPC process and return the reply text."""
    if not available():
        raise RuntimeError(f"'{PI_CMD}' not found. Install Pi (npm i -g @earendil-works/pi-coding-agent) or use another LLM_PROVIDER.")
    text = "\n\n".join(f"[{m['role'].upper()}]\n{m['content']}" for m in messages if isinstance(m.get("content"), str))
    proc = subprocess.Popen([PI_CMD, "--mode", "rpc", "--no-session", "--no-builtin-tools", *PI_ARGS],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            cwd=tempfile.mkdtemp(prefix="geollm_pi_"))
    q = queue.Queue()
    threading.Thread(target=lambda: [q.put(l) for l in proc.stdout], daemon=True).start()
    try:
        proc.stdin.write(json.dumps({"type": PROMPT_TYPE, "message": text}) + "\n")
        proc.stdin.flush()
        while True:
            try:
                line = q.get(timeout=timeout)
            except queue.Empty:
                raise RuntimeError("Pi did not finish in time")
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") in END_EVENTS:
                reply = _assistant_text(ev)
                if reply is not None:
                    return reply
                if ev.get("type") == "agent_end":
                    raise RuntimeError("Pi finished but no assistant text was found in: " + line[:500])
    finally:
        proc.kill()