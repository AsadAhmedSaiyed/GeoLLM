"""Minimal Pi RPC client with progress reporting and an honest finish."""

import json
import queue
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path


class PiRPCError(RuntimeError):
    pass


# Matches the sandbox tool's own result text, e.g. "Execution FAILED (attempt 1/14".
_EXEC = re.compile(r"Execution (SUCCEEDED|FAILED) \(attempt (\d+)/(\d+)")


def _short(x, n=120):
    s = x if isinstance(x, str) else json.dumps(x, default=str)
    s = s.replace("\n", " ")
    return s if len(s) <= n else s[:n] + "..."


class PiRPC:
    DIALOGS = {"select", "confirm", "input", "editor"}
    HEARTBEAT_S = 20        # progress line interval while running
    POST_END_IDLE_S = 90    # how long to wait for agent_settled after agent_end

    def __init__(self, args, cwd, env, stderr_path):
        self._stderr = open(stderr_path, "w", encoding="utf-8")
        # every raw Pi event is saved next to pi_stderr.log
        self._events = open(Path(stderr_path).with_name("events.jsonl"),
                            "a", encoding="utf-8")

        self.proc = subprocess.Popen(
            args,
            cwd=str(cwd),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        self._q = queue.Queue()
        self._lock = threading.Lock()
        self.last_stats = self._new_stats()

        threading.Thread(target=self._pump, daemon=True).start()

    # ---------- stats / progress ----------

    @staticmethod
    def _new_stats():
        now = time.time()
        return {
            "t0": now, "last_event_at": now, "last_event": "starting",
            "tool_calls": 0, "turns": 0, "aborted": False,
            "sandbox_attempts": [], "errors": [], "streamed_chars": 0,
            "agent_ended": False, "last_assistant_stop": None,
            "last_assistant_error": None, "finished": False,
            "no_tool_calls": False,
        }

    def snapshot(self):
        """Real, current state for the status chat to read."""
        s = dict(self.last_stats)
        now = time.time()
        s["elapsed_s"] = round(now - s["t0"])
        s["seconds_since_last_event"] = round(now - s["last_event_at"])
        s["process_alive"] = self.proc.poll() is None
        return s

    def _say(self, msg, stats):
        print(f"[PiRPC {time.time() - stats['t0']:4.0f}s] {msg}", flush=True)

    def _note(self, ev, stats):
        t = ev.get("type", "?")
        stats["last_event"], stats["last_event_at"] = t, time.time()

        if t == "agent_start":
            stats["agent_ended"] = False
        elif t == "agent_end":
            stats["agent_ended"] = True
            self._say("agent run ended, waiting for Pi to settle", stats)
        elif t == "turn_start":
            self._say(f"turn {stats['turns'] + 1}: model working", stats)
        elif t == "message_update":
            u = ev.get("assistantMessageEvent") or {}
            if str(u.get("type", "")).endswith("_delta"):
                stats["streamed_chars"] += len(u.get("delta") or "")
        elif t == "tool_execution_start":
            stats["tool_calls"] += 1
            name = ev.get("toolName") or ev.get("name") or "?"
            args = ev.get("args") or ev.get("input") or ev.get("arguments") or ""
            self._say(f"tool #{stats['tool_calls']} start: {name} {_short(args, 100)}", stats)
            if stats["tool_calls"] == 1:   # learn the real field names; remove later
                self._say(f"(debug) tool event keys: {sorted(ev)}", stats)
        elif t == "tool_execution_end":
            raw = json.dumps(ev, default=str)
            m = _EXEC.search(raw)
            if m:
                status, attempt, total = m.group(1), int(m.group(2)), m.group(3)
                stats["sandbox_attempts"].append({"attempt": attempt, "status": status})
                hint = ""
                if status == "FAILED":
                    hint = " | " + raw[m.end(): m.end() + 220].replace("\\n", " ")
                self._say(f"sandbox attempt {attempt}/{total}: {status}{hint}", stats)
            else:
                self._say("tool finished", stats)
        elif t in ("message_end", "turn_end"):
            msg = ev.get("message") or {}
            if t == "turn_end":
                stats["turns"] += 1
            if msg.get("role") == "assistant":
                stats["last_assistant_stop"] = msg.get("stopReason")
                stats["last_assistant_error"] = msg.get("errorMessage")
                if msg.get("stopReason") == "error":
                    err = msg.get("errorMessage") or "unknown provider error"
                    if err not in stats["errors"]:
                        stats["errors"].append(err)
                        self._say(f"MODEL/PROVIDER ERROR: {_short(err, 300)}", stats)
        elif t == "compaction_start":
            self._say(f"Pi compaction/recovery started ({ev.get('reason')})", stats)
        elif t == "extension_error":
            self._say(f"extension error: {_short(ev, 300)}", stats)

    def _heartbeat(self, stats, stop):
        while not stop.wait(self.HEARTBEAT_S):
            idle = time.time() - stats["last_event_at"]
            warn = "  [!] no events for 90s, provider may be stalled" if idle > 90 else ""
            sb = [a["status"] for a in stats["sandbox_attempts"]] or "none yet"
            self._say(
                f"running | turns={stats['turns']} tools={stats['tool_calls']} "
                f"sandbox={sb} streamed={stats['streamed_chars']} chars | "
                f"last={stats['last_event']} {idle:.0f}s ago{warn}", stats)

    def _finish(self, stats):
        """Judge the final state; Pi must have settled (or exited after agent_end)."""
        stats["finished"] = True
        if stats["last_assistant_stop"] == "error":
            raise PiRPCError(stats["last_assistant_error"]
                             or "Pi agent ended with an error")
        stats["no_tool_calls"] = stats["tool_calls"] == 0
        if stats["no_tool_calls"]:
            self._say("WARNING: agent finished without calling any tool", stats)
        else:
            self._say("agent finished (outputs still need verifying)", stats)
        return stats

    # ---------- plumbing ----------

    def _pump(self):
        print("[PiRPC] stdout reader started", flush=True)
        for line in iter(self.proc.stdout.readline, ""):
            line = line.rstrip("\n").rstrip("\r")
            if not line.strip():
                continue
            try:
                self._events.write(line + "\n")
                self._events.flush()
            except ValueError:
                pass  # file already closed
            try:
                self._q.put(json.loads(line))
            except json.JSONDecodeError:
                print("[PiRPC] Invalid JSON from Pi", flush=True)
                self._q.put({"type": "_unparsed", "raw": line})
        print("[PiRPC] stdout closed", flush=True)
        self._q.put(None)

    def send(self, cmd):
        print(f"[PiRPC SEND] {cmd.get('type')}", flush=True)
        with self._lock:
            self.proc.stdin.write(json.dumps(cmd) + "\n")
            self.proc.stdin.flush()

    def _next(self, idle_s, deadline):
        remaining = deadline - time.time()
        if remaining <= 0:
            raise TimeoutError("total timeout reached")
        try:
            ev = self._q.get(timeout=min(idle_s, remaining))
        except queue.Empty:
            raise TimeoutError("no output from pi (idle timeout)")
        if ev is None:
            raise PiRPCError("pi exited unexpectedly")
        if ev.get("type") == "extension_ui_request" and ev.get("method") in self.DIALOGS:
            self.send({"type": "extension_ui_response", "id": ev["id"], "cancelled": True})
        return ev

    # ---------- main API ----------

    def run_prompt(self, message, idle_s, total_s, max_tool_calls,
                   on_event=None, images=None):
        """Send a prompt; return stats only when Pi has settled. Raises on failure."""
        req = uuid.uuid4().hex
        deadline = time.time() + total_s
        stats = self._new_stats()
        self.last_stats = stats

        cmd = {"id": req, "type": "prompt", "message": message}
        if images:
            cmd["images"] = images
        self.send(cmd)

        stop_hb = threading.Event()
        threading.Thread(target=self._heartbeat, args=(stats, stop_hb),
                         daemon=True).start()
        try:
            while True:
                idle = min(idle_s, self.POST_END_IDLE_S) if stats["agent_ended"] else idle_s
                try:
                    ev = self._next(idle, deadline)
                except (TimeoutError, PiRPCError):
                    if stats["agent_ended"]:
                        # run ended but agent_settled never arrived: judge final state
                        return self._finish(stats)
                    raise

                t = ev.get("type")
                self._note(ev, stats)
                if on_event:
                    on_event(ev)

                if t == "response" and ev.get("id") == req:
                    if not ev.get("success"):
                        raise PiRPCError(f"prompt rejected: {ev.get('error')}")
                    if (ev.get("data") or {}).get("disposition") == "handled":
                        return self._finish(stats)   # no run started, nothing to wait for

                if (t == "tool_execution_start"
                        and stats["tool_calls"] >= max_tool_calls
                        and not stats["aborted"]):
                    self._say("maximum tool calls reached; aborting", stats)
                    self.send({"type": "abort"})
                    stats["aborted"] = True

                if t == "agent_settled":
                    return self._finish(stats)
        except Exception as e:
            stats["finished"] = True
            self._say(f"FAILED: {e}", stats)
            raise
        finally:
            stop_hb.set()

    def drain(self):
        """Discard leftover queued events before sending a new prompt."""
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass

    def last_assistant_text(self, timeout_s=30):
        req = uuid.uuid4().hex
        self.send({"id": req, "type": "get_last_assistant_text"})
        deadline = time.time() + timeout_s
        while True:
            ev = self._next(timeout_s, deadline)
            if ev.get("type") == "response" and ev.get("id") == req:
                return (ev.get("data") or {}).get("text") or ""

    def close(self):
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()
        self._stderr.close()
        try:
            self._events.close()
        except Exception:
            pass