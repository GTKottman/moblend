"""Compile a math expression into Geometry Nodes (for Formula effectors and fields).

Only arithmetic, comparisons, the variables passed in and the functions below are allowed; the text
is parsed with `ast` and never executed. O(expression size) nodes.

Functions: sin cos tan asin acos atan atan2 abs sqrt pow exp log min max floor ceil fract round
sign clamp(x, lo, hi) mod(a, b) lerp(a, b, t) smoothstep(lo, hi, x) rand(n[, seed]) noise(x, y, z).
Constants: pi, e, tau.
"""

import ast
import math

from .util import out

_UNARY = {"sin": "SINE", "cos": "COSINE", "tan": "TANGENT", "asin": "ARCSINE", "acos": "ARCCOSINE",
          "atan": "ARCTANGENT", "abs": "ABSOLUTE", "sqrt": "SQRT", "exp": "EXPONENT", "floor": "FLOOR",
          "ceil": "CEIL", "fract": "FRACT", "round": "ROUND", "sign": "SIGN"}
_BINARY = {"pow": "POWER", "min": "MINIMUM", "max": "MAXIMUM", "atan2": "ARCTAN2", "mod": "FLOORED_MODULO",
           "log": "LOGARITHM"}
_OPS = {ast.Add: "ADD", ast.Sub: "SUBTRACT", ast.Mult: "MULTIPLY", ast.Div: "DIVIDE", ast.Pow: "POWER",
        ast.Mod: "FLOORED_MODULO"}
_COMPARE = {ast.Lt: "LESS_THAN", ast.Gt: "GREATER_THAN"}
CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau}
NAMES = sorted(set(_UNARY) | set(_BINARY) | {"clamp", "lerp", "smoothstep", "rand", "noise"})


class FormulaError(ValueError):
    pass


def check(expr, variables):
    """Raise FormulaError if `expr` is not a valid formula over `variables` (no nodes created)."""
    _walk(ast.parse(expr, mode="eval").body, set(variables))


def _walk(node, variables):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return
    if isinstance(node, ast.Name):
        if node.id not in variables and node.id not in CONSTANTS:
            raise FormulaError(f"Unknown name {node.id!r}; use {sorted(variables)} or {sorted(CONSTANTS)}")
        return
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        return _walk(node.operand, variables)
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        _walk(node.left, variables)
        return _walk(node.right, variables)
    if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in _COMPARE:
        _walk(node.left, variables)
        return _walk(node.comparators[0], variables)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in NAMES:
        for arg in node.args:
            _walk(arg, variables)
        return
    raise FormulaError(f"Not allowed in a formula: {ast.unparse(node)!r}")


def compile_expr(b, expr, variables):
    """Socket computing `expr`, where `variables` maps names to sockets. Validates first."""
    tree = ast.parse(expr, mode="eval").body
    _walk(tree, set(variables))
    return _emit(b, tree, variables)


def _emit(b, node, env):
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.Name):
        return env[node.id] if node.id in env else CONSTANTS[node.id]
    if isinstance(node, ast.UnaryOp):
        v = _emit(b, node.operand, env)
        return b.math("MULTIPLY", v, -1.0) if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.BinOp):
        return b.math(_OPS[type(node.op)], _emit(b, node.left, env), _emit(b, node.right, env))
    if isinstance(node, ast.Compare):
        return b.math(_COMPARE[type(node.ops[0])], _emit(b, node.left, env), _emit(b, node.comparators[0], env))
    name, args = node.func.id, [_emit(b, a, env) for a in node.args]

    def need(n):
        if len(args) != n:
            raise FormulaError(f"{name}() takes {n} argument(s)")

    if name in _UNARY:
        need(1)
        return b.math(_UNARY[name], args[0])
    if name in _BINARY:
        if name == "log" and len(args) == 1:
            return b.math("LOGARITHM", args[0], math.e)
        need(2)
        return b.math(_BINARY[name], *args)
    if name == "clamp":
        need(3)
        return b.math("MINIMUM", b.math("MAXIMUM", args[0], args[1]), args[2])
    if name == "lerp":
        need(3)
        return b.math("MULTIPLY_ADD", b.math("SUBTRACT", args[1], args[0]), args[2], args[0])
    if name == "smoothstep":
        need(3)
        return b.map_range(args[2], args[0], args[1], 0.0, 1.0, "SMOOTHSTEP")
    if name == "rand":
        if len(args) not in (1, 2):
            raise FormulaError("rand() takes 1 or 2 arguments")
        n = b.node("FunctionNodeRandomValue", {"Min": 0.0, "Max": 1.0, "ID": args[0],
                                               "Seed": args[1] if len(args) == 2 else 0}, data_type="FLOAT")
        return out(n, "Value")
    need(3)  # noise(x, y, z)
    nz = b.noise4d(b.combine(*args), 0.0)
    return b.math("SUBTRACT", b.math("MULTIPLY", nz.outputs["Factor"], 2.0), 1.0)
