"""Point deformers placed by an empty, with the same falloff fields as effectors. O(points).

Bend / Twist / Taper / Stretch use Blender's Simple Deform modifier instead
(see api/deformer.py); these are the ones Blender has no modifier for.
"""

import math

from .util import S, out
from .core import falloff_group


def _deformer(name, extra, shape):
    """`shape(b, g, local) -> new_local` maps points in the deformer's space."""
    def body(b, g, weight):
        pos = b.position()
        new = b.transform_point(shape(b, g, b.to_local(pos, g["Transform"])), g["Transform"])
        moved = b.mix("VECTOR", weight, pos, new, clamp=False)
        return b.node("GeometryNodeSetPosition", {"Geometry": g["Geometry"], "Position": moved}).outputs[0]
    return falloff_group(name, "Geometry", extra, body, "Infinite")


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
    nz = b.noise4d(b.vmath("SCALE", local, scale=g["Noise Size"]), b.math("MULTIPLY", b.seconds(), g["Speed"]),
                   detail=2.0)
    off = b.vmath("SCALE", b.vmath("SUBTRACT", out(nz, "Color"), (0.5, 0.5, 0.5)),
                  scale=b.math("MULTIPLY", g["Amplitude"], 2.0))
    return b.vmath("ADD", local, off)


BUILDERS = {
    "wave": _deformer("MB Deformer Wave", [
        S("Amplitude", "FLOAT", 0.3), S("Wavelength", "FLOAT", 1.0, 0.001),
        S("Speed", "FLOAT", 0.5, desc="Waves per second"),
        S("Radial", "BOOL", False, desc="Ripple outward from the center")], _wave),
    "spherify": _deformer("MB Deformer Spherify", [S("Radius", "FLOAT", 1.0, 0.0)], _spherify),
    "shear": _deformer("MB Deformer Shear", [S("Amount", "VECTOR", (0.5, 0.0, 0.0), subtype="XYZ")], _shear),
    "bulge": _deformer("MB Deformer Bulge", [S("Amount", "FLOAT", 0.5)], _bulge),
    "displace": _deformer("MB Deformer Displace", [
        S("Amplitude", "FLOAT", 0.2), S("Noise Size", "FLOAT", 1.5, 0.0), S("Speed", "FLOAT", 0.2)], _displace),
}
