import base64
import json
import os
import re
import time

import requests

import logging as _logging
_dvlog = _logging.getLogger("geollm.debug_vision")
_DEBUG_VISION = os.environ.get("GEOLLM_DEBUG_VISION", "") == "1"


def _dv(msg: str, *args) -> None:
    """Emit a debug-vision log line only when GEOLLM_DEBUG_VISION=1."""
    if _DEBUG_VISION:
        _dvlog.debug(msg, *args)


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

def _openrouter(messages, show, model=None, stream=True):
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError(
            "Set OPENROUTER_API_KEY in your environment (never commit it)."
        )

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model or MODEL,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 4096,
        "stream": stream,
    }

    if _DEBUG_VISION:
        import json as _json
        _safe_messages = []
        _total_payload_chars = 0
        for _m in messages:
            _role = _m.get("role", "?")
            _content = _m.get("content", "")
            if isinstance(_content, list):
                _types = [_p.get("type", "?") for _p in _content]
                _img_count = sum(1 for _p in _content if _p.get("type") == "image_url")
                _img_bytes = sum(
                    len(_p.get("image_url", {}).get("url", "")) * 3 // 4
                    for _p in _content
                    if _p.get("type") == "image_url"
                )
                _safe_messages.append({
                    "role": _role,
                    "content_types": _types,
                    "image_count": _img_count,
                    "image_approx_bytes": _img_bytes,
                })
            else:
                _safe_messages.append({"role": _role, "content_type": "text", "text_len": len(_content or "")})
            _total_payload_chars += len(_json.dumps(_m))
        _dv(
            "[LLM request] model=%r max_tokens=%s stream=%s n_messages=%d messages=%s total_payload_bytes~=%d",
            model or MODEL,
            payload.get("max_tokens"),
            stream,
            len(messages),
            _safe_messages,
            _total_payload_chars,
        )
    print(
        f"[GeoLLM] OpenRouter → model={model or MODEL}, "
        f"timeout=120s, streaming={stream}",
        flush=True,
    )

    if not stream:
        try:
            r = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=120)
            if r.status_code == 429:
                raise RuntimeError("OpenRouter rate limit reached (429). Wait briefly and try again.")
            if r.status_code != 200:
                raise RuntimeError(f"OpenRouter error {r.status_code}: {r.text[:500]}")
            res_json = r.json()
            if "error" in res_json:
                err = res_json["error"]
                msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                raise RuntimeError(f"OpenRouter error: {msg}")
            choices = res_json.get("choices") or []
            if not choices:
                raise RuntimeError("OpenRouter returned no choices.")
            msg = choices[0].get("message") or {}
            text = msg.get("content") or msg.get("reasoning") or ""
            if show and text:
                print(text)
            if not text:
                if _DEBUG_VISION:
                    import json as _json
                    _finish = choices[0].get("finish_reason") if choices else "N/A"
                    _usage = res_json.get("usage", {})
                    _msg_keys = list(msg.keys()) if msg else []
                    _raw_snippet = _json.dumps(res_json)[:2000]
                    _dv(
                        "[LLM empty-response] status=%s finish_reason=%r usage=%s model=%r provider=%r msg_keys=%s raw(2000)=%s",
                        r.status_code,
                        _finish,
                        _usage,
                        res_json.get("model"),
                        res_json.get("provider"),
                        _msg_keys,
                        _raw_snippet,
                    )
                raise RuntimeError("OpenRouter returned an empty response.")
            print(f"[GeoLLM] OpenRouter ← response received ({len(text)} characters)", flush=True)
            if _DEBUG_VISION:
                _dv("[LLM response] chars=%d preview=%r", len(text), text[:200])
            return text
        except requests.RequestException as e:
            raise RuntimeError(f"OpenRouter non-streaming connection failed: {e}")

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

            # Log errors from the payload itself if they appear in the stream
            if "error" in event:
                err = event["error"]
                msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                raise RuntimeError(f"OpenRouter stream error: {msg}")

            choices = event.get("choices") or []
            if not choices:
                continue

            choice = choices[0]
            finish_reason = choice.get("finish_reason")
            if finish_reason and finish_reason in ("content_filter", "refusal"):
                 raise RuntimeError(f"OpenRouter blocked response: {finish_reason}")

            delta = choice.get("delta") or choice.get("message") or {}
            piece = delta.get("content") or delta.get("reasoning") or delta.get("text") or ""

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
        print("[GeoLLM] Streaming returned empty response; falling back to non-streaming OpenRouter request...", flush=True)
        return _openrouter(messages, show, model=model, stream=False)

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
    return bool(VISION_MODEL) and (
        PROVIDER == "openrouter"
        or bool(os.environ.get("OPENROUTER_API_KEY"))
        or "/" in VISION_MODEL
        or PROVIDER == "ollama"
    )


def chat_vision(prompt, image_paths):
    """Ask GEOLLM_VISION_MODEL about PNG images. Uses OpenRouter for cloud models (e.g. Gemini)."""
    if not vision_available():
        raise RuntimeError("No vision model configured (set GEOLLM_VISION_MODEL).")
    b64 = [base64.b64encode(open(p, "rb").read()).decode() for p in image_paths]

    # Route to OpenRouter if an API key is present or model contains '/' (e.g. google/gemini-2.5-flash)
    use_openrouter = (
        PROVIDER == "openrouter"
        or bool(os.environ.get("OPENROUTER_API_KEY"))
        or "/" in VISION_MODEL
    )
    if use_openrouter:
        content = [{"type": "text", "text": prompt}] + [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b}"}} for b in b64
        ]
        # Force stream=False to avoid empty stream responses for vision models
        return _openrouter([{"role": "user", "content": content}], show=False, model=VISION_MODEL, stream=False)

    # Fallback to local Ollama only for local models without '/'
    r = requests.post(
        f"{OLLAMA_URL}/api/chat",
        timeout=600,
        json={
            "model": VISION_MODEL,
            "stream": False,
            "options": {"temperature": 0.1},
            "messages": [{"role": "user", "content": prompt, "images": b64}],
        },
    )
    if r.status_code != 200:
        raise RuntimeError(f"Ollama vision error {r.status_code}: {r.text}")
    return r.json()["message"]["content"]


def extract_code(text):
    blocks = re.findall(r"```(?:python)?\n(.*?)```", text, re.S)
    return blocks[0].strip() if blocks else None