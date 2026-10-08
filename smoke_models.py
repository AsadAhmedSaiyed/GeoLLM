import os, time, json, requests

URL = "https://openrouter.ai/api/v1/chat/completions"
HEAD = {"Authorization": "Bearer " + os.environ["OPENROUTER_API_KEY"]}
MODELS = [
    "cohere/north-mini-code:free",
    "poolside/laguna-s-2.1:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
]
TOOL = {"type": "function", "function": {
    "name": "save_result", "description": "Save the final result",
    "parameters": {"type": "object", "properties": {
        "changed_pixels": {"type": "integer"}, "summary": {"type": "string"}},
        "required": ["changed_pixels", "summary"]}}}
PROMPT = ("Call save_result with changed_pixels=3887 and a one-sentence summary. "
          "Do not write any other text.")

for m in MODELS:
    t = time.time()
    try:
        r = requests.post(URL, headers=HEAD, timeout=90, json={
            "model": m, "temperature": 0, "max_tokens": 512, "tools": [TOOL],
            "messages": [{"role": "user", "content": PROMPT}]})
        if r.status_code != 200:
            print(f"{m:50s} HTTP {r.status_code} {r.text[:100]}")
        else:
            calls = r.json()["choices"][0]["message"].get("tool_calls") or []
            ok = bool(calls) and json.loads(calls[0]["function"]["arguments"]).get("changed_pixels") == 3887
            print(f"{m:50s} tool_call_ok={ok}  {time.time()-t:.1f}s")
    except Exception as e:
        print(f"{m:50s} ERROR {e}")
    time.sleep(4)   # stay under free-tier rate limits