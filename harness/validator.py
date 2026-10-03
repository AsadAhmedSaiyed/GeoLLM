"""Policy and API check on generated code. Saves time and catches API mistakes; Docker is the security boundary."""
import ast

ALLOWED_IMPORTS = {"numpy", "scipy", "pandas", "rasterio", "geopandas", "shapely", "matplotlib", "geollm_lib",
                   "json", "math", "pathlib", "datetime", "collections", "itertools", "statistics",
                   "warnings", "typing", "functools", "re"}
BANNED_CALLS = {"eval", "exec", "compile", "__import__", "input", "breakpoint", "globals", "locals",
                "vars", "getattr", "setattr", "delattr"}
BANNED_NAMES = {"subprocess", "sys", "os", "importlib", "builtins", "ctypes", "socket", "shutil", "pickle", "marshal"}
OK_PREFIXES = ("/workspace", "/tmp")


def _api():
    try:
        from . import api_doc
        return api_doc.signatures()
    except Exception:
        return None


def _check_call(node, label, info):
    probs = []
    has_star = any(isinstance(a, ast.Starred) for a in node.args) or any(k.arg is None for k in node.keywords)
    n_pos = len(node.args)
    if not info["vararg"] and n_pos > len(info["pos"]):
        probs.append(f"{label}() takes at most {len(info['pos'])} positional arguments. Signature: {info['sig']}")
    allowed = set(info["pos"]) | set(info["kwonly"])
    for k in node.keywords:
        if k.arg is not None and k.arg not in allowed and not info["varkw"]:
            probs.append(f"{label}() has no parameter '{k.arg}'. Signature: {info['sig']}")
    if not has_star:
        given = set(info["pos"][:n_pos]) | {k.arg for k in node.keywords if k.arg}
        missing = [r for r in info["required"] if r not in given]
        if missing:
            probs.append(f"{label}() is missing required argument(s) {missing}. Signature: {info['sig']}")
    return probs


def validate(code, api="auto", require_result=True):
    """Returns a list of problems (empty = OK)."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"SyntaxError on line {e.lineno}: {e.msg}"]
    api = _api() if api == "auto" else api
    problems = []
    funcs, modalias = {}, {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                root = a.name.split(".")[0]
                if root not in ALLOWED_IMPORTS:
                    problems.append(f"import '{a.name}' is not allowed")
                elif root == "geollm_lib":
                    parts = a.name.split(".")
                    if len(parts) == 1 or not a.asname:
                        problems.append("Use explicit imports: 'from geollm_lib.<module> import <function>' (not 'import geollm_lib').")
                    elif api is not None:
                        if parts[1] in api:
                            modalias[a.asname] = parts[1]
                        else:
                            problems.append(f"geollm_lib has no module '{parts[1]}'. Modules: {sorted(api)}")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            root = mod.split(".")[0]
            if node.level or root not in ALLOWED_IMPORTS:
                problems.append(f"import from '{mod}' is not allowed")
                continue
            for a in node.names:
                if a.name in BANNED_NAMES:
                    problems.append(f"importing '{a.name}' is not allowed")
            if root == "geollm_lib" and api is not None:
                parts = mod.split(".")
                if len(parts) == 1:
                    for a in node.names:
                        if a.name in api:
                            modalias[a.asname or a.name] = a.name
                        else:
                            problems.append(f"geollm_lib has no module '{a.name}'. Modules: {sorted(api)}")
                else:
                    m = parts[1]
                    if m not in api:
                        problems.append(f"geollm_lib has no module '{m}'. Modules: {sorted(api)}")
                        continue
                    for a in node.names:
                        if a.name in api[m]["functions"]:
                            funcs[a.asname or a.name] = (m, a.name)
                        elif a.name not in api[m]["names"]:
                            problems.append(f"'{a.name}' is not in geollm_lib.{m}. Available: {sorted(api[m]['functions'])}")
        elif isinstance(node, ast.Attribute):
            if node.attr in BANNED_NAMES or (node.attr.startswith("__") and node.attr != "__name__"):
                problems.append(f"attribute '.{node.attr}' is not allowed")
        elif isinstance(node, ast.Name):
            if node.id in BANNED_NAMES or (node.id.startswith("__") and node.id != "__name__"):
                problems.append(f"name '{node.id}' is not allowed")

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name) and f.id in BANNED_CALLS:
                problems.append(f"call to '{f.id}()' is not allowed")
            if isinstance(f, ast.Name) and f.id == "open" and node.args and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str):
                p = node.args[0].value
                if (p.startswith("/") and not p.startswith(OK_PREFIXES)) or ".." in p:
                    problems.append(f"open('{p}') is outside the allowed folders (/workspace, /tmp)")
            if api is not None:
                if isinstance(f, ast.Name) and f.id in funcs:
                    m, n = funcs[f.id]
                    problems += _check_call(node, n, api[m]["functions"][n])
                elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in modalias:
                    m = modalias[f.value.id]
                    if f.attr in api[m]["functions"]:
                        problems += _check_call(node, f"{m}.{f.attr}", api[m]["functions"][f.attr])
                    else:
                        problems.append(f"geollm_lib.{m} has no function '{f.attr}'. Available: {sorted(api[m]['functions'])}")
        if api is not None and isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Call):
            f = node.value.func
            info = None
            if isinstance(f, ast.Name) and f.id in funcs:
                m, n = funcs[f.id]
                info, label = api[m]["functions"][n], n
            if info and info["tuple_n"]:
                problems.append(f"{label}() returns a tuple of {info['tuple_n']} values ({info['tuple_expr']}); "
                                f"unpack it, e.g. 'a, b = {label}(...)'.")
    if require_result and "save_result" not in code:
        problems.append("The script must call save_result({...}) with the task result.")
    return list(dict.fromkeys(problems))