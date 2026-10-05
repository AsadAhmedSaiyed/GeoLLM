import base64
import json
import os
import re
import time

import requests

PROVIDER = os.environ.get("LLM_PROVIDER", "ollama")          # ollama | openrouter | pi
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_DEFAULTS = {"ollama": "qwen2.5-coder:7b", "openrouter": "qwen/qwen3-coder", "pi": "pi"}
MODEL = os.environ.get("GEOLLM_MODEL", _DEFAULTS.get(PROVIDER, "qwen2.5-coder:7b"))
VISION_MODEL = os.environ.get("GEOLLM_VISION_MODEL", "")
NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "16384"))


def _ollama(messages, fmt, show):
    payload = {"model": MODEL, "messages": messages, "stream": True, "keep_alive": "30m",
               "options": {"temperature": 0.1, "num_ctx": NUM_CTX}}
    if fmt:
        payload["format"] = fmt
    r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=1800, stream=True)
    if r.status_code != 200:
        raise RuntimeError(f"Ollama error {r.status_code}: {r.text}")
    parts = []
    for line in r.iter_lines():
        if line:
            piece = json.loads(line).get("message", {}).get("content", "")
            if show:
                print(piece, end="", flush=True)
            parts.append(piece)
    if show:
        print()
    return "".join(parts)

def _openrouter(messages, show, model=None):
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError(
            "Set OPENROUTER_API_KEY in your environment (never commit it)."
        )

    payload = {
        "model": model or MODEL,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 4096,
        "stream": True,
    }

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    print(
        f"[GeoLLM] OpenRouter → model={model or MODEL}, "
        f"timeout=120s, streaming=True",
        flush=True,
    )

    try:
        r = requests.post(
            OPENROUTER_URL,
            headers=headers,
            json=payload,
            timeout=120,
            stream=True,
        )
    except requests.Timeout:
        raise RuntimeError("OpenRouter request timed out after 120 seconds.")
    except requests.RequestException as e:
        raise RuntimeError(f"OpenRouter connection failed: {e}")

    if r.status_code == 429:
        raise RuntimeError(
            "OpenRouter rate limit reached (429). "
            "Wait briefly and try again."
        )

    if r.status_code != 200:
        raise RuntimeError(
            f"OpenRouter error {r.status_code}: {r.text[:500]}"
        )

    parts = []

    try:
        for line in r.iter_lines():
            if not line:
                continue

            line = line.decode("utf-8") if isinstance(line, bytes) else line

            if not line.startswith("data:"):
                continue

            data = line[5:].strip()

            if data == "[DONE]":
                break

            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue

            choices = event.get("choices") or []
            if not choices:
                continue

            delta = choices[0].get("delta") or {}
            piece = delta.get("content") or ""

            if piece:
                parts.append(piece)
                if show:
                    print(piece, end="", flush=True)

    except requests.Timeout:
        raise RuntimeError(
            "OpenRouter response timed out while generating."
        )

    text = "".join(parts)

    if show:
        print()

    if not text:
        raise RuntimeError("OpenRouter returned an empty response.")

    print(
        f"[GeoLLM] OpenRouter ← response received "
        f"({len(text)} characters)",
        flush=True,
    )

    return text



def chat(messages, fmt=None, show=True):
    """Text chat. Same call for every provider. fmt='json' is honoured by Ollama only."""
    if PROVIDER == "openrouter":
        return _openrouter(messages, show)
    if PROVIDER == "ollama":
        return _ollama(messages, fmt, show)
    if PROVIDER == "pi":
        from . import pi_runtime
        text = pi_runtime.complete(messages)
        if show:
            print(text)
        return text
    raise RuntimeError(f"Unknown LLM_PROVIDER '{PROVIDER}'")


def vision_available():
    return bool(VISION_MODEL) and PROVIDER in ("openrouter", "ollama")


def chat_vision(prompt, image_paths):
    """Ask GEOLLM_VISION_MODEL about PNG images. Raises if no vision model is configured."""
    if not vision_available():
        raise RuntimeError("No vision model configured (set GEOLLM_VISION_MODEL).")
    b64 = [base64.b64encode(open(p, "rb").read()).decode() for p in image_paths]
    if PROVIDER == "openrouter":
        content = [{"type": "text", "text": prompt}] + [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b}"}} for b in b64]
        return _openrouter([{"role": "user", "content": content}], False, model=VISION_MODEL)
    r = requests.post(f"{OLLAMA_URL}/api/chat", timeout=600, json={
        "model": VISION_MODEL, "stream": False, "options": {"temperature": 0.1},
        "messages": [{"role": "user", "content": prompt, "images": b64}]})
    if r.status_code != 200:
        raise RuntimeError(f"Ollama vision error {r.status_code}: {r.text}")
    return r.json()["message"]["content"]


def extract_code(text):
    blocks = re.findall(r"```(?:python)?\n(.*?)```", text, re.S)
    return blocks[0].strip() if blocks else None