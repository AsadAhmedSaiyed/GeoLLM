"""Documentation of geollm_lib generated from the real source (AST), so prompts never drift from the code."""
import ast
from functools import lru_cache
from pathlib import Path

LIB = Path(__file__).resolve().parent.parent / "lib" / "geollm_lib"
MODULES = ("io", "bands", "indices", "masks", "vector", "align", "change", "viz", "stats", "result",
           "sar", "hyperspectral", "temporal")


def _returns(fn):
    rets = [n for n in ast.walk(fn) if isinstance(n, ast.Return) and n.value is not None]
    if rets and all(isinstance(r.value, ast.Tuple) for r in rets) and len({len(r.value.elts) for r in rets}) == 1:
        return len(rets[0].value.elts), ast.unparse(rets[0].value)
    return None, None


def _params(args):
    pos = [a.arg for a in args.posonlyargs + args.args]
    required = pos[: len(pos) - len(args.defaults)]
    required += [a.arg for a, d in zip(args.kwonlyargs, args.kw_defaults) if d is None]
    return {"pos": pos, "kwonly": [a.arg for a in args.kwonlyargs], "required": required,
            "vararg": bool(args.vararg), "varkw": bool(args.kwarg)}


@lru_cache(maxsize=1)
def signatures():
    """{module: {"doc", "names", "functions": {name: {sig, doc, pos, kwonly, required, vararg, varkw, tuple_n, tuple_expr}}}}"""
    out = {}
    for mod in MODULES:
        path = LIB / f"{mod}.py"
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        funcs, names = {}, set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                names.update(t.id for t in node.targets if isinstance(t, ast.Name))
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                n, expr = _returns(node)
                ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
                funcs[node.name] = {**_params(node.args), "sig": f"{node.name}({ast.unparse(node.args)}){ret}",
                                    "doc": (ast.get_docstring(node) or "").strip(), "tuple_n": n, "tuple_expr": expr}
        out[mod] = {"doc": (ast.get_docstring(tree) or "").split("\n")[0], "names": names, "functions": funcs}
    return out


def module_overview():
    return "\n".join(f"- geollm_lib.{m}: {i['doc']} [{', '.join(i['functions'])}]" for m, i in signatures().items())


def docs_for(modules):
    """Full signatures and docs for the given modules (io and result are always included)."""
    sig = signatures()
    wanted = list(dict.fromkeys(["io", "result", *[m for m in modules if m in sig]]))
    blocks = []
    for mod in wanted:
        blocks.append(f"# geollm_lib.{mod} - {sig[mod]['doc']}")
        for f in sig[mod]["functions"].values():
            ret = f"\n    RETURNS a tuple of {f['tuple_n']}: {f['tuple_expr']}" if f["tuple_n"] else ""
            blocks.append(f"  from geollm_lib.{mod} import {f['sig']}\n    {f['doc'].replace(chr(10), ' ')[:450]}{ret}")
    return "\n".join(blocks)