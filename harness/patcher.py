"""Apply minimal patches (SEARCH/REPLACE blocks) to a task script; full rewrite only as a fallback."""
import difflib
import re

from . import llm, prompts

_BLOCK = re.compile(r"<<<<<<< SEARCH\n(.*?)\n=======\n(.*?)\n>>>>>>> REPLACE", re.S)

_LN = re.compile(r"^(?:>>)?\s*\d+ \| ?")


def _strip_numbers(text):
    """Remove the 'NN | ' line-number prefixes if (and only if) every non-empty line has one."""
    lines = text.split("\n")
    if all(_LN.match(l) for l in lines if l.strip()):
        return "\n".join(_LN.sub("", l) for l in lines)
    return text


def parse_patches(text):
    return [(_strip_numbers(m.group(1)), _strip_numbers(m.group(2))) for m in _BLOCK.finditer(text)]


def _fuzzy(code_lines, old):
    """Unique match ignoring leading/trailing whitespace per line. Returns (start, end) or None."""
    ol = [l.strip() for l in old.split("\n")]
    hits = [i for i in range(len(code_lines) - len(ol) + 1) if [l.strip() for l in code_lines[i:i + len(ol)]] == ol]
    return (hits[0], hits[0] + len(ol)) if len(hits) == 1 else None


def apply_patches(code, patches):
    """Returns (new_code, errors)."""
    errors = []
    for old, new in patches:
        n = code.count(old)
        if n == 1:
            code = code.replace(old, new)
        elif n > 1:
            errors.append("SEARCH text matches more than once; include more context")
        else:
            lines = code.split("\n")
            span = _fuzzy(lines, old)
            if span:
                code = "\n".join(lines[:span[0]] + new.split("\n") + lines[span[1]:])
            else:
                errors.append("SEARCH text not found in the script: " + old.split("\n")[0][:80])
    return code, errors


def diff_stats(old, new):
    d = list(difflib.unified_diff(old.split("\n"), new.split("\n"), lineterm="", n=0))
    changed = sum(1 for l in d if l[:1] in "+-" and l[:3] not in ("+++", "---"))
    return {"changed_lines": changed, "total_lines": len(old.split("\n")), "diff": "\n".join(d)[:3000]}


def _code_block(text):
    return llm.extract_code(text)


def patch(code, feedback):
    """Ask the model for a minimal patch. Returns (new_code or None, mode 'patch'|'rewrite'|'failed', info)."""
    messages = [{"role": "system", "content": prompts.DEBUG}, {"role": "user", "content": feedback}]
    reply = llm.chat(messages, show=False)
    patches = parse_patches(reply)
    if patches:
        new, errs = apply_patches(code, patches)
        if not errs and new != code:
            return new, "patch", diff_stats(code, new)
        why = "; ".join(errs) or "the patch changed nothing"
    else:
        why = "no SEARCH/REPLACE block found"
        rewritten = _code_block(reply)
        if rewritten:
            return rewritten, "rewrite", diff_stats(code, rewritten)
    reply = llm.chat(messages + [{"role": "assistant", "content": reply},
                                 {"role": "user", "content": f"Your patch could not be applied ({why}). Reply with the complete corrected "
                                  "script in one ```python block, changing only what is necessary."}], show=False)
    rewritten = _code_block(reply)
    if rewritten:
        return rewritten, "rewrite", diff_stats(code, rewritten)
    return None, "failed", {"reason": why}