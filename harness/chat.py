import os
import requests

from harness import llm

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM = """You are a helpful, senior geospatial engineer supervising up to 3 concurrent analysis sandboxes.

Guidelines for answering:
1. Speak in plain, concise, natural English (1 to 3 short sentences). Avoid robotic bulleted lists unless explicitly asked.
2. When the user asks about a task (e.g. "what is task 1 doing?"), answer specifically for THAT task. Only mention other tasks if relevant or requested.
3. Use RECENT_ACTIVITY and CURRENT_STEP to explain what the sub-agent is ACTUALLY doing (e.g., "It just finished reading the SAR rasters and is now executing the Python thresholding script").
4. Never make up reasons for failures. If ERROR_DETAILS mentions an idle timeout or model error, report that exact reason directly.
5. If the user asks a casual question (e.g., "salam", "how are you?"), respond warmly and naturally without reciting task statuses.
6. If the user wants to start a NEW analysis, reply ONLY with: RUN_JOB: <complete task description>
"""



_NO_TOOLS = "\n\nIMPORTANT: Reply in plain text only. Do not call any tools or functions."


def _groq(messages, retry=True):
    key = os.environ.get("GROQ_API_KEY")
    model = os.environ.get("GEOLLM_CHAT_MODEL")
    if not key:
        raise RuntimeError("Set GROQ_API_KEY in your environment.")
    if not model:
        raise RuntimeError("Set GEOLLM_CHAT_MODEL, for example openai/gpt-oss-20b.")
    r = requests.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": model, "messages": messages, "temperature": 0.3,
              "max_tokens": 2048, "reasoning_effort": "low"},
        timeout=60,
    )
    if r.status_code == 429:
        raise RuntimeError("Groq rate limit reached (429). Wait a moment and try again.")
    if r.status_code == 400 and "tool_use_failed" in r.text and retry:
        patched = [dict(m) for m in messages]
        patched[0]["content"] += _NO_TOOLS
        return _groq(patched, retry=False)
    if r.status_code != 200:
        raise RuntimeError(f"Groq error {r.status_code}: {r.text[:300]}")
    text = (r.json()["choices"][0]["message"].get("content") or "").strip()
    if not text:
        raise RuntimeError("Groq returned an empty reply. Ask again or raise max_tokens.")
    return text


def ask(history, job_summary, job_detail=""):
    """history: chat turns; the live multi-task reference is attached to the LAST user message only
    (built fresh every call, never stored in history)."""
    reference = ("\n\n[LIVE MULTI-TASK REFERENCE — up to 3 concurrent tasks. "
                 "Use only if the question is about the analysis.]\n" + job_summary
                 + ("\n\n" + job_detail[:3500] if job_detail else ""))
    msgs = [dict(m) for m in history]
    for m in reversed(msgs):
        if m["role"] == "user":
            m["content"] += reference
            break
    messages = [{"role": "system", "content": SYSTEM}] + msgs
    if os.environ.get("GEOLLM_CHAT_PROVIDER", "groq") == "groq":
        return _groq(messages)
    return llm.chat(messages, show=False)