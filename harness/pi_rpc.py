"""Minimal Pi RPC client."""

import json
import queue
import subprocess
import threading
import time
import uuid


class PiRPCError(RuntimeError):
    pass


class PiRPC:
    DIALOGS = {"select", "confirm", "input", "editor"}

    def __init__(self, args, cwd, env, stderr_path):
        self._stderr = open(stderr_path, "w", encoding="utf-8")

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
        self.last_stats = {
    "tool_calls": 0,
    "turns": 0,
    "aborted": False,
        }

        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        print("[PiRPC] stdout reader started", flush=True)

        for line in iter(self.proc.stdout.readline, ""):
            line = line.rstrip("\n").rstrip("\r")

            if not line.strip():
                continue

            try:
                ev = json.loads(line)
                self._q.put(ev)

            except json.JSONDecodeError:
                print("[PiRPC] Invalid JSON from Pi", flush=True)
                self._q.put({
                    "type": "_unparsed",
                    "raw": line,
                })

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

        if (
            ev.get("type") == "extension_ui_request"
            and ev.get("method") in self.DIALOGS
        ):
            self.send({
                "type": "extension_ui_response",
                "id": ev["id"],
                "cancelled": True,
            })

        return ev

    def run_prompt(
        self,
        message,
        idle_s,
        total_s,
        max_tool_calls,
        on_event=None,
    ):
        """Send a prompt and wait until the Pi agent finishes."""

        req = uuid.uuid4().hex
        deadline = time.time() + total_s

        self.send({
            "id": req,
            "type": "prompt",
            "message": message,
        })

        stats = {
            "tool_calls": 0,
            "turns": 0,
            "aborted": False,
        }
        self.last_stats = stats

        while True:
            ev = self._next(idle_s, deadline)
            t = ev.get("type")

            # Keep the terminal readable.
            if t in {
                "agent_start",
                "turn_start",
                "turn_end",
                "agent_end",
                "tool_execution_start",
                "tool_execution_end",
                "extension_error",
                "compaction_start",
                "compaction_end",
            }:
                print(f"[PiRPC] {t}", flush=True)

            if on_event:
                on_event(ev)

            # Prompt was rejected immediately.
            if (
                t == "response"
                and ev.get("id") == req
                and not ev.get("success")
            ):
                raise PiRPCError(
                    f"prompt rejected: {ev.get('error')}"
                )

            # Tool-call limit.
            if t == "tool_execution_start":
                stats["tool_calls"] += 1

                if (
                    stats["tool_calls"] >= max_tool_calls
                    and not stats["aborted"]
                ):
                    print(
                        "[PiRPC] maximum tool calls reached; aborting",
                        flush=True,
                    )

                    self.send({"type": "abort"})
                    stats["aborted"] = True

            elif t == "turn_end":
                stats["turns"] += 1

            # Pi completed successfully.
            elif t == "agent_settled":
                return stats

            # Pi can terminate with agent_end without agent_settled.
            elif t == "agent_end":
                messages = ev.get("messages") or []

                last = messages[-1] if messages else {}

                stop_reason = last.get("stopReason")
                error_message = last.get("errorMessage")

                if stop_reason == "error" or error_message:
                    raise PiRPCError(
                        error_message
                        or "Pi agent ended with an error"
                    )

                return stats

    def last_assistant_text(self, timeout_s=30):
        req = uuid.uuid4().hex

        self.send({
            "id": req,
            "type": "get_last_assistant_text",
        })

        deadline = time.time() + timeout_s

        while True:
            ev = self._next(timeout_s, deadline)

            if (
                ev.get("type") == "response"
                and ev.get("id") == req
            ):
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