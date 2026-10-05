"""Point deformers placed by an empty, with the same falloff fields as effectors. O(points).

Bend / Twist / Taper / Stretch use Blender's Simple Deform modifier instead
(see api/deformer.py); these are the ones Blender has no modifier for.
"""

import math

from .util import S, geometry_socket, out
from .core import TEXTURE_INPUTS, falloff_group, texture


def _deformer(name, extra, shape, menus=None):
    """`shape(b, g, local) -> new_local` maps points in the deformer's space."""
    def body(b, g, weight):
        pos = b.position()
        new = b.transform_point(shape(b, g, b.to_local(pos, g["Transform"])), g["Transform"])
        moved = b.mix("VECTOR", weight, pos, new, clamp=False)
        return b.node("GeometryNodeSetPosition", {"Geometry": g["Geometry"], "Position": moved}).outputs[0]
    return falloff_group(name, "Geometry", extra, body, "Infinite", menus)


def _wave(b, g, local):
    x, y, z = b.separate(local)
    coord = b.mix("FLOAT", g["Radial"], x, b.vmath("LENGTH", b.combine(x, y)))
    phase = b.math("SUBTRACT", b.math("DIVIDE", coord, g["Wavelength"]), b.math("MULTIPLY", b.seconds(), g["Speed"]))
    dz = b.math("MULTIPLY", b.math("SINE", b.math("MULTIPLY", phase, 2 * math.pi)), g["Amplitude"])
    return b.combine(x, y, b.math("ADD", z, dz))


def _spherify(b, g, local):
    return b.vmath("SCALE", b.vmath("NORMALIZE", local), scale=g["Radius"])


def _shear(b, g, local):
    x, y, z = b.separate(local)
    ax, ay, _ = b.separate(g["Amount"])
    return b.combine(b.math("MULTIPLY_ADD", ax, z, x), b.math("MULTIPLY_ADD", ay, z, y), z)


def _bulge(b, g, local):
    x, y, z = b.separate(local)
    ends = b.math("MINIMUM", b.math("MULTIPLY", z, z), 1.0)  # 0 at the middle, 1 at the caps
    f = b.math("MULTIPLY_ADD", g["Amount"], b.math("SUBTRACT", 1.0, ends), 1.0)
    return b.combine(b.math("MULTIPLY", x, f), b.math("MULTIPLY", y, f), z)


def _displace(b, g, local):
    """Texture-driven displacement: along the normal by the texture's value, or by its color as a vector."""
    value, color = texture(b, g, local)
    inv = b.node("FunctionNodeInvertMatrix", {"Matrix": g["Transform"]}).outputs["Matrix"]
    normal = b.vmath("NORMALIZE", b.node("FunctionNodeTransformDirection", {
        "Direction": b.inp("GeometryNodeInputNormal"), "Transform": inv}).outputs[0])
    along = b.vmath("SCALE", normal, scale=b.math("MULTIPLY", b.math("SUBTRACT", value, 0.5), 2.0))
    vector = b.vmath("SCALE", b.vmath("SUBTRACT", color, (0.5, 0.5, 0.5)), scale=2.0)
    off = b.vmath("SCALE", b.mix("VECTOR", g["Along Normal"], vector, along), scale=g["Amplitude"])
    return b.vmath("ADD", local, off)


def _moextrude(b, g, weight):
    """C4D MoExtrude: extrude faces Steps times, Offset and Scale per step, scaled per face by the falloff /
    fields (so effector-like fields drive the extrusion). Selection limits it to an attribute or vertex group.
    O(Steps x selected faces)."""
    sel = b.node("GeometryNodeInputNamedAttribute", {"Name": g["Selection"]}, data_type="FLOAT")
    first = b.switch("BOOLEAN", out(sel, "Exists"), True, b.math("GREATER_THAN", out(sel, "Attribute"), 0.5))
    geo = b.store(g["Geometry"], "mb_top", first, "BOOLEAN", "FACE")
    rep_in, rep_out = b.node("GeometryNodeRepeatInput"), b.node("GeometryNodeRepeatOutput")
    rep_in.pair_with_output(rep_out)
    b.set(rep_in, "Iterations", g["Steps"])
    b.link(geo, geometry_socket(rep_in.inputs))
    top = b.named("mb_top", "BOOLEAN")
    ext = b.node("GeometryNodeExtrudeMesh", {"Mesh": geometry_socket(rep_in.outputs), "Selection": top,
                                             "Offset Scale": b.math("MULTIPLY", g["Offset"], weight),
                                             "Individual": True}, mode="FACES")
    stepped = b.store(out(ext, "Mesh"), "mb_top", out(ext, "Top"), "BOOLEAN", "FACE")
    stepped = b.node("GeometryNodeScaleElements", {"Geometry": stepped, "Selection": top,
                                                   "Scale": b.mix("FLOAT", weight, 1.0, g["Scale"])},
                     domain="FACE").outputs[0]
    b.link(stepped, geometry_socket(rep_out.inputs))
    return geometry_socket(rep_out.outputs)



BUILDERS = {
    "wave": _deformer("MB Deformer Wave", [
        S("Amplitude", "FLOAT", 0.3), S("Wavelength", "FLOAT", 1.0, 0.001),
        S("Speed", "FLOAT", 0.5, desc="Waves per second"),
        S("Radial", "BOOL", False, desc="Ripple outward from the center")], _wave),
    "spherify": _deformer("MB Deformer Spherify", [S("Radius", "FLOAT", 1.0, 0.0)], _spherify),
    "shear": _deformer("MB Deformer Shear", [S("Amount", "VECTOR", (0.5, 0.0, 0.0), subtype="XYZ")], _shear),
    "bulge": _deformer("MB Deformer Bulge", [S("Amount", "FLOAT", 0.5)], _bulge),
    "displace": _deformer("MB Deformer Displace", [S("Amplitude", "FLOAT", 0.2)] + TEXTURE_INPUTS + [
        S("Along Normal", "BOOL", True, desc="Push along the normal by the texture's value (off: by its color)")],
        _displace, {"Texture": "Noise"}),
    "moextrude": falloff_group("MB MoExtrude", "Geometry", [
        S("Steps", "INT", 3, 0, 100), S("Offset", "FLOAT", 0.2, subtype="DISTANCE", desc="Extrusion per step"),
        S("Scale", "FLOAT", 0.9, 0.0, desc="Face scale per step"),
        S("Selection", "STRING", "", desc="Attribute / vertex group of faces to extrude (empty: all)")],
        _moextrude, "Infinite"),
}
