"""Policy check on LLM code. Saves time and blocks obvious abuse; Docker is the real wall."""
import ast

ALLOWED_IMPORTS = {"numpy", "scipy", "pandas", "rasterio", "geopandas", "shapely", "matplotlib", "geollm_lib",
                   "json", "math", "pathlib", "datetime", "collections", "itertools", "statistics",
                   "warnings", "typing", "functools", "re"}
BANNED_CALLS = {"eval", "exec", "compile", "__import__", "input", "breakpoint", "globals", "locals",
                "vars", "getattr", "setattr", "delattr"}
BANNED_NAMES = {"subprocess", "sys", "os", "importlib", "builtins", "ctypes", "socket", "shutil", "pickle", "marshal"}


def validate(code):
    """Returns a list of problems (empty = OK)."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"SyntaxError on line {e.lineno}: {e.msg}"]
    problems = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in ALLOWED_IMPORTS:
                    problems.append(f"import '{a.name}' is not allowed")
        elif isinstance(node, ast.ImportFrom):
            if node.level or (node.module or "").split(".")[0] not in ALLOWED_IMPORTS:
                problems.append(f"import from '{node.module}' is not allowed")
            for a in node.names:
                if a.name in BANNED_NAMES:
                    problems.append(f"importing '{a.name}' is not allowed")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in BANNED_CALLS:
                problems.append(f"call to '{node.func.id}()' is not allowed")
        elif isinstance(node, ast.Attribute):
            if node.attr in BANNED_NAMES or (node.attr.startswith("__") and node.attr != "__name__"):
                problems.append(f"attribute '.{node.attr}' is not allowed")
        elif isinstance(node, ast.Name):
            if node.id in BANNED_NAMES or (node.id.startswith("__") and node.id != "__name__"):
                problems.append(f"name '{node.id}' is not allowed")
    return problems