"""Field layer types (C4D field objects and layers). Each evaluates a raw 0..1 value per element, then the
shared tail applies Contour, Invert and Remap, multiplies in its own sub-fields (Layers, which makes any
field a Group field), and blends with the layers above it. All O(elements).

Interface of every field type group, in order:
  Previous, First, Element Count, Layers, Transform   (wired by MoBlend, hidden)
  type-specific inputs
  Blend, Opacity, Invert, Contour, Steps, Remap Min, Remap Max
"""

from ..catalog import FIELD_BLENDS
from .core import FALLOFF_INPUTS, TEXTURE_INPUTS, falloff, sound_level, texture
from .formula import compile_expr
from .util import S, ensure, new_group, out, set_menu_defaults

CONTOURS = ("None", "Quadratic", "Ease", "Step", "Quantize")
HEAD = [S("Previous", "FLOAT", 1.0, hide_value=True), S("First", "BOOL", True, hide_value=True),
        S("Element Count", "INT", 1, hide_value=True), S("Layers", "FLOAT", 1.0, hide_value=True),
        S("Transform", "MATRIX", hide_value=True)]
TAIL = [S("Blend", "MENU", desc="How this field combines with the fields above it"),
        S("Opacity", "FLOAT", 1.0, 0.0, 1.0, "FACTOR"),
        S("Invert", "BOOL", False),
        S("Contour", "MENU", desc="Reshape the value: Quadratic, Ease, Step (0/1) or Quantize (Steps levels)"),
        S("Steps", "INT", 4, 1, 100),
        S("Remap Min", "FLOAT", 0.0, desc="Output value where the field is 0"),
        S("Remap Max", "FLOAT", 1.0, desc="Output value where the field is 1")]
FORMULA_VARIABLES = ("x", "y", "z", "id", "count", "t", "f")


def _tail(b, g, raw):
    """Contour -> Invert -> Remap -> x sub-fields -> blend with Previous (first layer: just itself)."""
    w = b.math("MINIMUM", b.math("MAXIMUM", raw, 0.0), 1.0)
    steps = b.at_least(g["Steps"])
    quantized = b.math("MINIMUM", b.math("DIVIDE", b.math("FLOOR", b.math("MULTIPLY", w, steps)),
                                         b.at_least(b.math("SUBTRACT", steps, 1.0))), 1.0)
    w = b.index_switch("FLOAT", b.menu(CONTOURS, g["Contour"]), [
        w, b.math("MULTIPLY", w, w), b.map_range(w, 0.0, 1.0, 0.0, 1.0, "SMOOTHSTEP"),
        b.math("GREATER_THAN", w, 0.4999), quantized])
    w = b.mix("FLOAT", g["Invert"], w, b.math("SUBTRACT", 1.0, w))
    w = b.math("MULTIPLY_ADD", w, b.math("SUBTRACT", g["Remap Max"], g["Remap Min"]), g["Remap Min"])
    w = b.math("MULTIPLY", w, g["Layers"])
    p = g["Previous"]
    inv_p, inv_w = b.math("SUBTRACT", 1.0, p), b.math("SUBTRACT", 1.0, w)
    ops = {"Normal": w, "Multiply": b.math("MULTIPLY", p, w), "Max": b.math("MAXIMUM", p, w),
           "Min": b.math("MINIMUM", p, w), "Add": b.math("ADD", p, w), "Subtract": b.math("SUBTRACT", p, w),
           "Screen": b.math("SUBTRACT", 1.0, b.math("MULTIPLY", inv_p, inv_w)),
           "Average": b.math("MULTIPLY", b.math("ADD", p, w), 0.5),
           "Difference": b.math("ABSOLUTE", b.math("SUBTRACT", p, w))}
    blended = b.index_switch("FLOAT", b.menu(FIELD_BLENDS, g["Blend"]), [ops[k] for k in FIELD_BLENDS])
    blended = b.math("MINIMUM", b.math("MAXIMUM", blended, 0.0), 1.0)
    layered = b.mix("FLOAT", g["Opacity"], p, blended)
    return b.switch("FLOAT", g["First"], layered, b.math("MULTIPLY", w, g["Opacity"]))


def _field_type(name, extra, raw, menus=None):
    def build():
        ng, gin, gout, b = new_group(name, HEAD + extra + TAIL, [S("Weight", "FLOAT")], "MoBlend field layer")
        g = gin.outputs
        b.link(_tail(b, g, raw(b, g)), gout.inputs[0])
        set_menu_defaults(ng, {"Blend": "Normal", "Contour": "None", **(menus or {})})
        return ng
    return build


def _local(b, g):
    return b.to_local(b.position(), g["Transform"])


def _shape(b, g):
    fo = b.group(falloff(), {"Transform": g["Transform"], "Invert": False})
    for spec in FALLOFF_INPUTS:
        if spec["name"] != "Invert":
            b.link(g[spec["name"]], fo.inputs[spec["name"]])
    return fo.outputs["Weight"]


def _time(b, g):
    v = b.math("ADD", b.math("MULTIPLY", b.seconds(), g["Speed"]), g["Offset"])
    return b.index_switch("FLOAT", b.menu(["Loop", "Ping-Pong", "Clamp"], g["Mode"]), [
        b.math("FRACT", v), b.math("PINGPONG", v, 1.0), b.math("MINIMUM", b.math("MAXIMUM", v, 0.0), 1.0)])


def _step(b, g):
    t = b.math("DIVIDE", b.index(), b.steps(g["Element Count"]))
    return b.mix("FLOAT", g["Reverse"], t, b.math("SUBTRACT", 1.0, t))


def _object(b, g):
    """Distance to another object's surface, edges or points (curves count as their edges)."""
    geo = b.object_geometry(g["Object"])
    parts = b.node("GeometryNodeSeparateComponents", {"Geometry": geo})
    target = b.join(out(parts, "Mesh"), b.node("GeometryNodeCurveToMesh", {"Curve": out(parts, "Curve")}).outputs[0],
                    out(parts, "Point Cloud"))
    faces, edges, points = (out(b.node("GeometryNodeProximity", {"Geometry": target, "Source Position": b.position()},
                                       target_element=el), "Distance") for el in ("FACES", "EDGES", "POINTS"))
    size = b.node("GeometryNodeAttributeDomainSize", {"Geometry": target}, component="MESH")
    # Fall back to what the target has: a curve has edges but no faces, a point cloud only points.
    edges = b.switch("FLOAT", b.math("GREATER_THAN", out(size, "Edge Count"), 0.0), points, edges)
    faces = b.switch("FLOAT", b.math("GREATER_THAN", out(size, "Face Count"), 0.0), edges, faces)
    d = b.index_switch("FLOAT", b.menu(["Surface", "Edges", "Points"], g["Mode"]), [faces, edges, points])
    return b.map_range(d, 0.0, b.at_least(g["Distance"], 1e-5), 1.0, 0.0, "SMOOTHSTEP")


def _shader(b, g):
    value, _ = texture(b, g, _local(b, g))
    return value


def _sound(b, g):
    return sound_level(b, g, g["Element Count"])


SHAPE_INPUTS = [s for s in FALLOFF_INPUTS if s["name"] != "Invert"]
SOUND_INPUTS = [
    S("Sound", "SOUND", desc="Audio to listen to (name, or a file path via set_params)"),
    S("Mode", "MENU", desc="Spread: each element gets its own frequency band. All: the whole range"),
    S("Low", "FLOAT", 40.0, 1.0, 22000.0, desc="Lowest frequency (Hz)"),
    S("High", "FLOAT", 12000.0, 1.0, 22000.0, desc="Highest frequency (Hz)"),
    S("Gain", "FLOAT", 4.0, 0.0, desc="Amplitude multiplier before clamping to 1"),
    S("Time Offset", "FLOAT", 0.0, desc="Seconds added to the scene time when sampling"),
]

TYPES = {
    "shape": ("MB Field", SHAPE_INPUTS, _shape, {"Falloff": "Sphere"}),
    "time": ("MB Field Time", [S("Speed", "FLOAT", 0.5, desc="Cycles per second"), S("Offset", "FLOAT", 0.0),
                               S("Mode", "MENU")], _time, {"Mode": "Loop"}),
    "step": ("MB Field Step", [S("Reverse", "BOOL", False)], _step, None),
    "object": ("MB Field Object", [S("Object", "OBJECT", desc="Mesh or curve to measure the distance to"),
                                   S("Mode", "MENU"), S("Distance", "FLOAT", 1.0, 0.0, subtype="DISTANCE",
                                                        desc="Distance at which the value reaches 0")],
               _object, {"Mode": "Surface"}),
    "shader": ("MB Field Shader", TEXTURE_INPUTS, _shader, {"Texture": "Noise"}),
    "sound": ("MB Field Sound", SOUND_INPUTS, _sound, {"Mode": "All"}),
}

BUILDERS = {kind: (lambda spec=spec: ensure(spec[0], _field_type(*spec))) for kind, spec in TYPES.items()}


def formula_group(name, expr):
    """A field type group for one formula field. Variables: x, y, z (field-local position), id, count, t
    (seconds), f (frame). Rebuilt in place whenever the formula changes."""
    def raw(b, g):
        x, y, z = b.separate(_local(b, g))
        env = {"x": x, "y": y, "z": z, "id": b.index(), "count": g["Element Count"], "t": b.seconds(),
               "f": b.inp("GeometryNodeInputSceneTime", "Frame")}
        return compile_expr(b, expr, env)
    return _field_type(name, [], raw)()
