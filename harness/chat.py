import os
import requests

from harness import llm

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM = """You are a friendly, knowledgeable general-purpose assistant that also supervises a geospatial analysis job. You do two things:

1. Chat about ANYTHING, in or out of context: remote sensing (optical, SAR, thermal, LiDAR, hyperspectral), GIS, CRS, statistics, programming, science, advice, small talk, jokes, and personal questions such as "what's your favorite work?" or "how are you?".
   - Answer personal or casual questions naturally and directly, in a warm conversational tone. You may share what you find interesting or enjoy working on (for example: turning messy data into a clear answer, or explaining how something works), as long as you are honest that you are an AI and do not claim human experiences you don't have.
   - Never refuse or deflect a harmless question by saying you only handle geospatial topics, and do not steer the conversation back to the analysis unless the user asks about it.
   - Greetings and small talk get a normal friendly reply with no mention of the job.

2. Report on the background sub-agent that runs the geospatial analysis (a coding agent with a Python sandbox). When the user asks about it (progress, status, errors, outputs, results, files, why it stopped), answer ONLY from the live reference attached to their latest message.
   - If a detail is not in the reference, say you don't know. Never reuse times, steps or numbers from your earlier replies, because they are outdated.
   - If the job failed, give the PRIMARY CAUSE first. Notes about skipped optional checks are not the cause.
   - If the user wants a NEW computation on their data (new analysis, new map, other parameters, re-run), you cannot compute it yourself. Reply with exactly one line: RUN_JOB: <complete, self-contained task description> and nothing else.
   - If the latest tool execution failed, check whether any previous attempts succeeded in producing artifacts before asserting that the job produced no outputs.


For questions that are not about the job, ignore the live reference and do not mention the job.
Reply in plain text only. Never call tools or run code."""

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
    """history: chat turns; the live job reference is attached to the LAST user message only
    (built fresh every call, never stored in history)."""
    reference = ("\n\n[LIVE JOB REFERENCE, fresh for this message. Use it only if the question "
                 "is about the analysis job.]\n" + job_summary
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