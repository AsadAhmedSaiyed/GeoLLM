"""Standalone Google Gemini (AI Studio) client via the OpenAI-compatible endpoint.

Used when GEOLLM_VISION_PROVIDER is set to "google" or "gemini", keeping
existing Groq and OpenRouter code paths untouched.
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

import requests

GEMINI_OPENAI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"


def is_gemini_vision_enabled() -> bool:
    prov = (os.environ.get("GEOLLM_VISION_PROVIDER") or "").strip().lower()
    return prov in ("google", "gemini") and bool((os.environ.get("GEMINI_API_KEY") or "").strip())


def _normalize_model(model: Optional[str]) -> str:
    m = (model or os.environ.get("GEOLLM_VISION_MODEL") or "gemini-2.5-flash").strip()
    if m.startswith("google/"):
        m = m[len("google/"):]
    return m


def chat_completion(
    messages: List[Dict[str, Any]],
    model: Optional[str] = None,
    temperature: float = 0.1,
    timeout: int = 120,
    max_tokens: int = 4096,
) -> str:
    """Send text or multimodal (OpenAI-format) messages to Google AI Studio Gemini."""
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("Set GEMINI_API_KEY in geollm/.env to use Google Gemini.")

    target_model = _normalize_model(model)
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": target_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    last_err = None
    for attempt in range(3):
        r = requests.post(GEMINI_OPENAI_URL, headers=headers, json=payload, timeout=timeout)
        if r.status_code == 200:
            data = r.json()
            choices = data.get("choices") or []
            if not choices:
                raise RuntimeError("Gemini returned no choices.")
            text = (choices[0].get("message", {}).get("content") or "").strip()
            if not text:
                raise RuntimeError("Gemini returned an empty response.")
            return text
        if r.status_code in (429, 500, 502, 503) and attempt < 2:
            last_err = f"Gemini HTTP {r.status_code}: {r.text[:300]}"
            time.sleep(2 ** attempt)
            continue
        raise RuntimeError(f"Gemini error {r.status_code}: {r.text[:500]}")

    raise RuntimeError(last_err or "Gemini request failed.")
