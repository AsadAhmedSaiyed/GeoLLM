"""Reproduce turn-1 and turn-2 of the agentic vision loop for one frame.

Usage (bash / PowerShell):
    python scripts/debug_vision_turn2.py <path/to/frame.png>

Env vars required:
    OPENROUTER_API_KEY   – OpenRouter API key
    GEOLLM_VISION_MODEL  – e.g. google/gemini-2.5-flash

Optional:
    GEOLLM_DEBUG_VISION=1   – enable verbose logging in llm.py / agent.py

This script does NOT run in a loop and makes at most 4 API calls.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Make sure the project root is on sys.path regardless of CWD
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from harness import llm as _llm
from harness.validation.agent import (
    _build_system_prompt,
    _make_overview,
    _DEFAULT_OVERVIEW_MAX_PX,
)


# ---------------------------------------------------------------------------
# Safe request summary (no base64, no API key)
# ---------------------------------------------------------------------------

def _safe_summary(messages: list[dict]) -> dict:
    """Return a loggable summary of a messages list."""
    summary = []
    total_chars = 0
    for m in messages:
        role = m.get("role", "?")
        content = m.get("content", "")
        if isinstance(content, list):
            types = [p.get("type", "?") for p in content]
            img_count = sum(1 for p in content if p.get("type") == "image_url")
            img_bytes = sum(
                len(p.get("image_url", {}).get("url", "")) * 3 // 4
                for p in content
                if p.get("type") == "image_url"
            )
            summary.append({
                "role": role,
                "content_types": types,
                "image_count": img_count,
                "image_approx_bytes": img_bytes,
            })
        else:
            summary.append({"role": role, "content_type": "text", "text_len": len(content or "")})
        total_chars += len(json.dumps(m))
    return {"messages": summary, "total_payload_bytes_approx": total_chars}


# ---------------------------------------------------------------------------
# Build turn-1 and turn-2 messages exactly as the agent does
# ---------------------------------------------------------------------------

def build_turn1_messages(png_path: Path, feedback_dir: Path) -> tuple[list[dict], str]:
    """Return (messages, overview_path_str) for turn 1."""
    import base64

    overview_path = _make_overview(png_path, feedback_dir, _DEFAULT_OVERVIEW_MAX_PX)

    # The agent passes the SYSTEM prompt as the user message on turn 1
    system_prompt = _build_system_prompt(
        task_name="debug_repro",
        task_description="Reproduction script — no real task.",
        image_name=png_path.name,
    )

    b64 = base64.b64encode(overview_path.read_bytes()).decode()
    content = [
        {"type": "text", "text": system_prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
    ]
    messages = [{"role": "user", "content": content}]
    return messages, str(overview_path)


def build_turn2_messages(turn1_messages: list[dict], turn1_reply: str, overview_path_str: str) -> list[dict]:
    """Return messages for turn 2 — built exactly as the agent builds them.

    The agent does NOT carry history; it passes only the tool-result prompt
    + image_paths to llm_call, which re-wraps them as a fresh single-user message.
    This is the critical reproduction of what the agent actually sends.
    """
    import base64

    tool_result_prompt = (
        "Tool result for 'make_grid':\n"
        "```json\n"
        '{"ok": true, "grid": "2x2", "tiles": [], "message": "Grid 2x2 created (4 tiles). Call crop(tile_id) to inspect each."}\n'
        "```\nContinue inspection. Reply with the next tool call."
    )

    # chat_vision always constructs a NEW single-user message — history is NOT passed
    b64 = base64.b64encode(Path(overview_path_str).read_bytes()).decode()
    content = [
        {"type": "text", "text": tool_result_prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
    ]
    messages = [{"role": "user", "content": content}]
    return messages


# ---------------------------------------------------------------------------
# Raw OpenRouter call (bypasses chat_vision wrapper for inspection)
# ---------------------------------------------------------------------------

def _call_openrouter_raw(messages: list[dict], max_tokens: int = 4096, label: str = "") -> tuple[str | None, dict]:
    """Call OpenRouter non-streaming; return (text_or_None, raw_response_dict)."""
    import requests

    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        print("ERROR: OPENROUTER_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    model = os.environ.get("GEOLLM_VISION_MODEL", "")
    if not model:
        print("ERROR: GEOLLM_VISION_MODEL not set", file=sys.stderr)
        sys.exit(1)

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": max_tokens,
        "stream": False,
    }

    print(f"\n{'='*60}")
    print(f"[{label}] Sending to OpenRouter")
    print(f"  model        : {model}")
    print(f"  max_tokens   : {max_tokens}")
    print(f"  stream       : False")
    safe = _safe_summary(messages)
    print(f"  messages     : {json.dumps(safe['messages'], indent=4)}")
    print(f"  payload_bytes: ~{safe['total_payload_bytes_approx']}")
    print(f"{'='*60}")

    t0 = time.time()
    r = requests.post("https://openrouter.ai/api/v1/chat/completions",
                      headers=headers, json=payload, timeout=120)
    elapsed = time.time() - t0

    print(f"  HTTP status  : {r.status_code}  ({elapsed:.2f}s)")

    if r.status_code != 200:
        print(f"  ERROR body   : {r.text[:500]}")
        return None, {}

    res_json = r.json()
    # Safe print of raw response (truncated, no base64)
    raw_snippet = json.dumps(res_json)[:2000]
    print(f"  raw_response : {raw_snippet}")

    choices = res_json.get("choices") or []
    if not choices:
        print(f"  RESULT       : NO CHOICES in response")
        return None, res_json

    msg = choices[0].get("message") or {}
    finish_reason = choices[0].get("finish_reason")
    usage = res_json.get("usage", {})
    provider = res_json.get("provider")

    print(f"  finish_reason: {finish_reason!r}")
    print(f"  usage        : {usage}")
    print(f"  provider     : {provider!r}")
    print(f"  msg_keys     : {list(msg.keys())}")

    text = msg.get("content") or msg.get("reasoning") or ""
    if text:
        print(f"  response_len : {len(text)} chars")
        print(f"  preview      : {text[:200]!r}")
        return text, res_json
    else:
        print(f"  RESULT       : EMPTY content and reasoning")
        return None, res_json


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/debug_vision_turn2.py <path/to/frame.png>")
        sys.exit(1)

    png_path = Path(sys.argv[1]).resolve()
    if not png_path.is_file():
        print(f"ERROR: file not found: {png_path}")
        sys.exit(1)

    feedback_dir = _PROJECT_ROOT / "runs" / "debug_repro" / "feedback"
    feedback_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[repro] Frame      : {png_path}")
    print(f"[repro] Model      : {os.environ.get('GEOLLM_VISION_MODEL', '(not set)')}")
    print(f"[repro] Feedback   : {feedback_dir}")

    # ---- Turn 1 ----
    t1_messages, overview_path = build_turn1_messages(png_path, feedback_dir)
    t1_reply, t1_raw = _call_openrouter_raw(t1_messages, max_tokens=4096, label="TURN-1")

    if t1_reply is None:
        print("\n[repro] TURN-1 FAILED — cannot continue to turn 2")
        sys.exit(1)

    print(f"\n[repro] Turn 1 OK — reply length {len(t1_reply)} chars")

    # ---- Turn 2 (baseline — same as agent) ----
    t2_messages = build_turn2_messages(t1_messages, t1_reply, overview_path)
    t2_reply, t2_raw = _call_openrouter_raw(t2_messages, max_tokens=4096, label="TURN-2 (baseline)")
    t2_pass = t2_reply is not None

    # ---- Variation A: same request, max_tokens=8192 ----
    t2a_messages = build_turn2_messages(t1_messages, t1_reply, overview_path)
    t2a_reply, t2a_raw = _call_openrouter_raw(t2a_messages, max_tokens=8192, label="TURN-2 variation-A max_tokens=8192")
    t2a_pass = t2a_reply is not None

    # ---- Variation B: assistant reply replaced by plain user message ----
    # Build turn-2 messages but prepend turn-1 assistant reply as a user message instead
    import base64
    tool_result_prompt = (
        "Tool result for 'make_grid':\n"
        "```json\n"
        '{"ok": true, "grid": "2x2", "tiles": [], "message": "Grid 2x2 created (4 tiles). Call crop(tile_id) to inspect each."}\n'
        "```\nContinue inspection. Reply with the next tool call."
    )
    b64 = base64.b64encode(Path(overview_path).read_bytes()).decode()
    t2b_messages = [
        {"role": "user", "content": [
            {"type": "text", "text": t1_messages[0]["content"][0]["text"]},  # original system prompt
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]},
        # Instead of an assistant role, inject the turn-1 reply as a second user message
        {"role": "user", "content": f"Previous assistant response: {t1_reply}\n\n{tool_result_prompt}"},
    ]
    t2b_reply, t2b_raw = _call_openrouter_raw(t2b_messages, max_tokens=4096, label="TURN-2 variation-B user-restate")
    t2b_pass = t2b_reply is not None

    # ---- Summary ----
    print("\n" + "="*60)
    print("RESULTS SUMMARY")
    print("="*60)
    print(f"  Turn 1 baseline               : {'PASS' if t1_reply else 'FAIL'}")
    print(f"  Turn 2 baseline (agent exact) : {'PASS' if t2_pass else 'FAIL'}")
    print(f"  Turn 2 variation-A max_tok=8192: {'PASS' if t2a_pass else 'FAIL'}")
    print(f"  Turn 2 variation-B user-restate: {'PASS' if t2b_pass else 'FAIL'}")

    # Exit 0 if any variation passes, 1 if all fail
    if t2_pass or t2a_pass or t2b_pass:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
