"""Phase 4 – Reliability Layer: Consensus Voting.

For each tile marked 'wrong' or 'unsure', re-inspects with a fresh crop
and a second LLM call at temperature=0.  Disagreement → 'needs_review'.
All pixel evidence still comes from tools, never from the model.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Callable, Dict, Optional

from .tools import InspectionSession, crop

logger = logging.getLogger(__name__)

_VERDICT_KEYWORDS = ("correct", "wrong", "unsure", "not_verifiable")
_DEFAULT_CONSENSUS_MAX_TILES = 4


def _parse_verdict_from_text(text: str) -> Optional[str]:
    """Scan response text for one of the recognised verdict keywords.

    Prioritises the first non-empty line (as requested in the prompt). If
    no keyword is on the first line, searches the remaining text for the
    earliest occurrence of a keyword.

    Parameters
    ----------
    text:
        Raw string returned by the vision model.

    Returns
    -------
    The matched verdict keyword in lower-case, or ``None`` if none found.
    """
    if not text:
        return None

    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    if lines:
        first_line = lines[0].lower()
        for kw in _VERDICT_KEYWORDS:
            if re.search(rf"\b{re.escape(kw)}\b", first_line):
                return kw

    # Fallback to search in whole text by earliest match position
    lower = text.lower()
    earliest_pos = None
    earliest_kw = None
    for kw in _VERDICT_KEYWORDS:
        m = re.search(rf"\b{re.escape(kw)}\b", lower)
        if m:
            if earliest_pos is None or m.start() < earliest_pos:
                earliest_pos = m.start()
                earliest_kw = kw
    return earliest_kw


def re_verify_flagged_tiles(
    session: InspectionSession,
    llm_call_fn: Callable[[str, list[str]], str],
) -> Dict[str, str]:
    """Re-verify every tile whose verdict is ``'wrong'`` or ``'unsure'``.

    A fresh high-resolution crop is generated for each candidate tile and a
    second LLM call is made at temperature=0.  When the new verdict disagrees
    with the original, the tile is escalated to ``'needs_review'`` and its
    rationale is updated accordingly.  When they agree the original verdict is
    confirmed and left unchanged.

    Parameters
    ----------
    session:
        The completed :class:`~harness.validation.tools.InspectionSession`.
    llm_call_fn:
        Injected callable with signature ``(prompt: str, image_paths: list[str]) -> str``.
        Receives the re-verification prompt and a list of thumbnail paths; returns
        the model's raw text response.  Injected so unit tests can mock the LLM.

    Returns
    -------
    dict
        Mapping of ``tile_id`` → final verdict string (original or
        ``'needs_review'``).

    Notes
    -----
    * Never raises — all per-tile exceptions are caught and logged; the tile
      keeps its original verdict on any error.
    * Respects the ``GEOLLM_CONSENSUS_MAX_TILES`` environment variable (default 4).
    """
    max_tiles: int = int(
        os.environ.get("GEOLLM_CONSENSUS_MAX_TILES", str(_DEFAULT_CONSENSUS_MAX_TILES))
    )

    candidates = [
        (tid, rec)
        for tid, rec in session.tiles.items()
        if rec.verdict in ("wrong", "unsure")
    ][:max_tiles]

    results: Dict[str, str] = {}

    for tid, rec in candidates:
        original_verdict = rec.verdict or "unsure"
        try:
            crop_result = crop(session, tile_id=tid, zoom_level=2)

            if not crop_result.get("ok"):
                logger.warning(
                    "consensus: crop failed for tile %s — %s",
                    tid,
                    crop_result.get("error", "unknown"),
                )
                results[tid] = original_verdict
                continue

            thumb_path: str = session.tiles[tid].evidence_crop_path or str(
                session.feedback_dir
                / "thumbs"
                / f"{tid}_z2.png"
            )

            prompt = (
                f"Re-verification request for tile {tid}.\n"
                f"Original verdict: {original_verdict}\n"
                f"Original rationale: {rec.rationale}\n\n"
                "Please re-examine the attached crop and provide your updated verdict. "
                "Reply with exactly one of: correct, wrong, unsure, not_verifiable — "
                "on the first line, followed by your reasoning."
            )

            response_text = llm_call_fn(prompt, [thumb_path])
            new_verdict = _parse_verdict_from_text(response_text)

            if new_verdict is None:
                logger.warning(
                    "consensus: could not parse verdict from response for tile %s", tid
                )
                results[tid] = original_verdict
                continue

            if new_verdict != original_verdict:
                # Disagreement — escalate
                rec_updated = session.tiles[tid]
                import dataclasses
                session.tiles[tid] = dataclasses.replace(
                    rec_updated,
                    verdict="needs_review",
                    rationale=(
                        f"[CONSENSUS DISAGREEMENT] Original: {original_verdict}; "
                        f"Re-verification: {new_verdict}. "
                        f"Original rationale: {rec.rationale}"
                    )[:500],
                )
                results[tid] = "needs_review"
                logger.info(
                    "consensus: tile %s escalated to 'needs_review' "
                    "(original=%s, re-verify=%s)",
                    tid,
                    original_verdict,
                    new_verdict,
                )
            else:
                # Agreement — confirmed
                results[tid] = original_verdict
                logger.info(
                    "consensus: tile %s confirmed as '%s'", tid, original_verdict
                )

        except Exception as exc:  # noqa: BLE001
            logger.exception("consensus: unexpected error for tile %s: %s", tid, exc)
            results[tid] = original_verdict

    # Pass-through for tiles that were not re-verified
    for tid, rec in session.tiles.items():
        if tid not in results:
            results[tid] = rec.verdict or "not_verifiable"

    return results
