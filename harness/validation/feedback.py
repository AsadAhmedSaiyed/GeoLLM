"""Phase 6 – Structured Feedback Formatter."""
import json
from typing import Dict, Any, List

def format_structured_feedback(session: Any) -> Dict[str, Any]:
    """Transform inspection session into structured JSON."""
    defects = []
    for tid, rec in session.tiles.items():
        if rec.verdict in ("wrong", "needs_review"):
            defects.append({
                "tile_id": tid,
                "type": rec.defect_category or "unknown",
                "rationale": rec.rationale,
                "severity": "high" if rec.verdict == "wrong" else "medium"
            })
            
    return {
        "feedback_version": "2.0",
        "overall_verdict": "not_valid" if defects else "valid",
        "defects": defects
    }
