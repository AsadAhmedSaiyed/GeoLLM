import ast

ALLOWED_IMPORTS = {
    "numpy", "rasterio", "geopandas", "shapely", "matplotlib", "geollm_lib",
    "json", "math", "os", "pathlib", "datetime", "collections", "itertools",
    "statistics", "warnings", "typing",
}
BANNED_CALLS = {"eval", "exec", "compile", "__import__", "input", "breakpoint"}
BANNED_ATTRS = {"system", "popen", "fork", "execv", "execve", "spawnl", "spawnv", "rmtree", "remove", "unlink"}


def validate(code):
    """Returns a list of problems. Empty list = OK."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"SyntaxError on line {e.lineno}: {e.msg}"]

    problems = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in ALLOWED_IMPORTS:
                    problems.append(f"import '{alias.name}' is not allowed")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if node.level or root not in ALLOWED_IMPORTS:
                problems.append(f"import from '{node.module}' is not allowed")
        elif isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name) and f.id in BANNED_CALLS:
                problems.append(f"call to '{f.id}()' is not allowed")
            if isinstance(f, ast.Attribute) and f.attr in BANNED_ATTRS:
                problems.append(f"call to '.{f.attr}()' is not allowed")
    if "save_result" not in code:
        problems.append("script must call save_result({...}) with the final numbers")
    return problems