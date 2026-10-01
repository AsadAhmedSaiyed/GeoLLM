import json
import os
import re
import requests

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("GEOLLM_MODEL", "qwen2.5-coder:7b")


def chat(messages):
    r = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={"model": MODEL, "messages": messages, "stream": True,
              "options": {"temperature": 0.1, "num_ctx": 4096}},
        timeout=900, stream=True,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Ollama error {r.status_code}: {r.text}")
    parts = []
    for line in r.iter_lines():
        if not line:
            continue
        chunk = json.loads(line)
        piece = chunk.get("message", {}).get("content", "")
        print(piece, end="", flush=True)
        parts.append(piece)
    print()
    return "".join(parts)


def extract_code(text):
    blocks = re.findall(r"```(?:python)?\n(.*?)```", text, re.S)
    return blocks[0].strip() if blocks else None