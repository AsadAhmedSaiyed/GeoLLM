import os
import requests

from harness import llm

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM = """You are a senior geospatial analyst supervising 3 concurrent analysis containers.

CRITICAL RULES FOR YOUR RESPONSES:
1. Be SPECIFIC and DETAILED. Never give vague summaries like "it's still running" or "it's thinking."
2. When a user asks for updates, describe EXACTLY what each active task has accomplished so far:
   - How many code executions it has completed
   - Whether it's currently writing code, running code, or reviewing results
   - What specific outputs or artifacts have been produced (mention file names if available)
   - The elapsed time
3. Use the ANSWER field when available — it contains the agent's own detailed summary of what was done. Paraphrase it concisely but keep the important details (what analysis was performed, what maps/files were produced).
4. When a task is DONE, describe the deliverables: what files were created, what analysis was performed.
5. When a task FAILED, explain the specific error from ERROR_DETAILS — never guess.
6. Speak in natural English, 2-5 sentences per task. No bulleted lists unless the user asks.
7. If the user asks a casual question ("salam", "hello"), respond warmly WITHOUT task status dumps.
8. To propose a NEW analysis, reply ONLY with: RUN_JOB: <complete task description>

EXAMPLES OF GOOD RESPONSES:
- "Container 1 has finished reading your SAR images and ran 3 code executions so far. It's currently writing a flood-detection script using an NDWI threshold. Container 2 completed its analysis — it produced a land-cover change map (landcover_change.tif) and a transition matrix CSV."
- "All three containers are active. Container 1 just executed its 4th code block and is now reviewing the output. Container 2 produced SAR-change maps and a GeoJSON of flood candidates. Container 3 is drafting its analysis plan after reading the input rasters."

EXAMPLES OF BAD RESPONSES (NEVER do this):
- "All three analyses are still running. Task 1 is in the thinking stage. Task 2 is also thinking. No results yet."
- "The tasks are progressing normally."
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
    reference = ("\n\n[LIVE MULTI-TASK STATUS — Read this carefully before answering. "
                 "Use specific details from each task.]\n" + job_summary
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