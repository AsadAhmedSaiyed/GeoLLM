"""Repair generated task scripts using patches or complete rewrites."""

import ast
import difflib
import re

from . import llm, prompts


_BLOCK = re.compile(
    r"<<<<<<< SEARCH\n(.*?)\n=======\n(.*?)\n>>>>>>> REPLACE",
    re.S,
)

_LN = re.compile(r"^(?:>>)?\s*\d+ \| ?")


def _strip_numbers(text):
    """Remove line-number prefixes when every non-empty line has one."""
    lines = text.split("\n")

    if all(_LN.match(line) for line in lines if line.strip()):
        return "\n".join(_LN.sub("", line) for line in lines)

    return text


def _valid_python(code):
    """Return True only when code is syntactically valid Python."""
    try:
        ast.parse(code)
        return True
    except SyntaxError:
        return False


def parse_patches(text):
    """Extract SEARCH/REPLACE blocks from an LLM response."""
    return [
        (
            _strip_numbers(match.group(1)),
            _strip_numbers(match.group(2)),
        )
        for match in _BLOCK.finditer(text)
    ]


def _fuzzy(code_lines, old):
    """Find a unique matching block while ignoring line whitespace."""
    old_lines = [line.strip() for line in old.split("\n")]

    hits = [
        i
        for i in range(len(code_lines) - len(old_lines) + 1)
        if [
            line.strip()
            for line in code_lines[i:i + len(old_lines)]
        ] == old_lines
    ]

    if len(hits) == 1:
        return hits[0], hits[0] + len(old_lines)

    return None


def apply_patches(code, patches):
    """Apply SEARCH/REPLACE patches. Returns (new_code, errors)."""
    errors = []

    for old, new in patches:
        count = code.count(old)

        if count == 1:
            code = code.replace(old, new)

        elif count > 1:
            errors.append(
                "SEARCH text matches more than once; include more context"
            )

        else:
            lines = code.split("\n")
            span = _fuzzy(lines, old)

            if span:
                start, end = span

                code = "\n".join(
                    lines[:start]
                    + new.split("\n")
                    + lines[end:]
                )
            else:
                errors.append(
                    "SEARCH text not found in the script: "
                    + old.split("\n")[0][:80]
                )

    return code, errors


def diff_stats(old, new):
    """Return basic statistics and a truncated unified diff."""
    diff = list(
        difflib.unified_diff(
            old.split("\n"),
            new.split("\n"),
            lineterm="",
            n=0,
        )
    )

    changed = sum(
        1
        for line in diff
        if line[:1] in "+-"
        and line[:3] not in ("+++", "---")
    )

    return {
        "changed_lines": changed,
        "total_lines": len(old.split("\n")),
        "diff": "\n".join(diff)[:3000],
    }


def _code_block(text):
    """Extract Python code from an LLM response."""
    return llm.extract_code(text)


def _format_context(context):
    """Build structured repair context for the LLM."""
    task = context.get("task", {})
    current_code = context.get("current_code", "")
    failure = context.get("failure", "")
    dataset_facts = context.get("dataset_facts", {})
    capabilities = context.get("capabilities", "")
    previous_attempts = context.get("previous_attempts", [])
    attempt_number = context.get("attempt_number", 1)
    repeated = context.get("repeated_failure", False)
    repeat_note = (
        "\nThis exact failure has already repeated. Your previous approach did "
        "not work. Choose a different method or hypothesis instead of "
        "adjusting the same logic.\n"
        if repeated
        else ""
    )

    return f"""
ORIGINAL TASK
=============

{task}


CURRENT SCRIPT
==============

```python
{current_code}
```


FAILURE / VALIDATION FEEDBACK
=============================

{failure}


DATASET FACTS
=============

{dataset_facts}


AVAILABLE CAPABILITIES
======================

{capabilities}


PREVIOUS ATTEMPTS
=================

This is repair attempt number {attempt_number}.
{repeat_note}
{previous_attempts}


REPAIR OBJECTIVE
================

Correct the implementation so that it satisfies the ORIGINAL TASK.

Diagnose the actual cause of the failure before changing the code.

You may choose any valid implementation strategy.

The current implementation is NOT authoritative.

Helpers are optional capabilities, not requirements.

You may:

* fix existing logic
* remove incorrect logic
* change the algorithm
* change how inputs are interpreted
* use a different helper
* stop using a helper
* combine helpers with custom Python
* implement the operation directly with allowed libraries
* completely rewrite the script

If the current architecture is fundamentally sound, prefer a focused patch.

If the current approach is fundamentally wrong, rewrite it.

Do NOT preserve incorrect code merely because it already exists.

Do NOT force the solution to use a helper.

Do NOT replace the requested task with an easier unrelated operation.

The primary objectives are:

1. Correctly perform the requested task.
2. Produce the expected outputs.
3. Respect the available data and runtime constraints.
4. Produce scientifically defensible results.
5. Report limitations truthfully.

If the available data genuinely cannot support the requested operation,
do not invent data or results. Use the established result protocol to
report the limitation.

Do not invent:

* missing bands
* wavelengths
* timestamps
* measurements
* thresholds
* geographic observations
* metadata
* files
* sensor properties
"""


def _build_messages(context):
    """Build the repair-model conversation."""
    return [
        {
            "role": "system",
            "content": prompts.DEBUG,
        },
        {
            "role": "user",
            "content": _format_context(context),
        },
    ]


def _apply_patch_response(code, reply):
    """Try to apply SEARCH/REPLACE blocks from an LLM response."""
    patches = parse_patches(reply)

    if not patches:
        return None, "no SEARCH/REPLACE block found"

    new_code, errors = apply_patches(code, patches)

    if errors:
        return None, "; ".join(errors)

    if new_code == code:
        return None, "the patch changed nothing"

    return new_code, None


def _extract_rewrite(reply):
    """Try to extract a complete Python rewrite."""
    rewritten = _code_block(reply)

    if not rewritten:
        return None

    return rewritten.strip()


def patch(context):
    """
    Repair a generated task implementation.

    The repair model may:
    1. Apply a focused SEARCH/REPLACE patch.
    2. Completely rewrite the script.

    Rewrites are only accepted when they are syntactically valid Python.

    Args:
        context: Structured repair context containing:
            task
            current_code
            failure
            dataset_facts
            capabilities
            previous_attempts

    Returns:
        (new_code, mode, info)
    """

    code = context.get("current_code", "")

    if not code:
        return None, "failed", {
            "reason": "no current code was provided",
        }

    messages = _build_messages(context)

    # ---------------------------------------------------------
    # ATTEMPT 1
    # ---------------------------------------------------------

    reply = llm.chat(
        messages,
        show=False,
    )

    patches = parse_patches(reply)

    if patches:
        new_code, error = _apply_patch_response(
            code,
            reply,
        )

        if new_code is not None:
            return (
                new_code,
                "patch",
                diff_stats(code, new_code),
            )

        failure_reason = error

    else:
        rewritten = _extract_rewrite(reply)

        if rewritten and rewritten != code:
            if _valid_python(rewritten):
                return (
                    rewritten,
                    "rewrite",
                    diff_stats(code, rewritten),
                )

            failure_reason = (
                "repair model returned syntactically invalid Python"
            )

        else:
            failure_reason = (
                "response contained neither a valid patch "
                "nor a complete Python rewrite"
            )

    # ---------------------------------------------------------
    # ATTEMPT 2
    # ---------------------------------------------------------

    retry_context = dict(context)

    retry_context["failure"] = (
        str(context.get("failure", ""))
        + "\n\n"
        + "PREVIOUS REPAIR RESPONSE FAILED\n"
        + "--------------------------------\n"
        + f"{failure_reason}\n"
    )

    retry_messages = _build_messages(retry_context)

    retry_messages.append(
        {
            "role": "user",
            "content": """
The previous repair response could not be applied.

Generate a valid correction now.

You have two valid output formats.

FORMAT 1 — PATCH

Use exact SEARCH/REPLACE blocks:

<<<<<<< SEARCH
exact existing code
=======
corrected code
>>>>>>> REPLACE

FORMAT 2 — COMPLETE REWRITE

Return the entire corrected script inside exactly one Python code block.

Choose PATCH when the existing approach is fundamentally correct.

Choose COMPLETE REWRITE when the existing approach is fundamentally wrong.

Do not explain the answer.
""",
        }
    )

    retry_reply = llm.chat(
        retry_messages,
        show=False,
    )

    retry_patches = parse_patches(retry_reply)

    if retry_patches:
        new_code, error = _apply_patch_response(
            code,
            retry_reply,
        )

        if new_code is not None:
            return (
                new_code,
                "patch",
                diff_stats(code, new_code),
            )

        failure_reason = error

    else:
        rewritten = _extract_rewrite(retry_reply)

        if rewritten and rewritten != code:
            if _valid_python(rewritten):
                return (
                    rewritten,
                    "rewrite",
                    diff_stats(code, rewritten),
                )

            failure_reason = (
                "second repair response returned "
                "syntactically invalid Python"
            )

        else:
            failure_reason = (
                "second repair response contained neither "
                "a valid patch nor a complete Python rewrite"
            )

    return None, "failed", {
        "reason": failure_reason,
    }