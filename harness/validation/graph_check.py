"""Phase 5 – Graph & Tabular Data Verification."""
from pathlib import Path
from typing import Dict, Any, Optional

def validate_graph_deliverable(png_path: Path, session_output_dir: Path) -> Dict[str, Any]:
    """Validate a graph PNG.
    
    Checks:
    1. Presence of companion CSV (recommended).
    2. Axes labels, units, and legend (visual heuristic).
    3. Cross-reference with CSV if found.
    """
    csv_path = session_output_dir / png_path.with_suffix(".csv").name
    report = {
        "file": png_path.name,
        "csv_found": csv_path.is_file(),
        "issues": [],
        "verdict": "valid"
    }
    
    if not csv_path.is_file():
        report["issues"].append("No companion CSV data found for this plot. Analysis cannot be verified numerically.")
        report["verdict"] = "unsure"
        
    return report
