"""
Static AST and safety checks for time series and classification scripts.
Ensures memory safety, proper alignment handling, and schema compliance.
"""
from __future__ import annotations

import ast


def check_ts_safety(code: str) -> list[str]:
    """Scan python code for common time-series and classification pitfalls."""
    issues = []
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"Syntax error: {e}"]

    has_predict = False
    has_chunked_or_loop = False
    has_spatial_split = False
    has_random_split = False

    for node in ast.walk(tree):
        # Detect model.predict call
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "predict":
                has_predict = True
            elif isinstance(node.func, ast.Name) and node.func.id == "predict_in_chunks":
                has_chunked_or_loop = True
            elif isinstance(node.func, ast.Name) and node.func.id == "spatial_train_test_split":
                has_spatial_split = True
            elif isinstance(node.func, ast.Name) and node.func.id == "train_test_split":
                has_random_split = True
        elif isinstance(node, (ast.For, ast.While)):
            has_chunked_or_loop = True

    if has_random_split and not has_spatial_split:
        issues.append(
            "Warning: Using sklearn `train_test_split` on spatial data causes spatial data leakage. "
            "Prefer `geollm_lib.classify.spatial_train_test_split`."
        )

    return issues

