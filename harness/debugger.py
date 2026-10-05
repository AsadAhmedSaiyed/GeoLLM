"""Turns a failure into focused feedback for the patcher.
Nothing here depends on a list of known errors: the message, traceback and numbered code are always passed through.
HINTS is only an optional extra for a few failure kinds."""
import re

_TB = re.compile(r'File "/workspace/code/script\.py", line (\d+)')

GENERIC = ("Base your diagnosis on the evidence in the failure message and traceback, not on a first guess. "
           "Find the smallest cause and change only that, keeping everything that already works. "
           "If an earlier change did not alter the failure, that hypothesis was wrong: choose a different one.")

HINTS = {
    "validation": "Remove or replace exactly the flagged construct. Use the helper signatures given.",
    "numerical": ("The message contains measured evidence (counts, ranges, file properties). Diagnose from those "
                  "numbers. Do not assume the cause is the method or its parameters: also check how outputs were "
                  "written (dtype, nodata, shape, CRS) and how inputs were read."),
    "visual": "Change only the plotting or selection logic implicated by the visual feedback.",
    "no_result": "The script must call save_result({...}) once at the end.",
    "requirements": "Add only the missing computation or output; keep the working parts.",
}


def error_line(stderr):
    """Line number of the last frame inside the generated script (the call site to fix), or None."""
    m = _TB.findall(stderr or "")
    return int(m[-1]) if m else None


def error_type(stderr):
    """Exception name from the last traceback line, e.g. 'KeyError'. Works for any exception."""
    lines = [l for l in (stderr or "").strip().splitlines() if l.strip()]
    if not lines:
        return None
    head = lines[-1].split(":")[0].strip()
    return head if re.fullmatch(r"[A-Za-z_][\w.]*", head) else None


def numbered(code, mark=None):
    out = []
    for i, line in enumerate(code.split("\n"), start=1):
        out.append(f"{'>>' if i == mark else '  '}{i:4d} | {line}")
    return "\n".join(out)


def _signature(entry):
    return (entry.get("kind", ""), (entry.get("message", "").strip().splitlines() or [""])[0][:120])


def build_feedback(task, code, kind, message, stderr=""):
    """Feedback text for the patcher. `kind` is a free label; unknown kinds are fine."""
    lines = code.split("\n")
    mark = error_line(stderr)
    etype = error_type(stderr)

    past = list(task.feedback)
    if past and past[-1].get("message") == message:
        past = past[:-1]
    repeated = bool(task.feedback) and bool(past) and _signature(past[-1]) == _signature(task.feedback[-1])
    hist = "\n".join(f"- attempt {f['attempt']} [{f['kind']}]: {f['message'][:600]}" for f in past[-4:])

    parts = [f"TASK {task.id}: {task.name}\n{task.description}\nExpected outputs: {task.expected_outputs}",
             f"FAILURE KIND: {kind}" + (f" ({etype})" if etype else "") + f"\n{message}"]
    if stderr:
        parts.append(f"TRACEBACK (tail):\n{stderr[-1500:]}")
    if mark and 1 <= mark <= len(lines):
        parts.append(f"FAILING LINE {mark}: {lines[mark - 1].strip()}")
    if "BandError" in (stderr or "") + message:
        parts.append("BandError means the requested band or role was not found. First check whether the code asked "
                     "for the wrong band number or role, or passed the wrong object. Never substitute an unrelated "
                     "band. Only if the file genuinely lacks the required data, patch the script to call "
                     "save_result({'error': '<what is missing and why>'}).")
    if repeated:
        parts.append("The same failure happened again after the previous patch, so that patch did not fix it. "
                     "Do not repeat it; try a different approach.")
    if getattr(task, "patches", None) and task.patches[-1].get("diff"):
        parts.append("LAST PATCH APPLIED (if the failure is unchanged, this patch was not the cause):\n"
                     + task.patches[-1]["diff"][:800])
    parts.append(f"PREVIOUS FEEDBACK:\n{hist or '(none)'}")
    parts.append("GUIDANCE: " + GENERIC + (" " + HINTS[kind] if kind in HINTS else ""))
    parts.append(f"CURRENT SCRIPT (line numbers are not part of the code{'; >> marks the failing line' if mark else ''}):\n"
                 + numbered(code, mark))
    return "\n\n".join(parts)