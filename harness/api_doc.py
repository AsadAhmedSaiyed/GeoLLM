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


def _annotations(args, returns):
    """Return ({param_name: annotation_or_None}, return_annotation_or_None)."""
    result = {}

    for arg in args.posonlyargs + args.args + args.kwonlyargs:
        result[arg.arg] = ast.unparse(arg.annotation) if arg.annotation else None

    return_annotation = ast.unparse(returns) if returns else None

    return result, return_annotation


@lru_cache(maxsize=1)
def signatures():
    """Return dynamically extracted API information for every library module."""
    out = {}

    for mod in MODULES:
        path = LIB / f"{mod}.py"

        if not path.exists():
            continue

        tree = ast.parse(path.read_text(encoding="utf-8"))

        funcs = {}
        names = set()

        for node in tree.body:
            # Keep track of public functions/classes/constants.
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                names.add(node.name)

            elif isinstance(node, ast.Assign):
                names.update(
                    target.id
                    for target in node.targets
                    if isinstance(target, ast.Name)
                )

            # Extract public function documentation.
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                n, expr = _returns(node)

                annotations, return_annotation = _annotations(
                    node.args,
                    node.returns,
                )

                ret = f" -> {return_annotation}" if return_annotation else ""

                funcs[node.name] = {
                    **_params(node.args),
                    "sig": f"{node.name}({ast.unparse(node.args)}){ret}",
                    "doc": (ast.get_docstring(node) or "").strip(),
                    "annotations": annotations,
                    "return_annotation": return_annotation,
                    "tuple_n": n,
                    "tuple_expr": expr,
                }

        out[mod] = {
            "doc": (ast.get_docstring(tree) or "").split("\n")[0],
            "names": names,
            "functions": funcs,
        }

    return out


def module_overview():
    blocks = []

    for mod, info in signatures().items():
        blocks.append(f"# geollm_lib.{mod} - {info['doc']}")

        for f in info["functions"].values():
            blocks.append(
                f"  from geollm_lib.{mod} import {f['sig']}\n"
                f"    {f['doc'].replace(chr(10), ' ')[:500]}"
            )

    return "\n".join(blocks)


def docs_for(modules):
    """Full signatures and docs for the given modules (io and result are always included)."""
    sig = signatures()
    names = [m.removeprefix("geollm_lib.") for m in modules]
    wanted = list(dict.fromkeys(["io", "result", *[m for m in names if m in sig]]))
    blocks = []

    for mod in wanted:
        blocks.append(f"# geollm_lib.{mod} - {sig[mod]['doc']}")

        for f in sig[mod]["functions"].values():
            ret = (
                f"\n    RETURNS a tuple of {f['tuple_n']}: {f['tuple_expr']}"
                if f["tuple_n"]
                else ""
            )

            annotations = f.get("annotations", {})

            param_types = [
                f"{name}: {annotation}"
                for name, annotation in annotations.items()
                if annotation
            ]

            type_info = ""
            if param_types:
                type_info = "\n    Parameter types: " + ", ".join(param_types)

            if f.get("return_annotation"):
                type_info += f"\n    Return type: {f['return_annotation']}"

            blocks.append(
                f"  from geollm_lib.{mod} import {f['sig']}\n"
                f"    {f['doc'].replace(chr(10), ' ')[:700]}"
                f"{type_info}{ret}"
            )

    return "\n".join(blocks)