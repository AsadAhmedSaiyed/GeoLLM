import json
import os
import time

import requests

PROVIDER = os.environ.get("LLM_PROVIDER", "ollama")

OLLAMA_URL = os.environ.get(
    "OLLAMA_URL",
    "http://localhost:11434"
)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

_DEFAULTS = {
    "ollama": "qwen2.5-coder:7b",
    "openrouter": "qwen/qwen3-coder",
}

MODEL = os.environ.get(
    "GEOLLM_MODEL",
    _DEFAULTS.get(PROVIDER, "qwen2.5-coder:7b")
)


def _ollama(messages, fmt, show):
    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": True,
        "keep_alive": "30m",
        "options": {
            "temperature": 0.1,
            "num_ctx": 8192,
        },
    }

    if fmt:
        payload["format"] = fmt

    r = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json=payload,
        timeout=1800,
        stream=True,
    )

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


def _openrouter(messages, show):
    key = os.environ.get("OPENROUTER_API_KEY")

    if not key:
        raise RuntimeError(
            "Set OPENROUTER_API_KEY in your environment (never commit it)."
        )

    for attempt in range(4):
        r = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "messages": messages,
                "temperature": 0.1,
                "max_tokens": 4096,
            },
            timeout=300,
        )

        if r.status_code == 429:
            time.sleep(5 * (attempt + 1))
            continue

        break

    if r.status_code != 200:
        raise RuntimeError(
            f"OpenRouter error {r.status_code}: {r.text[:500]}"
        )

    data = r.json()

    if "choices" not in data:
        raise RuntimeError(
            f"OpenRouter returned no answer: {str(data)[:500]}"
        )

    text = data["choices"][0]["message"]["content"] or ""

    if show:
        print(text)

    return text


def chat(messages, fmt=None, show=True):
    if PROVIDER == "openrouter":
        return _openrouter(messages, show)

    if PROVIDER == "ollama":
        return _ollama(messages, fmt, show)

    raise RuntimeError(
        f"Unknown LLM_PROVIDER '{PROVIDER}'"
    )