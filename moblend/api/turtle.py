"""MoSpline Turtle mode: an L-system drawn by a 3D turtle into a curve object.

Rewriting is O(final string length) per iteration (it grows geometrically with Iterations, so the
length is capped); drawing is one pass over the final string. The curve regenerates whenever one of
its settings changes through set_params.

Turtle commands: F / G draw forward, f move without drawing, + - turn (yaw), & ^ pitch, \\ / roll,
| turn around, [ ] push / pop the turtle (branches), ! shrink the step. Other letters are ignored.
"""

import math

import bpy
from mathutils import Matrix, Vector

from ..catalog import KEY_KIND, KEY_TYPE, Kind
from .objects import link_new, select_only, tag
from .params import PARAM_SOURCES, Param

MAX_LENGTH = 200_000  # characters; beyond this an L-system is too big to draw interactively
SETTINGS = {"Premise": "F", "Rules": "F=F[+F]F[-F]F", "Iterations": 3, "Angle": 25.7, "Step": 0.2,
            "Shrink": 0.7}
# The turtle walks along its local Z (plants grow up): yaw turns around X, pitch around Y, roll around Z.
TURNS = {"+": ("X", 1), "-": ("X", -1), "&": ("Y", 1), "^": ("Y", -1), "\\": ("Z", 1), "/": ("Z", -1)}


def parse_rules(text):
    """'F=FF+[+F-F-F], X=F[+X]' -> {'F': 'FF+[+F-F-F]', 'X': 'F[+X]'} (separators: comma, semicolon, newline)."""
    rules = {}
    for part in filter(None, (p.strip() for p in text.replace(";", ",").replace("\n", ",").split(","))):
        key, sep, value = part.partition("=")
        if not sep or len(key.strip()) != 1:
            raise ValueError(f"Rule {part!r} must look like 'F=...'")
        rules[key.strip()] = value.strip()
    return rules


def expand(premise, rules, iterations):
    s = premise
    for _ in range(iterations):
        s = "".join(rules.get(ch, ch) for ch in s)
        if len(s) > MAX_LENGTH:
            raise ValueError(f"L-system grows past {MAX_LENGTH} characters; use fewer iterations")
    return s


def draw(commands, angle, step, shrink):
    """Turtle path as polylines (one list of points per unbroken stroke)."""
    turn = math.radians(angle)
    m, length = Matrix.Identity(3), step
    pos = Vector()
    stack, lines, current = [], [], [pos.copy()]
    for ch in commands:
        if ch in "FG":
            pos = pos + m @ Vector((0, 0, length))
            current.append(pos.copy())
        elif ch == "f":
            pos = pos + m @ Vector((0, 0, length))
            if len(current) > 1:
                lines.append(current)
            current = [pos.copy()]
        elif ch in TURNS:
            axis, sign = TURNS[ch]
            m = m @ Matrix.Rotation(sign * turn, 3, axis)
        elif ch == "|":
            m = m @ Matrix.Rotation(math.pi, 3, "X")
        elif ch == "!":
            length *= shrink
        elif ch == "[":
            stack.append((pos.copy(), m.copy(), length))
        elif ch == "]" and stack:
            if len(current) > 1:
                lines.append(current)
            pos, m, length = stack.pop()
            current = [pos.copy()]
    if len(current) > 1:
        lines.append(current)
    return lines


def _regenerate(o):
    lines = draw(expand(o["Premise"], parse_rules(o["Rules"]), int(o["Iterations"])), o["Angle"], o["Step"],
                 o["Shrink"])
    cu = o.data
    cu.splines.clear()
    for pts in lines:
        sp = cu.splines.new("POLY")
        sp.points.add(len(pts) - 1)
        sp.points.foreach_set("co", [c for p in pts for c in (*p, 1.0)])
    o.update_tag()
    return len(lines)


def create_mospline_turtle(name=None, location=None, **settings):
    """MoSpline Turtle: a curve drawn from an L-system (Premise, Rules, Iterations, Angle, Step, Shrink)."""
    cu = bpy.data.curves.new(name or "MoSpline Turtle", "CURVE")
    cu.dimensions = "3D"
    o = tag(link_new(bpy.data.objects.new(cu.name, cu), location), **{KEY_KIND: Kind.MOSPLINE, KEY_TYPE: "turtle"})
    for key, default in SETTINGS.items():
        o[key] = settings.get(key.lower(), settings.get(key, default))
    _regenerate(o)
    select_only(o)
    return o


def _params(o):
    kinds = {"Premise": "STRING", "Rules": "STRING", "Iterations": "INT", "Angle": "FLOAT", "Step": "FLOAT",
             "Shrink": "FLOAT"}
    return [Param(k, o, f'["{k}"]', kind, on_change=_regenerate) for k, kind in kinds.items()]


PARAM_SOURCES.append((lambda o: o.get(KEY_KIND) == Kind.MOSPLINE and o.get(KEY_TYPE) == "turtle", _params))
